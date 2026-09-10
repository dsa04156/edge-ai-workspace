"""Adjacent-hop demo using the existing request journal, transport and workers.

Execution order and physical role are independent: edge -> edge -> server.
Lower hops remain warm for a return; abandoned upper hops unload after drain.
"""
from __future__ import annotations

import asyncio
import json
import time

from .model_offload_controller import ModelOffloadError, ModelOffloadExecutionController
from .runtime_recommendation import recommend_model_offload


class OrderedModelOffloadExecutionController(ModelOffloadExecutionController):
    def __init__(self, contract, journal, transport=None):
        if not contract.execution_order:
            raise ValueError("ordered_execution_contract_required")
        super().__init__(contract, journal, transport)
        self.order = contract.execution_order
        self.touched: set[str] = set()
        self.reached_top = False
        previous = self.journal.db.execute("SELECT value FROM metadata WHERE key='ordered-runtime'").fetchone()
        if previous:
            saved = json.loads(previous[0])
            self.touched = set(saved["touched"])
            self.cycles = saved["cycles"]
        elif self.selected:
            self.touched.add(self.selected)
        # Never resume an uncertain cutover after restart. Drain all touched hops
        # from the permanent source, retaining every unknown request in the WAL.
        self.selected = None
        self.recovering = bool(self.touched)

    def transition(self, state: str, reason: str) -> None:
        # Admission/dispatch may fail while an adjacent-hop probe is awaiting.
        # Mark recovery immediately: that action can replace DRAINING before
        # the next tick, but must never turn an interrupted route into a cycle.
        if state == "DRAINING":
            self.recovering = True
            self.reached_top = False
        saved = {"target": self.target, "selected": self.selected,
                 "touched": sorted(self.touched), "cycles": self.cycles,
                 "reached_top": self.reached_top}
        with self.journal.db:
            self.journal.db.execute("INSERT OR REPLACE INTO metadata VALUES ('ordered-runtime',?)",
                                    (json.dumps(saved),))
            self.journal.db.execute("INSERT INTO events(at,state,reason,selected) VALUES(?,?,?,?)",
                                    (time.time(), state, reason, self.selected))
        self.state, self.reason = state, reason
        self.changed_at = time.monotonic()
        self.high_since = self.low_since = None

    def snapshot(self) -> dict:
        result = super().snapshot()
        index = self.order.index(self.target)
        result.update(execution_order=self.order, current_level=index,
                      next_hop=self.order[index + 1] if index + 1 < len(self.order) else None,
                      previous_hop=self.order[index - 1] if index else None,
                      retained_models=sorted(self.touched), reached_top=self.reached_top,
                      recovering=self.recovering)
        return result

    def stable_state(self) -> str:
        return "LOCAL" if self.target == self.edge else "REMOTE"

    def resource_ready(self, node: str) -> bool:
        sample = self.samples.get(node, {})
        ram, rtt = sample.get("ram_utilization_percent"), sample.get("management_rtt_ms")
        return (self.workers[node].qualified and self.healthy(node, ready=False)
                and sample.get("runtime_placement_verified") is True
                and isinstance(ram, (int, float)) and 0 <= ram <= self.workers[node].max_ram_percent
                and isinstance(rtt, (int, float)) and 0 <= rtt <= self.workers[node].max_management_rtt_ms)

    async def move(self, source: str, destination: str, *, upward: bool) -> None:
        expected_state = "PREPARING" if upward else "RETURNING"
        try:
            async with asyncio.timeout(self.contract.action_timeout_seconds):
                if not self.resource_ready(destination):
                    raise ModelOffloadError("next_hop_resource_gate_failed")
                if not self.healthy(destination):
                    await self.transport.lifecycle(self.workers[destination], "activate")
                await self.probe(destination)
                if self.target != source or self.state != expected_state:
                    raise ModelOffloadError("route_changed_during_prepare")
                if not self.healthy(source) or not self.resource_ready(destination):
                    raise ModelOffloadError("handoff_health_gate_failed")
                ceiling = self.workers[destination].capacity_rps
                if not upward:
                    ceiling *= self.contract.low_ratio
                if self.rate() > ceiling:
                    raise ModelOffloadError("handoff_load_changed")
                self.target = destination
                self.selected = destination if destination != self.edge else None
                if destination == self.order[-1]:
                    self.reached_top = True
                # The released hop must be idle for the full dwell after handoff.
                if self.order.index(source) > self.order.index(destination):
                    self.last_finished[source] = time.monotonic()
                self.transition(self.stable_state(), "next_hop_verified" if upward else "previous_hop_verified")
        except Exception as exc:
            self.selected = self.target if self.target != self.edge else None
            self.last_finished[destination] = time.monotonic()
            self.transition(self.stable_state(), exc.reason if isinstance(exc, ModelOffloadError)
                            else "adjacent_hop_prepare_failed")

    def drained_hop(self, node: str) -> bool:
        sample = self.samples.get(node, {})
        return (self.healthy(node, ready=False) and not self.inflight[node] and self.queues[node].empty()
                and sample.get("active_requests") == 0 and sample.get("queue_length") == 0
                and time.monotonic() - self.last_finished[node] >= self.contract.idle_seconds)

    def finish_cycle(self) -> None:
        if self.target != self.edge or self.touched:
            return
        if self.reached_top:
            self.cycles += 1
        self.reached_top = False
        self.recovering = False
        self.selected = None
        self.transition("LOCAL", "ordered_models_released_rearmed")

    async def release_hop(self, node: str) -> None:
        try:
            async with asyncio.timeout(self.contract.action_timeout_seconds):
                self.samples[node] = await self.transport.snapshot(self.workers[node])
                if (self.order.index(node) <= self.order.index(self.target)
                        or not self.healthy(self.target) or not self.drained_hop(node)):
                    raise ModelOffloadError("ordered_release_drain_gate_failed")
                self.journal.event(self.state, "release_hop:" + node, self.selected)
                await self.transport.lifecycle(self.workers[node], "release")
                sample = self.samples[node] = await self.transport.snapshot(self.workers[node])
                if (not self.healthy(node, ready=False) or sample.get("node_state") != "CACHED"
                        or sample.get("model_loaded") is not False or sample.get("model_vram_mib") != 0
                        or sample.get("active_requests") != 0 or sample.get("queue_length") != 0):
                    raise ModelOffloadError("ordered_release_readback_failed")
            self.touched.remove(node)
            # Cleanup is not a route change: preserve route dwell/cooldown clocks.
            changed, high, low = self.changed_at, self.high_since, self.low_since
            self.transition(self.stable_state(), "released_hop:" + node)
            self.changed_at, self.high_since, self.low_since = changed, high, low
            self.finish_cycle()
        except Exception:
            self.last_finished[node] = time.monotonic()
            self.journal.event(self.state, "release_hop_not_verified:" + node, self.selected)

    async def tick(self) -> None:
        if self.closing:
            return
        now, rate = time.monotonic(), self.rate()
        self.accepting = self.running and self.healthy(self.target)
        if self.state == "RECOVERING":
            if not self.healthy(self.edge):
                return
            self.transition("LOCAL", "ordered_startup_edge_verified")
        if self.target != self.edge and not self.healthy(self.target):
            self.target = self.edge
            self.selected = None
            self.recovering = True
            self.reached_top = False
            self.transition("LOCAL", "emergency_source_fallback")
        if self.state == "DRAINING":
            # Base admission/dispatch handling also falls back to the permanent
            # source. Keep all touched hops for independent, verified cleanup.
            self.recovering = True
            self.reached_top = False
            self.selected = self.target if self.target != self.edge else None
            self.transition(self.stable_state(), "emergency_source_fallback")
        if self.action and not self.action.done():
            return
        index = self.order.index(self.target)
        for node in reversed(self.order[index + 1:]):
            if node in self.touched and self.healthy(self.target) and self.drained_hop(node):
                self.launch(self.release_hop(node))
                return
        if self.recovering:
            if not self.touched:
                self.finish_cycle()
            return
        # No skipping: only index + 1 is evaluated for an upward move, even if
        # a farther node would score better. Missing qualification blocks that hop.
        self.recommendation = recommend_model_offload(
            self.contract, self.samples, now, rate, self.queues[self.target].qsize(),
            self.inflight[self.target], current_node=self.target)
        pressure = self.recommendation.get("pressure") and self.healthy(self.target)
        self.high_since = (now if self.high_since is None else self.high_since) if pressure else None
        if (pressure and now - self.high_since >= self.contract.pressure_seconds
                and now - self.changed_at >= self.contract.cooldown_seconds
                and self.recommendation["selected_node"]):
            destination = self.recommendation["selected_node"]
            self.selected = destination
            self.touched.add(destination)
            self.transition("PREPARING", "ordered_next_hop_selected")
            self.launch(self.move(self.target, destination, upward=True))
            return
        if index:
            previous = self.order[index - 1]
            low = (rate <= self.contract.low_ratio * self.workers[previous].capacity_rps
                   and self.resource_ready(previous))
            self.low_since = (now if self.low_since is None else self.low_since) if low else None
            if (low and now - self.low_since >= self.contract.return_seconds
                    and now - self.changed_at >= self.contract.cooldown_seconds):
                self.selected = previous
                self.transition("RETURNING", "ordered_previous_hop_low_dwell")
                self.launch(self.move(self.target, previous, upward=False))
