import asyncio
from collections import deque
import json
from pathlib import Path
import time

import pytest

from app.model_offload_contract import ModelOffloadContract, recommend_model_offload
from app.model_offload_controller import OffloadJournal
from app.model_offload_ordered import OrderedModelOffloadExecutionController
from test_model_offload import FakeTransport, refresh, sample


def ordered_contract(qualified=True):
    data = json.loads((Path(__file__).parents[1] / "app/config/model_offload_llama.json").read_text())
    # Explicit synthetic profile, never written to the actual Spark catalog.
    data["workers"][-1].update(qualified=qualified, capacity_rps=8 if qualified else None,
                               service_ms=40 if qualified else None, low_ttft_ms=60 if qualified else None,
                               activation_ms=500 if qualified else None, evidence="synthetic-test-only")
    return ModelOffloadContract.model_validate(data)


async def controller_at_start(tmp_path, qualified=True):
    c = ordered_contract(qualified)
    transport = FakeTransport(c)
    controller = OrderedModelOffloadExecutionController(c, OffloadJournal(tmp_path / "ordered.db"), transport)
    controller.running = True
    controller.tasks = [asyncio.create_task(controller.consume(node)) for node in controller.workers]
    await refresh(controller)
    await controller.tick()
    return controller, transport


def offered(controller, rate):
    controller.arrivals = deque([time.monotonic()] * round(rate * controller.contract.rate_window_seconds))


async def upward(controller, rate=4.7):
    await refresh(controller)
    offered(controller, rate)
    controller.high_since = time.monotonic() - 6
    controller.changed_at = time.monotonic() - 61
    await controller.tick()
    assert controller.state == "PREPARING", controller.snapshot()
    await controller.action
    assert controller.state == "REMOTE", controller.snapshot()


async def downward(controller, rate=2):
    await refresh(controller)
    offered(controller, rate)
    controller.low_since = time.monotonic() - 31
    controller.changed_at = time.monotonic() - 61
    await controller.tick()
    assert controller.state == "RETURNING", controller.snapshot()
    await controller.action


async def unload(controller, node):
    await refresh(controller)
    controller.last_finished[node] = time.monotonic() - 31
    await controller.tick()
    await controller.action
    assert node not in controller.touched


def test_roles_are_distinct_from_execution_order_and_missing_measurements_block():
    c = ordered_contract(False)
    assert [w.role for w in c.workers] == ["edge", "edge", "server"]
    assert c.edge == c.workers[0]
    snapshots = {w.node: sample(w) for w in c.workers}
    first = recommend_model_offload(c, snapshots, time.monotonic(), 4.7, 0, 0)
    assert first["selected_node"] == c.workers[1].node and first["tier"] == "edge"
    second = recommend_model_offload(c, snapshots, time.monotonic(), 4.7, 0, 0,
                                     current_node=c.workers[1].node)
    assert second["selected_node"] is None
    assert "candidate_performance_unqualified" in second["candidates"][0]["reason_codes"]


def test_order_never_skips_orin_when_spark_is_faster_or_orin_is_unavailable():
    c = ordered_contract()
    snapshots = {w.node: sample(w) for w in c.workers}
    decision = recommend_model_offload(c, snapshots, time.monotonic(), 4.7, 0, 0)
    assert [row["node"] for row in decision["candidates"]] == [c.workers[1].node]
    snapshots[c.workers[1].node] = {}
    decision = recommend_model_offload(c, snapshots, time.monotonic(), 4.7, 0, 0)
    assert decision["selected_node"] is None


def test_two_complete_three_hop_cycles_with_actual_request_identity(tmp_path):
    async def run():
        controller, transport = await controller_at_start(tmp_path)
        nano, orin, spark = controller.order
        try:
            for cycle in range(2):
                visited = [controller.target]
                for node in [orin, spark]:
                    await upward(controller)
                    assert controller.target == node
                    result = await controller.submit(f"{cycle}-{node}", controller.contract.prompt, 8)
                    assert result["node"] == node and result["status"] == "ok"
                    visited.append(controller.target)
                assert transport.loaded[orin] and transport.loaded[nano]
                await downward(controller)
                assert controller.target == orin and transport.loaded[spark]
                visited.append(controller.target)
                await unload(controller, spark)
                assert transport.loaded[orin] and not transport.loaded[spark]
                await downward(controller)
                assert controller.target == nano
                visited.append(controller.target)
                await unload(controller, orin)
                assert visited == [nano, orin, spark, orin, nano]
                assert controller.cycles == cycle + 1
                assert not controller.touched and transport.loaded[nano]
                assert controller.snapshot()["selected_server"] is None
        finally:
            await controller.stop()
    asyncio.run(run())


def test_return_threshold_uses_previous_hop_capacity(tmp_path):
    async def run():
        controller, _ = await controller_at_start(tmp_path)
        try:
            await upward(controller)
            await upward(controller)
            await downward(controller, rate=2.7)
            assert controller.target == controller.order[1]
            controller.low_since = time.monotonic() - 31
            controller.changed_at = time.monotonic() - 61
            await controller.tick()
            assert controller.target == controller.order[1] and controller.state == "REMOTE"
        finally:
            await controller.stop()
    asyncio.run(run())


def test_preparation_keeps_current_hop_serving_and_draining_guards_spark(tmp_path):
    async def run():
        controller, transport = await controller_at_start(tmp_path)
        try:
            await upward(controller)
            transport.activation_gate = asyncio.Event()
            up = asyncio.create_task(upward(controller))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            result = await controller.submit("during-spark-prepare", controller.contract.prompt, 8)
            assert result["node"] == controller.order[1]
            transport.activation_gate.set()
            await up
            transport.request_gate = asyncio.Event()
            request = asyncio.create_task(controller.submit("spark-inflight", controller.contract.prompt, 8))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            await downward(controller)
            spark = controller.order[-1]
            controller.last_finished[spark] = time.monotonic() - 31
            await controller.tick()
            assert spark in controller.touched and transport.loaded[spark]
            transport.request_gate.set()
            assert (await request)["status"] == "ok"
            await unload(controller, spark)
        finally:
            await controller.stop()
    asyncio.run(run())


def test_restart_tracks_both_loaded_hops_and_does_not_count_interrupted_cycle(tmp_path):
    async def run():
        controller, transport = await controller_at_start(tmp_path)
        await upward(controller)
        await upward(controller)
        await controller.stop()
        restarted = OrderedModelOffloadExecutionController(
            controller.contract, OffloadJournal(tmp_path / "ordered.db"), transport)
        restarted.running = True
        try:
            await refresh(restarted)
            await restarted.tick()
            assert restarted.target == restarted.edge and restarted.recovering
            assert restarted.touched == set(restarted.order[1:])
            await unload(restarted, restarted.order[-1])
            await unload(restarted, restarted.order[1])
            assert restarted.cycles == 0 and not restarted.recovering
        finally:
            await restarted.stop()
    asyncio.run(run())


def test_invalid_order_rejected():
    data = ordered_contract().model_dump()
    data["execution_order"][-1] = data["execution_order"][1]
    with pytest.raises(ValueError, match="every_worker_once"):
        ModelOffloadContract.model_validate(data)


def test_reviewed_spark_manifest_uses_real_gpu_runtime_and_controller_is_read_only():
    root = Path(__file__).resolve().parents[3] / "qualification/llama-offloading"
    worker = json.loads((root / "nano-orin-spark-k8s/resources.yaml").read_text())["items"]
    deployment = next(item for item in worker if item["kind"] == "Deployment")
    spec = deployment["spec"]["template"]["spec"]
    assert spec["runtimeClassName"] == "nvidia-spark"
    assert spec["nodeSelector"]["kubernetes.io/hostname"] == "etri-ser0003-cg0ms0"
    runtime = next(c for c in spec["containers"] if c["name"] == "inference-runtime")
    assert runtime["resources"]["limits"]["nvidia.com/gpu"] == 1
    assert all("hostPath" not in volume for volume in spec["volumes"])
    controller = json.loads((root / "nano-orin-spark-controller-k8s/resources.yaml").read_text())["items"]
    role = next(item for item in controller if item["kind"] == "ClusterRole")
    assert all(set(rule["verbs"]) <= {"get", "list"} for rule in role["rules"])
    deploy = next(item for item in controller if item["kind"] == "Deployment")
    assert deploy["spec"]["replicas"] == 1 and deploy["spec"]["strategy"]["type"] == "Recreate"
    assert deploy["spec"]["template"]["spec"]["containers"][0]["command"][:3] == ["python", "-m", "uvicorn"]


def test_admission_fallback_during_return_does_not_count_a_successful_cycle(tmp_path):
    async def run():
        controller, transport = await controller_at_start(tmp_path)
        try:
            await upward(controller)
            await upward(controller)
            nano, orin, spark = controller.order
            probe_started, probe_resume = asyncio.Event(), asyncio.Event()
            original_generate = transport.generate
            async def delayed_probe(worker, request_id, on_token=None):
                if worker.node == orin and request_id.startswith("probe-"):
                    probe_started.set()
                    await probe_resume.wait()
                return await original_generate(worker, request_id, on_token)
            transport.generate = delayed_probe
            returning = asyncio.create_task(downward(controller))
            await probe_started.wait()
            assert controller.state == "RETURNING"
            controller.samples[spark] = {}
            request = asyncio.create_task(controller.submit("fallback-during-return", controller.contract.prompt, 8))
            await asyncio.sleep(0)
            assert controller.state == "DRAINING" and controller.target == nano
            probe_resume.set()
            await returning
            assert (await request)["node"] == nano
            assert controller.recovering and not controller.reached_top
            await unload(controller, spark)
            await unload(controller, orin)
            assert controller.cycles == 0 and not controller.recovering
        finally:
            await controller.stop()
    asyncio.run(run())
