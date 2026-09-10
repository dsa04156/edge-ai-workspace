"""Continuous, request-pinned model executor for Runtime Recommendation/Plan.

One controller process and a persistent filesystem per reviewed service. No
Kubernetes mutations. Dispatched requests of uncertain outcome are never replayed.
"""
from __future__ import annotations

import asyncio
from collections import deque
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any

import httpx

from .model_offload_contract import ModelOffloadContract, ModelWorker, worker_reasons
from .runtime_recommendation import recommend_model_offload
from .runtime_execution_plan import build_model_offload_execution_plan


class ModelOffloadError(Exception):
    def __init__(self, reason: str, status_code: int = 503):
        super().__init__(reason)
        self.reason, self.status_code = reason, status_code


class WorkerTransport:
    def __init__(self, contract: ModelOffloadContract, kube=None):
        self.contract = contract
        self.kube = kube
        self.placement_cache: dict[str, tuple[float, bool]] = {}
        self.client = httpx.AsyncClient(timeout=contract.action_timeout_seconds, trust_env=False,
                                       limits=httpx.Limits(max_connections=32))

    async def snapshot(self, worker: ModelWorker) -> dict:
        started = time.monotonic()
        responses = await asyncio.gather(*[
            self.client.get(worker.endpoint + path, timeout=2)
            for path in ("/metrics", "/health")])
        for response in responses:
            response.raise_for_status()
        return {**responses[0].json(), **responses[1].json(),
                "management_rtt_ms": 1000 * (time.monotonic() - started),
                "runtime_placement_verified": await self.placement_verified(worker),
                "observed_at": started}

    async def placement_verified(self, worker: ModelWorker) -> bool:
        """Read only: actual node Ready/no pressure and the reviewed running image.

        The existing GPU reservation belongs to the resident Pod; do not demand
        another free GPU slot as if this were a new workload placement.
        """
        cached = self.placement_cache.get(worker.node)
        if cached and time.monotonic() - cached[0] < 2:
            return cached[1]
        if self.kube is None or not self.kube.enabled:
            return False
        started = time.monotonic()
        def read() -> bool:
            node = self.kube.v1.read_node(worker.node, _request_timeout=2)
            conditions = {c.type: c.status for c in node.status.conditions or []}
            if (conditions.get("Ready") != "True" or node.spec.unschedulable
                    or any(conditions.get(key) != "False" for key in
                           ("MemoryPressure", "DiskPressure", "PIDPressure"))):
                return False
            pods = self.kube.v1.list_namespaced_pod(
                worker.runtime_namespace, label_selector=worker.runtime_selector, _request_timeout=2).items
            for pod in pods:
                if pod.metadata.deletion_timestamp or pod.spec.node_name != worker.node:
                    continue
                statuses = {c.name: c for c in pod.status.container_statuses or []}
                for container in pod.spec.containers:
                    status = statuses.get(container.name)
                    if (container.name == worker.runtime_container and container.image == worker.runtime_image
                            and status and status.ready and status.state.running is not None):
                        return True
            return False
        try:
            verified = await asyncio.to_thread(read)
        except Exception:
            verified = False
        self.placement_cache[worker.node] = (started, verified)
        return verified

    async def lifecycle(self, worker: ModelWorker, action: str) -> dict:
        path, target = ("/activate", "ACTIVE") if action == "activate" else ("/deactivate", "CACHED")
        response = await self.client.post(worker.endpoint + path,
                                          json={"target_state": target, "reason": "runtime_model_offload"})
        response.raise_for_status()
        return response.json()

    async def generate(self, worker: ModelWorker, request_id: str, on_token=None) -> dict:
        result = None
        saw_token = False
        async with self.client.stream("POST", worker.endpoint + "/generate/stream", json={
            "request_id": request_id, "prompt": self.contract.prompt,
            "max_tokens": self.contract.max_tokens,
        }) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get("type") == "token" and event.get("text"):
                    if not saw_token and on_token:
                        on_token()
                    saw_token = True
                elif event.get("type") == "result":
                    result = event.get("result", event)
                elif event.get("type") == "error":
                    raise ModelOffloadError("worker_stream_error")
        if (not saw_token or not result or result.get("request_id") != request_id
                or result.get("node_id") != worker.node
                or result.get("model_digest") != worker.model_digest):
            raise ModelOffloadError("inference_identity_or_stream_failed")
        return result

    async def close(self) -> None:
        await self.client.aclose()


class OffloadJournal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = path.with_suffix(path.suffix + ".lock").open("a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ModelOffloadError("controller_already_owns_journal") from None
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, node TEXT NOT NULL,
                status TEXT NOT NULL, admitted REAL NOT NULL, result TEXT);
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY, at REAL NOT NULL, state TEXT NOT NULL,
                reason TEXT NOT NULL, selected TEXT);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def bind(self, contract: ModelOffloadContract) -> None:
        encoded = json.dumps(contract.model_dump(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self.db.execute("SELECT value FROM metadata WHERE key='contract'").fetchone()
        if existing and existing[0] != digest:
            raise ModelOffloadError("journal_contract_changed_requires_reconciliation")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('contract', ?)", (digest,))
            self.db.execute("UPDATE requests SET status='unknown' WHERE status='dispatched'")
            self.db.execute("UPDATE requests SET status='interrupted' WHERE status='queued'")

    def event(self, state: str, reason: str, selected: str | None) -> None:
        with self.db:
            self.db.execute("INSERT INTO events(at,state,reason,selected) VALUES(?,?,?,?)",
                            (time.time(), state, reason, selected))

    def request(self, request_id: str) -> dict | None:
        row = self.db.execute("SELECT id,fingerprint,node,status,admitted,result FROM requests WHERE id=?",
                              (request_id,)).fetchone()
        if not row:
            return None
        return dict(zip(("request_id", "fingerprint", "node", "status", "admitted_at", "result"),
                        (*row[:5], json.loads(row[5]) if row[5] else None)))

    def status(self, request_id: str, status: str, result: dict | None = None) -> None:
        with self.db:
            self.db.execute("UPDATE requests SET status=?,result=? WHERE id=?",
                            (status, json.dumps(result) if result else None, request_id))

    def events(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute("SELECT sequence,at,state,reason,selected FROM events ORDER BY sequence DESC LIMIT ?",
                               (min(1000, max(1, limit)),)).fetchall()
        return [dict(zip(("sequence", "at", "state", "reason", "selected_node"), row)) for row in rows]

    def close(self) -> None:
        self.db.close()
        self.lock.close()


class ModelOffloadExecutionController:
    def __init__(self, contract: ModelOffloadContract, journal: OffloadJournal,
                 transport: Any = None):
        self.contract, self.journal = contract, journal
        self.journal.bind(contract)
        self.transport = transport or WorkerTransport(contract)
        self.workers = {worker.node: worker for worker in contract.workers}
        self.edge = contract.edge.node
        self.target = self.edge
        self.selected: str | None = None
        previous = journal.events(1)
        if previous:
            self.selected = previous[0]["selected_node"]
        self.state = "RECOVERING"
        self.reason = "startup_reconciliation"
        self.samples: dict[str, dict] = {}
        self.queues = {node: asyncio.Queue() for node in self.workers}
        self.worker_locks = {node: asyncio.Lock() for node in self.workers}
        self.inflight = {node: 0 for node in self.workers}
        self.arrivals: deque[float] = deque()
        self.futures: dict[str, asyncio.Future] = {}
        self.started_at = time.monotonic()
        self.changed_at = self.started_at
        self.last_remote = self.started_at
        self.last_finished = {node: self.started_at for node in self.workers}
        self.high_since: float | None = None
        self.low_since: float | None = None
        self.recommendation: dict = {"service_id": contract.service_id, "tier": "edge",
                                     "selected_node": None, "reason_codes": [self.reason]}
        self.tasks: list[asyncio.Task] = []
        self.action: asyncio.Task | None = None
        self.running = False
        self.closing = False
        self.accepting = False
        self.cycles = 0

    def transition(self, state: str, reason: str) -> None:
        # Commit intent before publishing the in-memory state or starting an action.
        self.journal.event(state, reason, self.selected)
        self.state, self.reason = state, reason
        self.changed_at = time.monotonic()
        self.high_since = self.low_since = None

    def healthy(self, node: str, *, ready: bool = True) -> bool:
        return not worker_reasons(self.workers[node], self.samples.get(node, {}),
                                  time.monotonic(), self.contract.fresh_seconds, ready=ready)

    def rate(self) -> float:
        now = time.monotonic()
        while self.arrivals and self.arrivals[0] < now - self.contract.rate_window_seconds:
            self.arrivals.popleft()
        return len(self.arrivals) / self.contract.rate_window_seconds

    def snapshot(self) -> dict:
        return {"service_id": self.contract.service_id, "state": self.state,
                "reason_code": self.reason, "target_node": self.target,
                "target_tier": self.workers[self.target].role, "selected_worker": self.selected,
                "selected_server": self.selected if self.selected and self.workers[self.selected].role == "server" else None,
                "cycles_completed": self.cycles, "accepting": self.accepting,
                "arrival_rps": self.rate(), "recommendation": self.recommendation,
                "execution_plan": build_model_offload_execution_plan(self.recommendation),
                "workers": [{"node": worker.node, "role": worker.role,
                             "healthy": self.healthy(worker.node),
                             "queued": self.queues[worker.node].qsize(),
                             "inflight": self.inflight[worker.node],
                             "observation": self.samples.get(worker.node)}
                            for worker in self.workers.values()]}

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.journal.event(self.state, self.reason, self.selected)
        self.tasks = [asyncio.create_task(self.poll(worker)) for worker in self.workers.values()]
        self.tasks += [asyncio.create_task(self.consume(node)) for node in self.workers]
        self.tasks.append(asyncio.create_task(self.monitor()))

    async def poll(self, worker: ModelWorker) -> None:
        while self.running:
            try:
                self.samples[worker.node] = await self.transport.snapshot(worker)
            except Exception:
                self.samples[worker.node] = {"reason_code": "worker_observation_failed"}
            await asyncio.sleep(.5)

    async def submit(self, request_id: str, prompt: str, max_tokens: int) -> dict:
        if not request_id or len(request_id) > 128:
            raise ModelOffloadError("invalid_request_id", 422)
        if prompt != self.contract.prompt or max_tokens != self.contract.max_tokens:
            raise ModelOffloadError("request_outside_qualified_contract", 422)
        fingerprint = hashlib.sha256(json.dumps([prompt, max_tokens]).encode()).hexdigest()
        existing = self.journal.request(request_id)
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise ModelOffloadError("request_id_payload_conflict", 409)
            future = self.futures.get(request_id)
            if future:
                return await asyncio.shield(future)
            return existing
        if self.target != self.edge and not self.healthy(self.target):
            self.target = self.edge
            self.transition("DRAINING", "remote_unavailable_at_admission")
            self.accepting = self.running and not self.closing and self.healthy(self.edge)
        if not self.accepting or not self.healthy(self.target):
            raise ModelOffloadError("routing_target_not_ready")
        self.arrivals.append(time.monotonic())
        if sum(queue.qsize() for queue in self.queues.values()) >= self.contract.queue_limit:
            raise ModelOffloadError("admission_queue_full", 429)
        # No await between selecting target, durable admission and enqueuing.
        with self.journal.db:
            self.journal.db.execute("INSERT INTO requests VALUES(?,?,?,?,?,NULL)",
                                    (request_id, fingerprint, self.target, "queued", time.time()))
        future = asyncio.get_running_loop().create_future()
        self.futures[request_id] = future
        self.queues[self.target].put_nowait((request_id, time.monotonic()))
        return await asyncio.shield(future)

    async def consume(self, node: str) -> None:
        queue = self.queues[node]
        while self.running:
            request_id, admitted = await queue.get()
            self.inflight[node] += 1
            dispatched = False
            try:
                async with self.worker_locks[node]:
                    if not self.healthy(node):
                        raise ModelOffloadError("pinned_target_unavailable_before_dispatch")
                    self.journal.status(request_id, "dispatched")
                    dispatched = True
                    first_token: list[float] = []
                    async with asyncio.timeout(self.contract.action_timeout_seconds):
                        result = await self.transport.generate(
                            self.workers[node], request_id,
                            lambda: first_token.append(1000 * (time.monotonic() - admitted)))
                    result["gateway_latency_ms"] = 1000 * (time.monotonic() - admitted)
                    result["gateway_ttft_ms"] = first_token[0] if first_token else None
                    self.journal.status(request_id, "ok", result)
            except Exception as exc:
                self.journal.status(request_id, "unknown" if dispatched else "failed_unsent",
                                    {"reason_code": exc.reason if isinstance(exc, ModelOffloadError)
                                     else "worker_request_failed"})
                if node != self.edge and self.target == node:
                    self.target = self.edge
                    self.transition("DRAINING", "remote_failure_new_requests_return_to_edge")
            finally:
                self.inflight[node] -= 1
                self.last_finished[node] = time.monotonic()
                if node != self.edge:
                    self.last_remote = time.monotonic()
                future = self.futures.pop(request_id, None)
                if future and not future.done():
                    future.set_result(self.journal.request(request_id))
                queue.task_done()

    async def probe(self, node: str) -> None:
        async with self.worker_locks[node]:
            await self.transport.generate(self.workers[node], "probe-" + uuid.uuid4().hex)
        self.samples[node] = await self.transport.snapshot(self.workers[node])
        if not self.healthy(node):
            raise ModelOffloadError("probe_readback_failed")

    def launch(self, coroutine) -> None:
        self.action = asyncio.create_task(coroutine)

    async def prepare(self) -> None:
        node = self.selected
        assert node is not None
        try:
            async with asyncio.timeout(self.contract.action_timeout_seconds):
                if not self.healthy(node, ready=False):
                    raise ModelOffloadError("candidate_stale_before_activation")
                if self.samples[node].get("runtime_placement_verified") is not True:
                    raise ModelOffloadError("candidate_placement_unverified")
                await self.transport.lifecycle(self.workers[node], "activate")
                await self.probe(node)
                if self.state != "PREPARING" or not self.healthy(self.edge):
                    raise ModelOffloadError("prepare_source_or_state_changed")
                if self.rate() > self.workers[node].capacity_rps:
                    raise ModelOffloadError("prepared_candidate_capacity_exceeded")
                sample = self.samples[node]
                ram = sample.get("ram_utilization_percent")
                if (sample.get("runtime_placement_verified") is not True
                        or not isinstance(ram, (int, float))
                        or not 0 <= ram <= self.workers[node].max_ram_percent):
                    raise ModelOffloadError("prepared_candidate_resource_gate_failed")
                self.transition("REMOTE", "server_actual_inference_verified")
                self.target = node
        except Exception:
            self.target = self.edge
            self.last_remote = time.monotonic()
            self.transition("DRAINING", "prepare_failed_or_admission_changed")

    async def return_to_edge(self) -> None:
        try:
            async with asyncio.timeout(self.contract.action_timeout_seconds):
                await self.probe(self.edge)
            if self.state != "RETURNING":
                return
            if self.rate() > self.contract.low_ratio * self.contract.edge.capacity_rps:
                self.transition("REMOTE", "return_load_rebounded")
                return
            self.transition("DRAINING", "edge_actual_inference_verified")
            self.target = self.edge
        except Exception:
            if self.state == "RETURNING":
                self.transition("REMOTE", "edge_probe_failed")

    def drained(self, node: str) -> bool:
        sample = self.samples.get(node, {})
        return (self.healthy(node, ready=False) and not self.inflight[node] and self.queues[node].empty()
                and sample.get("active_requests") == 0 and sample.get("queue_length") == 0
                and time.monotonic() - self.last_remote >= self.contract.idle_seconds)

    async def release(self) -> None:
        node = self.selected
        assert node is not None
        try:
            async with asyncio.timeout(self.contract.action_timeout_seconds):
                # Fresh readback closes the stale idle-observation window.
                self.samples[node] = await self.transport.snapshot(self.workers[node])
                if self.target != self.edge or not self.healthy(self.edge) or not self.drained(node):
                    raise ModelOffloadError("release_drain_gate_failed")
                await self.transport.lifecycle(self.workers[node], "release")
                sample = self.samples[node] = await self.transport.snapshot(self.workers[node])
                if (not self.healthy(node, ready=False) or sample.get("node_state") != "CACHED"
                        or sample.get("model_loaded") is not False or sample.get("model_vram_mib") != 0
                        or sample.get("active_requests") != 0 or sample.get("queue_length") != 0):
                    raise ModelOffloadError("model_release_readback_failed")
            self.cycles += 1
            self.selected = None
            self.transition("LOCAL", "model_released_rearmed_after_cooldown")
        except Exception:
            # Remain drainable; wait a fresh idle interval before retrying unload.
            self.last_remote = time.monotonic()
            self.transition("DRAINING", "release_not_verified")

    async def tick(self) -> None:
        if self.closing:
            return
        now, rate = time.monotonic(), self.rate()
        self.accepting = self.running and self.healthy(self.target)
        if self.state == "RECOVERING":
            if not self.healthy(self.edge):
                return
            self.last_remote = now
            self.transition("DRAINING" if self.selected else "LOCAL", "startup_edge_verified")
        if self.target != self.edge and not self.healthy(self.target):
            self.target = self.edge
            self.transition("DRAINING", "remote_observation_lost")
        if self.action and not self.action.done():
            return
        if self.state == "LOCAL":
            self.recommendation = recommend_model_offload(
                self.contract, self.samples, now, rate,
                self.queues[self.edge].qsize(), self.inflight[self.edge])
            pressure = self.recommendation.get("pressure") and self.healthy(self.edge)
            self.high_since = (now if self.high_since is None else self.high_since) if pressure else None
            if (pressure and now - self.high_since >= self.contract.pressure_seconds
                    and now - self.changed_at >= self.contract.cooldown_seconds
                    and self.recommendation["selected_node"]):
                self.selected = self.recommendation["selected_node"]
                self.transition("PREPARING", "server_tier_and_candidate_selected")
                self.launch(self.prepare())
        elif self.state == "REMOTE":
            low = rate <= self.contract.low_ratio * self.contract.edge.capacity_rps and self.healthy(self.edge)
            self.low_since = (now if self.low_since is None else self.low_since) if low else None
            if (low and now - self.low_since >= self.contract.return_seconds
                    and now - self.changed_at >= self.contract.cooldown_seconds):
                self.transition("RETURNING", "total_arrival_rate_low_dwell")
                self.launch(self.return_to_edge())
        elif self.state == "DRAINING" and self.selected and self.healthy(self.edge) and self.drained(self.selected):
            self.transition("RELEASING", "server_queue_and_inflight_drained")
            self.launch(self.release())

    async def monitor(self) -> None:
        while self.running:
            try:
                await self.tick()
            except Exception:
                self.accepting = False
                self.reason = "controller_tick_failed"
            await asyncio.sleep(.1)

    async def stop(self) -> None:
        self.closing = True
        self.accepting = False
        # Finish accepted work; a process kill is recovered conservatively via WAL.
        if self.action:
            await self.action
        await asyncio.gather(*(queue.join() for queue in self.queues.values()))
        self.running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.transport.close()
        self.journal.close()
