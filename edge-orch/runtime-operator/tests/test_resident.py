import asyncio
import copy
import json

import httpx

from test_runtime import FakeKube, node, spec_data
from runtime_operator.contract import ServiceSpec
from runtime_operator.controller import Controller
from runtime_operator.journal import Journal
from runtime_operator.placement import candidates
from runtime_operator.resident import verify_binding, request_body, validate_result

DIGEST = "c" * 64


def setup():
    k = FakeKube()
    data = spec_data()
    data["port"] = 18110
    data["inference"] = {"modelDigest": DIGEST, "prompt": "qualified input", "maxTokens": 8}
    for index, v in enumerate(data["variants"]):
        v["maxInFlight"] = 1
        v["qualifiedRps"] = 4 + index * 2
        v["resident"] = {"protocol": "llama-worker-v1", "namespace": "runtime-existing",
            "service": v["name"], "selector": {"app": v["name"]}, "container": "runtime",
            "previousControllers": [{"namespace": "runtime-existing", "name": "old-controller"}]}
    k.resource["spec"] = data
    k.data["kubeServices"] = []
    k.data["deployments"] = [{"metadata": {"namespace": "runtime-existing", "name": "old-controller"},
        "spec": {"replicas": 0, "selector": {"matchLabels": {"app": "old-controller"}}}}]
    for n, v in zip(k.data["nodes"], data["variants"]):
        k.data["pods"].append({"metadata": {"namespace": "runtime-existing", "name": v["name"], "uid": v["name"] + "-uid",
             "labels": {"app": v["name"]}}, "spec": {"nodeName": n["metadata"]["name"],
             "containers": [{"name": "runtime", "image": v["image"], "resources": {"requests": {"cpu": "4", "memory": "4Gi"}}}]},
             "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}],
                        "containerStatuses": [{"name": "runtime", "ready": True}]}})
        k.data["kubeServices"].append({"metadata": {"namespace": "runtime-existing", "name": v["name"]},
             "spec": {"selector": {"app": v["name"]}, "ports": [{"port": 18110}]}})
    return k, ServiceSpec.model_validate(data)


def test_resident_uses_existing_reservation_and_actual_node():
    k, spec = setup()
    good, _ = candidates(spec, k.data["nodes"], k.data["pods"], [], snapshot=k.data)
    assert [(c.node, c.variant.name) for c in good] == [("field-any", "small"), ("datacenter-any", "large")]


def test_binding_requires_exclusive_handoff_and_exact_service_image():
    k, spec = setup()
    v = spec.variants[0]
    k.data["deployments"][0]["spec"]["replicas"] = 1
    assert verify_binding(v.resident, v.image, "field-any", k.data, 18110) == "previous_controller_not_stopped"
    k.data["deployments"][0]["spec"]["replicas"] = 0
    k.data["kubeServices"][0]["spec"]["selector"] = {"app": "something-else"}
    assert verify_binding(v.resident, v.image, "field-any", k.data, 18110) == "resident_service_identity_mismatch"
    k.data["kubeServices"][0]["spec"]["selector"] = {"app": "small"}
    assert verify_binding(v.resident, "wrong-image", "field-any", k.data, 18110) == "resident_image_or_pod_not_ready"


def test_resident_activation_routing_and_model_release_preserve_pods(tmp_path):
    async def run():
        k, spec = setup()
        journal = Journal(str(tmp_path / "resident.db"))
        now = [100.0]
        states = {"small": "CACHED", "large": "CACHED"}
        actions = []

        async def handler(request):
            variant = request.url.host.split(".")[0]
            n = "field-any" if variant == "small" else "datacenter-any"
            active = states[variant] == "ACTIVE"
            if request.url.path == "/health":
                return httpx.Response(200, json={"node_id": n, "model_digest": DIGEST, "node_state": states[variant],
                    "management_runtime_running": True, "model_cached": True, "model_loaded": active, "inference_ready": active})
            if request.url.path == "/metrics":
                return httpx.Response(200, json={"node_id": n, "max_concurrency": 1, "active_requests": 0,
                    "queue_length": 0, "model_vram_mib": 1000 if active else 0})
            actions.append((variant, request.url.path))
            states[variant] = json.loads(request.content)["target_state"]
            return httpx.Response(200, json={"node_state": states[variant]})

        c = Controller(k, journal, httpx.AsyncClient(transport=httpx.MockTransport(handler)), lambda: now[0])
        uid = k.resource["metadata"]["uid"]
        try:
            await c.tick()
            await asyncio.sleep(0)
            await c.tick()
            old = c.states[uid]["active"]["name"]
            now[0] += 120
            await c.tick()
            now[0] += 120
            await c.tick()
            assert c.states[uid]["reason"] == "healthy_current_placement"
            assert c.states[uid]["active"]["name"] == old
            c.inflight[old] = 1
            now[0] += 2
            await c.tick()
            now[0] += 2
            await c.tick()
            await asyncio.sleep(0)
            await c.tick()
            assert c.states[uid]["active"]["node"] == "datacenter-any"
            assert states["small"] == "ACTIVE"  # in-flight on source holds memory
            c.inflight[old] = 0
            await c.tick()
            await asyncio.sleep(0)
            await c.tick()
            assert states == {"small": "CACHED", "large": "ACTIVE"}
            assert not c.states[uid]["retiring"]
            observed = c.states[uid]["active"]["observation"]
            assert observed["health"]["nodeState"] == "ACTIVE"
            assert observed["health"]["modelVramMiB"] == 1000
            assert c.states[uid]["lastTransition"]["fromNode"] == "field-any"
            assert c.states[uid]["lastTransition"]["toNode"] == "datacenter-any"
            assert c.states[uid]["lastRelease"]["modelVramMiB"] == 0
            assert c.states[uid]["lastRelease"]["reservationRetained"] is True
            assert len(k.data["pods"]) == 2 and not k.actions
            assert ("small", "/deactivate") in actions
        finally:
            await c.transport.aclose()
            journal.close()
    asyncio.run(run())


def test_duplicate_resident_claims_fail_closed(tmp_path):
    async def run():
        k, _ = setup()
        other = copy.deepcopy(k.resource)
        other["metadata"].update(name="duplicate", uid="other-uid")
        k.data["services"].append(other)
        j = Journal(str(tmp_path / "claims.db"))
        c = Controller(k, j)
        try:
            await c.tick()
            assert all(s["phase"] == "Blocked" for s in c.states.values())
            assert not c.lifecycle_tasks
        finally:
            await c.transport.aclose()
            j.close()
    asyncio.run(run())


def test_qualified_input_and_result_identity():
    import pytest
    _, spec = setup()
    with pytest.raises(ValueError):
        request_body(spec.model_dump(), {"prompt": "other", "max_tokens": 128}, "id")
    target = {"node": "field-any", "spec": spec.model_dump()}
    with pytest.raises(ValueError):
        validate_result(target, "id", {"request_id": "id", "node_id": "wrong", "response": "text", "model_digest": DIGEST, "eval_count": 8})


def test_resident_must_actually_hold_declared_accelerator_reservation():
    k, spec = setup()
    data = spec.model_dump()
    data['variants'][0]['requests']['nvidia.com/gpu'] = '1'
    data['variants'][0]['limits']['nvidia.com/gpu'] = '1'
    spec = ServiceSpec.model_validate(data)
    good, rejected = candidates(spec, k.data['nodes'], k.data['pods'], [], snapshot=k.data)
    assert 'resident_reservation_below_contract' in next(r for r in rejected if r['node']=='field-any' and r['variant']=='small')['reasons']
    k.data['pods'][0]['spec']['containers'][0]['resources']['requests']['nvidia.com/gpu'] = '1'
    good, _ = candidates(spec, k.data['nodes'], k.data['pods'], [], snapshot=k.data)
    assert any(c.node=='field-any' for c in good)
