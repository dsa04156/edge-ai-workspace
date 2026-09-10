import asyncio
import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from runtime_operator.api import create_app
from runtime_operator.contract import ServiceSpec
from runtime_operator.controller import Controller
from runtime_operator.journal import Journal
from runtime_operator.kube import FINALIZER
from runtime_operator.placement import candidates, pod_requests


def spec_data():
    return {"ioContract": "example.echo.v1", "timeoutSeconds": 3, "variants": [
        {"name": "small", "image": "example/worker@sha256:" + "a" * 64, "architecture": "arm64",
         "backend": "cpu", "requests": {"cpu": "100m", "memory": "64Mi"},
         "limits": {"cpu": "1", "memory": "128Mi"}, "maxInFlight": 1, "qualification": "synthetic-small"},
        {"name": "large", "image": "example/worker@sha256:" + "b" * 64, "architecture": "amd64",
         "backend": "cpu", "requests": {"cpu": "100m", "memory": "64Mi"},
         "limits": {"cpu": "1", "memory": "128Mi"}, "maxInFlight": 4, "qualification": "synthetic-large"}],
        "policy": {"pressureSeconds": 1, "returnSeconds": 2, "cooldownSeconds": 1, "prepareTimeoutSeconds": 5}}


def node(name="field-any", arch="arm64", role="edge"):
    return {"metadata": {"name": name, "labels": {"kubernetes.io/arch": arch, "kubernetes.io/os": "linux",
             "platform.jinuk.io/role": role}}, "spec": {}, "status": {"allocatable": {
             "cpu": "4", "memory": "4Gi", "pods": "100"}, "conditions": [
             {"type": k, "status": "True" if k == "Ready" else "False"}
             for k in ("Ready", "MemoryPressure", "DiskPressure", "PIDPressure")]}}


def resource():
    return {"apiVersion": "platform.jinuk.io/v1alpha1", "kind": "RuntimeService", "metadata": {
        "uid": "12345678-abcd-1234-abcd-123456789abc", "name": "unrelated-service-name", "generation": 1,
        "resourceVersion": "1", "finalizers": [FINALIZER]}, "spec": spec_data()}


class FakeKube:
    namespace = "platform-runtime"

    def __init__(self):
        self.resource = resource()
        self.data = {"services": [self.resource], "nodes": [node(), node("datacenter-any", "amd64", "server")],
                     "pods": [], "deployments": [], "runtimeClasses": []}
        self.actions = []
        self.fail_scale = False

    def snapshot(self):
        return copy.deepcopy(self.data)

    def ensure(self, resource, spec, candidate, name):
        self.actions.append(("ensure", name))
        if any(d["metadata"]["name"] == name for d in self.data["deployments"]):
            return
        uid = resource["metadata"]["uid"]
        self.data["deployments"].append({"metadata": {"name": name, "ownerReferences": [
            {"kind": "RuntimeService", "uid": uid, "controller": True}]}, "spec": {"replicas": 1}})
        self.data["pods"].append({"metadata": {"namespace": self.namespace, "labels": {
            "platform.jinuk.io/revision": name, "platform.jinuk.io/service-uid": uid}},
            "spec": {"nodeName": candidate.node, "containers": [{"image": candidate.variant.image,
                       "resources": {"requests": candidate.variant.requests}}]},
            "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "False"}]}})

    def ready(self, name):
        for p in self.data["pods"]:
            if p["metadata"]["labels"]["platform.jinuk.io/revision"] == name:
                p["status"]["conditions"][0]["status"] = "True"

    def scale(self, name, uid, replicas):
        self.actions.append(("scale", name, replicas))
        if self.fail_scale:
            raise RuntimeError("API temporarily down")
        for d in self.data["deployments"]:
            if d["metadata"]["name"] == name:
                d["spec"]["replicas"] = replicas
        if replicas == 0:
            self.data["pods"] = [p for p in self.data["pods"] if p["metadata"]["labels"]["platform.jinuk.io/revision"] != name]

    def status(self, *_):
        pass

    def finalizer(self, resource, add=True):
        self.actions.append(("finalizer", add))

    def remove(self, name, uid):
        self.actions.append(("remove", name))


@pytest.fixture
def rig(tmp_path):
    now = [100.0]
    kube = FakeKube()
    remote = {"ready": True, "ioContract": "example.echo.v1", "inFlight": 0}
    calls = []

    async def handle(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=remote)
        return httpx.Response(200, json={"answer": json.loads(request.content)})

    j = Journal(str(tmp_path / "state.db"))
    c = Controller(kube, j, httpx.AsyncClient(transport=httpx.MockTransport(handle)), lambda: now[0])
    yield c, kube, now, remote, calls
    j.close()


async def activate(c, kube):
    await c.tick()
    target = c.states[kube.resource["metadata"]["uid"]]["target"]
    kube.ready(target["name"])
    await c.tick()
    return target["name"]


def test_arbitrary_names_and_architecture():
    good, rejected = candidates(ServiceSpec.model_validate(spec_data()), [node("orchard"), node("moon", "amd64", "server")], [], [])
    assert [(c.node, c.variant.name) for c in good] == [("orchard", "small"), ("moon", "large")]
    assert len(rejected) == 2


@pytest.mark.parametrize("change,reason", [
    (lambda n: n["status"]["conditions"][0].update(status="False"), "node_not_ready"),
    (lambda n: n["status"]["conditions"][1].update(status="True"), "node_pressure_or_unknown"),
    (lambda n: n["spec"].update(unschedulable=True), "node_cordoned"),
    (lambda n: n["spec"].update(taints=[{"key": "dedicated", "effect": "NoSchedule"}]), "untolerated_taint"),
    (lambda n: n["status"]["allocatable"].update(cpu="0"), "insufficient:cpu"),
    (lambda n: n["status"]["allocatable"].update(memory="32Mi"), "insufficient:memory"),
])
def test_exclusion_reasons(change, reason):
    n = node()
    change(n)
    good, bad = candidates(ServiceSpec.model_validate(spec_data()), [n], [], [])
    assert not good and reason in bad[0]["reasons"]


def test_gpu_is_not_npu_and_runtime_class_required():
    data = spec_data()
    v = data["variants"][0]
    v.update(backend="aries", runtimeClassName="aries")
    v["requests"]["mobilint.com/npu"] = v["limits"]["mobilint.com/npu"] = "1"
    n = node()
    n["status"]["allocatable"]["nvidia.com/gpu"] = "1"
    good, bad = candidates(ServiceSpec.model_validate(data), [n], [], [])
    assert not good and "insufficient:mobilint.com/npu" in bad[0]["reasons"]
    assert "runtime_class_missing" in bad[0]["reasons"]
    n["status"]["allocatable"]["mobilint.com/npu"] = "1"
    good, _ = candidates(ServiceSpec.model_validate(data), [n], [], [{"metadata": {"name": "aries"}}])
    assert len(good) == 1


def test_init_sidecars_and_overhead_count():
    p = {"spec": {"containers": [{"resources": {"requests": {"cpu": "1"}}}], "initContainers": [
        {"restartPolicy": "Always", "resources": {"requests": {"cpu": "500m"}}},
        {"resources": {"requests": {"cpu": "2"}}}], "overhead": {"cpu": "100m"}}}
    assert str(pod_requests(p)["cpu"]) == "2.600"


@pytest.mark.parametrize("change", [
    lambda d: d.update(execution="stateful"),
    lambda d: d.update(command=["sh", "-c", "anything"]),
    lambda d: d.update(requestPath="http://outside/"),
    lambda d: d["variants"][0].update(image="worker:latest"),
    lambda d: d["policy"].update(lowWatermark=0.9),
    lambda d: d["variants"][0]["requests"].update(cpu="9"),
])
def test_unsupported_or_unsafe_contract_rejected(change):
    data = spec_data()
    change(data)
    with pytest.raises((ValidationError, ValueError)):
        ServiceSpec.model_validate(data)


def test_never_switch_until_pod_and_application_ready(rig):
    async def run():
        c, k, _, remote, _ = rig
        await c.tick()
        state = next(iter(c.states.values()))
        assert state["active"] is None
        k.ready(state["target"]["name"])
        remote["ready"] = False
        await c.tick()
        assert not next(iter(c.states.values()))["serving"]
        remote["ready"] = True
        await c.tick()
        assert next(iter(c.states.values()))["active"]["node"] == "field-any"
    asyncio.run(run())


def test_pressure_switch_drain_return_and_scale_retry(rig):
    async def run():
        c, k, now, remote, _ = rig
        uid = k.resource["metadata"]["uid"]
        old = await activate(c, k)
        now[0] += 2
        c.inflight[old] = 1
        await c.tick()
        now[0] += 2
        await c.tick()
        new = c.states[uid]["target"]["name"]
        assert c.states[uid]["active"]["name"] == old
        k.ready(new)
        await c.tick()
        assert c.states[uid]["active"]["name"] == new
        assert ("scale", old, 0) not in k.actions
        c.inflight[old] = 0
        remote["inFlight"] = 1
        await c.tick()
        assert ("scale", old, 0) not in k.actions
        remote["inFlight"] = 0
        k.fail_scale = True
        await c.tick()
        assert c.states[uid]["phase"] == "Blocked"
        k.fail_scale = False
        await c.tick()
        assert k.actions.count(("scale", old, 0)) == 2
        await c.tick()
        now[0] += 3
        await c.tick()
        assert c.states[uid]["target"]["node"] == "field-any"
    asyncio.run(run())


def test_failed_prepare_preserves_active_and_releases_unrouted_pod(rig):
    async def run():
        c, k, now, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        old = await activate(c, k)
        k.resource["spec"]["policy"]["allowedRoles"] = ["server"]
        k.resource["spec"]["policy"]["preferredRole"] = "server"
        await c.tick()
        target = c.states[uid]["target"]["name"]
        now[0] += 6
        await c.tick()
        assert c.states[uid]["active"]["name"] == old and c.states[uid]["serving"]
        assert ("scale", target, 0) in k.actions
        assert ("scale", old, 0) not in k.actions
    asyncio.run(run())


def test_gateway_deduplicates_and_rejects_payload_conflict(rig):
    async def run():
        c, k, _, _, calls = rig
        await activate(c, k)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url="http://gateway") as api:
            path = "/services/unrelated-service-name/invoke"
            a = await api.post(path, json={"input": 1}, headers={"X-Request-ID": "r1"})
            b = await api.post(path, json={"input": 1}, headers={"X-Request-ID": "r1"})
            d = await api.post(path, json={"input": 2}, headers={"X-Request-ID": "r1"})
            assert a.status_code == b.status_code == 200 and a.json() == b.json()
            assert d.status_code == 409
            assert sum(r.method == "POST" for r in calls) == 1
    asyncio.run(run())


def test_gateway_stale_snapshot_refuses_new_dispatch(rig):
    async def run():
        c, k, now, _, calls = rig
        await activate(c, k)
        now[0] += 16
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url="http://gateway") as api:
            r = await api.post("/services/unrelated-service-name/invoke", json={}, headers={"X-Request-ID": "r1"})
            assert r.status_code == 503 and r.json()["accepted"] is False
            assert not any(r.method == "POST" for r in calls)
    asyncio.run(run())


def test_restart_never_replays_dispatched_request(tmp_path):
    path = str(tmp_path / "journal.db")
    j = Journal(path)
    j.dispatch("service", "r1", "fingerprint", "worker")
    with pytest.raises(RuntimeError, match="another controller"):
        Journal(path)
    j.close()
    reopened = Journal(path)
    assert reopened.request("service", "r1")["state"] == "unknown"
    reopened.close()


def test_suspension_stops_admission_then_drains(rig):
    async def run():
        c, k, _, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        old = await activate(c, k)
        c.inflight[old] = 1
        k.resource["spec"]["suspended"] = True
        await c.tick()
        assert not c.states[uid]["serving"] and c.states[uid]["phase"] == "Draining"
        assert ("scale", old, 0) not in k.actions
        c.inflight[old] = 0
        await c.tick()
        await c.tick()
        assert c.states[uid]["phase"] == "Suspended"
    asyncio.run(run())


def test_worker_timeout_is_unknown_and_never_retried(rig):
    async def run():
        c, k, _, _, _ = rig
        await activate(c, k)
        attempts = []

        async def fail(request):
            attempts.append(request)
            raise httpx.ReadTimeout("lost response")

        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url="http://gateway") as api:
            path = "/services/unrelated-service-name/invoke"
            for _ in range(2):
                r = await api.post(path, json={}, headers={"X-Request-ID": "lost"})
                assert r.status_code == 503 and r.headers["X-Request-State"] == "unknown"
            assert len(attempts) == 1
            outcome = await api.get("/services/unrelated-service-name/requests/lost")
            assert outcome.json()["state"] == "unknown"
    asyncio.run(run())


def test_failed_initial_candidate_backoff_allows_another_node(rig):
    async def run():
        c, k, now, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        await c.tick()
        first = c.states[uid]["target"]["name"]
        now[0] += 6
        await c.tick()
        await c.tick()
        now[0] += 2
        await c.tick()
        assert c.states[uid]["target"]["name"] != first
        assert c.states[uid]["target"]["node"] == "datacenter-any"
    asyncio.run(run())


def test_reservations_from_other_namespaces_are_not_credited():
    spec = ServiceSpec.model_validate(spec_data())
    n = node()
    n["status"]["allocatable"]["cpu"] = "100m"
    p = {"metadata": {"namespace": "someone-else", "labels": {"platform.jinuk.io/revision": "revision",
         "platform.jinuk.io/service-uid": "uid"}}, "spec": {"nodeName": n["metadata"]["name"],
         "containers": [{"resources": {"requests": {"cpu": "100m"}}}]}, "status": {"phase": "Running"}}
    good, bad = candidates(spec, [n], [p], [], {(n["metadata"]["name"], "small"):
        {"name": "revision", "uid": "uid", "namespace": "platform-runtime"}})
    assert not good and "insufficient:cpu" in bad[0]["reasons"]


def test_terminating_candidate_does_not_block_other_nodes(rig):
    async def run():
        c, k, now, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        await c.tick()
        target = c.states[uid]["target"]
        target["scaledDown"] = True
        state = c.states[uid]
        state.update(target=None, retiring=[target])
        c.save(uid, state)
        k.scale = lambda *args: None  # a disconnected node has not removed its Pod yet
        now[0] += 3
        await c.tick()
        assert c.states[uid]["target"]["node"] == "datacenter-any"
        assert c.states[uid]["retiring"]
    asyncio.run(run())


def test_low_load_does_not_hop_between_servers_while_edge_drains(rig):
    async def run():
        c, k, now, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        k.resource["spec"]["policy"]["preferredRole"] = "server"
        await activate(c, k)
        active = c.states[uid]["active"]["name"]
        k.resource["spec"]["policy"]["preferredRole"] = "edge"
        k.data["nodes"] = [n for n in k.data["nodes"] if n["metadata"]["name"] != "field-any"]
        k.data["nodes"].append(node("another-server", "arm64", "server"))
        now[0] += 10
        await c.tick()
        assert c.states[uid]["target"] is None and c.states[uid]["active"]["name"] == active
    asyncio.run(run())


def test_restart_waits_for_previous_process_inflight_before_admitting(rig):
    async def run():
        c, k, _, remote, _ = rig
        uid = k.resource["metadata"]["uid"]
        await activate(c, k)
        recovered = Controller(k, c.journal, c.transport, c.clock)
        remote["inFlight"] = 1
        await recovered.tick()
        assert recovered.states[uid]["phase"] == "Recovering"
        assert not recovered.states[uid]["serving"]
        remote["inFlight"] = 0
        await recovered.tick()
        assert recovered.states[uid]["serving"]
    asyncio.run(run())


def test_corrected_invalid_contract_recovers_without_new_uid(rig):
    async def run():
        c, k, _, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        k.resource["spec"]["variants"][0]["requests"]["cpu"] = "9"
        await c.tick()
        assert c.states[uid]["phase"] == "Blocked"
        k.resource["spec"] = spec_data()
        await activate(c, k)
        assert c.states[uid]["serving"]
    asyncio.run(run())


def test_removed_nonserving_uid_does_not_hide_recreated_service(rig):
    async def run():
        c, k, _, _, _ = rig
        uid = k.resource["metadata"]["uid"]
        k.resource["spec"]["suspended"] = True
        await c.tick()
        assert c.states[uid]["phase"] == "Suspended"
        k.data["services"] = []
        await c.tick()
        assert c.states[uid]["phase"] == "Missing"
    asyncio.run(run())
