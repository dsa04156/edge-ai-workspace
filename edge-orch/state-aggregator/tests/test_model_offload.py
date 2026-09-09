from __future__ import annotations

import asyncio
from collections import deque
import json
from pathlib import Path
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.model_offload_api import create_model_offload_router
from app.model_offload_contract import ModelOffloadContract, recommend_model_offload, overlap_forecast
from app.model_offload_controller import (
    ModelOffloadError, ModelOffloadExecutionController, OffloadJournal, WorkerTransport,
)


def contract():
    return ModelOffloadContract.model_validate_json(
        (Path(__file__).parents[1] / "app/config/model_offload_llama.json").read_text())


def sample(worker, **updates):
    return {"node_id": worker.node, "model_digest": worker.model_digest,
            "observed_at": time.monotonic(), "management_runtime_running": True,
            "model_cached": True, "inference_ready": True, "model_loaded": True,
            "node_state": "ACTIVE", "model_vram_mib": 1000,
            "active_requests": 0, "queue_length": 0, "ram_utilization_percent": 30,
            "management_rtt_ms": 3, "runtime_placement_verified": True, **updates}


def test_role_first_then_best_measured_server_without_node_name_assumptions():
    c = contract()
    edge, server = c.workers
    faster = server.model_copy(update={"node": "server-b", "endpoint": "http://b.test.svc.cluster.local:18110",
                                       "service_ms": 100, "activation_ms": 1000})
    c = c.model_copy(update={"workers": [edge, server, faster]})
    snapshots = {w.node: sample(w) for w in c.workers}
    low = recommend_model_offload(c, snapshots, time.monotonic(), 2, 0, 0)
    assert low["tier"] == "edge" and low["candidates"] == []
    high = recommend_model_offload(c, snapshots, time.monotonic(), 4.8, 0, 1)
    assert high["selected_node"] == "server-b"
    assert high["tier"] == "server"
    snapshots[faster.node]["model_digest"] = "wrong"
    assert recommend_model_offload(c, snapshots, time.monotonic(), 4.8, 0, 1)["selected_node"] == server.node


@pytest.mark.parametrize("updates,reason", [
    ({"observed_at": -1000}, "worker_observation_stale"),
    ({"model_digest": "wrong"}, "model_digest_mismatch"),
    ({"node_id": "substitute"}, "worker_identity_mismatch"),
    ({"ram_utilization_percent": None}, "ram_utilization_percent_unavailable_or_exceeded"),
    ({"ram_utilization_percent": float("nan")}, "ram_utilization_percent_unavailable_or_exceeded"),
    ({"management_rtt_ms": 5000}, "management_rtt_ms_unavailable_or_exceeded"),
    ({"active_requests": 1}, "candidate_busy"),
    ({"model_cached": False}, "qualified_model_cache_missing"),
    ({"runtime_placement_verified": False}, "runtime_placement_unverified"),
])
def test_candidate_exclusion(updates, reason):
    c = contract()
    snapshots = {w.node: sample(w) for w in c.workers}
    snapshots[c.workers[1].node].update(updates)
    decision = recommend_model_offload(c, snapshots, time.monotonic(), 4.8, 0, 1)
    assert decision["selected_node"] is None
    assert reason in decision["candidates"][0]["reason_codes"]


def test_over_capacity_and_slow_candidate_stay_edge():
    c = contract()
    snapshots = {w.node: sample(w) for w in c.workers}
    assert recommend_model_offload(c, snapshots, time.monotonic(), 6, 0, 0)["selected_node"] is None
    slow = c.workers[1].model_copy(update={"service_ms": 1000})
    c = c.model_copy(update={"workers": [c.edge, slow]})
    assert recommend_model_offload(c, snapshots, time.monotonic(), 4.8, 0, 0)["selected_node"] is None


def test_fixed_configuration_matches_frozen_qualification_forecast():
    c = contract()
    root = Path(__file__).resolve().parents[3]
    frozen = json.loads((root / "docs/assets/nano-agx-continuity-20260908/policy.json").read_text())
    forecast = overlap_forecast(c, c.workers[1], 4.8, 0, 0)
    assert forecast["gain"] == pytest.approx(frozen["qualification_forecast"]["gain"])
    assert c.queue_limit == frozen["queue_limit"]


class FakeTransport:
    def __init__(self, c):
        self.c = c
        self.loaded = {w.node: w.role == "edge" for w in c.workers}
        self.calls = []
        self.activation_gate = None
        self.request_gate = None
        self.fail_requests = False
        self.release_verified = True

    async def snapshot(self, worker):
        loaded = self.loaded[worker.node]
        return sample(worker, inference_ready=loaded, model_loaded=loaded,
                      node_state="ACTIVE" if loaded else "CACHED",
                      model_vram_mib=1000 if loaded else 0)

    async def lifecycle(self, worker, action):
        self.calls.append((action, worker.node))
        if action == "activate" and self.activation_gate:
            await self.activation_gate.wait()
        self.loaded[worker.node] = action == "activate" or not self.release_verified
        return {}

    async def generate(self, worker, request_id, on_token=None):
        self.calls.append(("generate", worker.node, request_id))
        if self.request_gate and not request_id.startswith("probe-"):
            await self.request_gate.wait()
        if self.fail_requests:
            raise TimeoutError("outcome_unknown")
        if on_token:
            on_token()
        return {"request_id": request_id, "node_id": worker.node,
                "model_digest": worker.model_digest, "response": "answer"}

    async def close(self):
        pass


async def make_controller(tmp_path):
    c = contract()
    transport = FakeTransport(c)
    controller = ModelOffloadExecutionController(c, OffloadJournal(tmp_path / "journal.db"), transport)
    controller.running = True
    controller.tasks = [asyncio.create_task(controller.consume(node)) for node in controller.workers]
    await refresh(controller)
    await controller.tick()
    return controller, transport


async def refresh(controller):
    for worker in controller.workers.values():
        controller.samples[worker.node] = await controller.transport.snapshot(worker)


async def trigger(controller):
    await refresh(controller)
    now = time.monotonic()
    controller.arrivals = deque([now] * 47)
    controller.high_since = now - 6
    controller.changed_at = now - 61
    await controller.tick()
    assert controller.state == "PREPARING"


async def finish_cycle(controller):
    await refresh(controller)
    controller.arrivals.clear()
    controller.low_since = time.monotonic() - 31
    controller.changed_at = time.monotonic() - 61
    await controller.tick()
    assert controller.state == "RETURNING"
    await controller.action
    assert controller.target == controller.edge and controller.state == "DRAINING"
    controller.last_remote = time.monotonic() - 31
    await refresh(controller)
    await controller.tick()
    assert controller.state == "RELEASING"
    await controller.action


def test_repeated_cycles_keep_edge_serving_during_prepare_and_release_only_models(tmp_path):
    async def run():
        controller, transport = await make_controller(tmp_path)
        try:
            for index in range(3):
                transport.activation_gate = asyncio.Event()
                await trigger(controller)
                await asyncio.sleep(0)
                result = await controller.submit(f"edge-{index}", controller.contract.prompt, 8)
                assert result["status"] == "ok" and result["node"] == controller.edge
                transport.activation_gate.set()
                await controller.action
                assert controller.state == "REMOTE"
                result = await controller.submit(f"server-{index}", controller.contract.prompt, 8)
                assert result["status"] == "ok" and result["node"] != controller.edge
                await finish_cycle(controller)
                assert controller.state == "LOCAL" and controller.cycles == index + 1
                assert controller.selected is None
            assert [call[0] for call in transport.calls].count("release") == 3
            assert all(call[1] != controller.edge for call in transport.calls if call[0] == "release")
        finally:
            await controller.stop()
    asyncio.run(run())


def test_duplicate_concurrent_request_runs_once_and_client_cancel_does_not_cancel_work(tmp_path):
    async def run():
        controller, transport = await make_controller(tmp_path)
        try:
            transport.request_gate = asyncio.Event()
            first = asyncio.create_task(controller.submit("same", controller.contract.prompt, 8))
            await asyncio.sleep(0)
            duplicate = asyncio.create_task(controller.submit("same", controller.contract.prompt, 8))
            await asyncio.sleep(0)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            transport.request_gate.set()
            assert (await duplicate)["status"] == "ok"
            assert (await controller.submit("same", controller.contract.prompt, 8))["status"] == "ok"
            assert sum(call[0] == "generate" for call in transport.calls) == 1
        finally:
            await controller.stop()
    asyncio.run(run())


def test_remote_unknown_is_not_replayed_and_unload_waits_for_drain(tmp_path):
    async def run():
        controller, transport = await make_controller(tmp_path)
        try:
            await trigger(controller)
            await controller.action
            node = controller.selected
            transport.request_gate = asyncio.Event()
            job = asyncio.create_task(controller.submit("uncertain", controller.contract.prompt, 8))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            controller.target = controller.edge
            controller.transition("DRAINING", "test_return")
            controller.last_remote = time.monotonic() - 31
            await controller.tick()
            assert controller.state == "DRAINING" and controller.inflight[node] == 1
            transport.fail_requests = True
            transport.request_gate.set()
            assert (await job)["status"] == "unknown"
            assert (await controller.submit("uncertain", controller.contract.prompt, 8))["status"] == "unknown"
            assert sum(len(call) == 3 and call[2] == "uncertain" for call in transport.calls) == 1
        finally:
            await controller.stop()
    asyncio.run(run())


def test_release_requires_actual_zero_vram_readback(tmp_path):
    async def run():
        controller, transport = await make_controller(tmp_path)
        try:
            await trigger(controller)
            await controller.action
            transport.release_verified = False
            await finish_cycle(controller)
            assert controller.state == "DRAINING" and controller.cycles == 0
            assert controller.selected is not None
        finally:
            await controller.stop()
    asyncio.run(run())


def test_restart_marks_uncertain_and_unsent_and_preserves_selected_server(tmp_path):
    c = contract()
    path = tmp_path / "journal.db"
    journal = OffloadJournal(path)
    journal.bind(c)
    with journal.db:
        journal.db.execute("INSERT INTO requests VALUES ('sent','fp',?,'dispatched',0,NULL)", (c.edge.node,))
        journal.db.execute("INSERT INTO requests VALUES ('waiting','fp',?,'queued',0,NULL)", (c.edge.node,))
    journal.event("PREPARING", "test", c.workers[1].node)
    with pytest.raises(ModelOffloadError, match="already_owns"):
        OffloadJournal(path)
    journal.close()
    journal = OffloadJournal(path)
    controller = ModelOffloadExecutionController(c, journal, FakeTransport(c))
    assert controller.selected == c.workers[1].node
    assert controller.state == "RECOVERING" and controller.target == c.edge.node
    assert journal.request("sent")["status"] == "unknown"
    assert journal.request("waiting")["status"] == "interrupted"
    journal.close()


def test_api_disabled_auth_and_qualified_request_contract(tmp_path):
    c = contract()
    controller = ModelOffloadExecutionController(c, OffloadJournal(tmp_path / "journal.db"), FakeTransport(c))
    app = FastAPI()
    app.include_router(create_model_offload_router(controller, "test-token"))
    try:
        with TestClient(app) as client:
            body = {"request_id": "test", "prompt": "unqualified prompt", "max_tokens": 8}
            assert client.post("/api/runtime-model-offloading/generate", json=body).status_code == 403
            response = client.post("/api/runtime-model-offloading/generate", json=body,
                                   headers={"X-Execution-Token": "test-token"})
            assert response.status_code == 422
            assert "outside_qualified_contract" in response.text
        app = FastAPI()
        app.include_router(create_model_offload_router(None, ""))
        with TestClient(app) as client:
            assert client.get("/api/runtime-model-offloading").json()["enabled"] is False
    finally:
        controller.journal.close()


@pytest.mark.parametrize("case", ["ok", "wrong_node", "missing_token", "stream_error"])
def test_actual_worker_ndjson_transport_contract(case):
    async def run():
        c = contract()
        worker = c.edge
        events = [{"type": "token", "text": "hello"}, {"type": "result", "request_id": "request",
                  "node_id": worker.node, "model_digest": worker.model_digest}]
        if case == "wrong_node":
            events[-1]["node_id"] = "substitute"
        elif case == "missing_token":
            events = events[1:]
        elif case == "stream_error":
            events[-1] = {"type": "error", "error": "failed"}
        transport = WorkerTransport(c)
        await transport.client.aclose()
        transport.client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="\n".join(json.dumps(e) for e in events))))
        try:
            if case == "ok":
                assert (await transport.generate(worker, "request"))["node_id"] == worker.node
            else:
                with pytest.raises(ModelOffloadError):
                    await transport.generate(worker, "request")
        finally:
            await transport.close()
    asyncio.run(run())


def test_activation_failure_and_return_load_rebound_keep_safe_route(tmp_path):
    async def run():
        controller, transport = await make_controller(tmp_path)
        try:
            transport.fail_requests = True
            await trigger(controller)
            await controller.action
            assert controller.target == controller.edge and controller.state == "DRAINING"
            transport.fail_requests = False
            controller.last_remote = time.monotonic() - 31
            await refresh(controller)
            await controller.tick()
            await controller.action
            assert controller.state == "LOCAL"
            await trigger(controller)
            await controller.action
            controller.transition("RETURNING", "test_low_dwell")
            await controller.return_to_edge()
            assert controller.state == "REMOTE" and controller.target != controller.edge
            assert controller.reason == "return_load_rebounded"
        finally:
            await controller.stop()
    asyncio.run(run())


def test_stale_server_falls_back_at_admission_without_waiting_for_monitor(tmp_path):
    async def run():
        controller, transport = await make_controller(tmp_path)
        try:
            await trigger(controller)
            await controller.action
            controller.samples[controller.selected] = {}
            result = await controller.submit("fallback", controller.contract.prompt, 8)
            assert result["node"] == controller.edge and result["status"] == "ok"
            assert controller.state == "DRAINING"
            assert not any(call[0] == "release" for call in transport.calls)
        finally:
            await controller.stop()
    asyncio.run(run())


@pytest.mark.parametrize("case", ["ok", "not_ready", "pressure", "wrong_image", "terminating", "wrong_node"])
def test_kubernetes_node_and_resident_runtime_gate(case):
    from types import SimpleNamespace as NS
    async def run():
        c = contract()
        worker = c.workers[1]
        conditions = [NS(type="Ready", status="False" if case == "not_ready" else "True")]
        conditions += [NS(type=key, status="True" if key == "MemoryPressure" and case == "pressure" else "False")
                       for key in ("MemoryPressure", "DiskPressure", "PIDPressure")]
        node = NS(status=NS(conditions=conditions), spec=NS(unschedulable=False))
        container = NS(name=worker.runtime_container, image="wrong" if case == "wrong_image" else worker.runtime_image)
        pod = NS(metadata=NS(deletion_timestamp="now" if case == "terminating" else None),
                 spec=NS(node_name="other" if case == "wrong_node" else worker.node, containers=[container]),
                 status=NS(container_statuses=[NS(name=container.name, ready=True, state=NS(running=NS()))]))
        kube = NS(enabled=True, v1=NS(read_node=lambda *a, **kw: node,
                                      list_namespaced_pod=lambda *a, **kw: NS(items=[pod])))
        transport = WorkerTransport(c, kube)
        try:
            assert await transport.placement_verified(worker) is (case == "ok")
        finally:
            await transport.close()
    asyncio.run(run())


def test_background_controller_rearms_without_restart(tmp_path):
    async def until(predicate):
        async with asyncio.timeout(4):
            while not predicate():
                await asyncio.sleep(.01)

    async def run():
        # Synthetic timings exercise the real polling/action loops, not SLOs.
        original = contract()
        workers = [original.edge.model_copy(update={"capacity_rps": 10, "service_ms": 200}),
                   original.workers[1].model_copy(update={"capacity_rps": 1000, "service_ms": 1, "activation_ms": 20})]
        c = original.model_copy(update={"workers": workers, "pressure_seconds": .05,
                                       "return_seconds": .05, "cooldown_seconds": .1,
                                       "idle_seconds": .05, "rate_window_seconds": .2})
        transport = FakeTransport(c)
        controller = ModelOffloadExecutionController(c, OffloadJournal(tmp_path / "continuous.db"), transport)
        await controller.start()
        try:
            await until(lambda: controller.state == "LOCAL" and controller.accepting)
            for cycle in range(2):
                for index in range(100):
                    await controller.submit(f"load-{cycle}-{index}", c.prompt, 8)
                    await asyncio.sleep(.002)
                await until(lambda: controller.state == "REMOTE")
                response = await controller.submit(f"remote-{cycle}", c.prompt, 8)
                assert response["node"] == c.workers[1].node
                await until(lambda: controller.cycles == cycle + 1 and controller.state == "LOCAL")
            assert len([row for row in controller.journal.events(100) if row["state"] == "PREPARING"]) == 2
        finally:
            await controller.stop()
    asyncio.run(run())
