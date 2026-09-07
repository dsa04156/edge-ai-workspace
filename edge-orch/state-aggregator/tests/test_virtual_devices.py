import asyncio
import copy
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kubernetes import client
from kubernetes.client.exceptions import ApiException
import pytest

from app.virtual_resource_registry import ID_LABEL, VirtualDeviceRegistry
from app.virtual_resources import (
    KubernetesVirtualDeviceReader, RuntimeStatusProbe, VirtualDeviceObserver,
    create_virtual_device_router, fresh, validate_status,
)


def run(coroutine):
    return asyncio.run(coroutine)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def owner(kind, uid):
    return client.V1OwnerReference(api_version="apps/v1", kind=kind, name=uid, uid=uid, controller=True)


def pod(uid="pod-1", label="vd-demo-001", owner_uid="rs-1", phase="Running", node="server-test"):
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name=uid, namespace="virtual-device-test", uid=uid,
                                   labels={ID_LABEL:label}, owner_references=[owner("ReplicaSet", owner_uid)]),
        spec=client.V1PodSpec(node_name=node, containers=[client.V1Container(name="inference",
            resources=client.V1ResourceRequirements(requests={"cpu":"100m","memory":"64Mi"}, limits={"cpu":"1","memory":"256Mi"}))]),
        status=client.V1PodStatus(phase=phase, pod_ip="127.0.0.1",
                                 conditions=[client.V1PodCondition(type="Ready", status="True")]))


def kube_fixture():
    kube = NS(enabled=True, apps=Mock(), v1=Mock())
    kube.apps.read_namespaced_deployment.return_value = NS(
        metadata=client.V1ObjectMeta(uid="deployment-1", labels={ID_LABEL:"vd-demo-001"}),
        spec=NS(replicas=0, template=NS(spec=NS(node_selector={"kubernetes.io/hostname":"server-test"}))))
    kube.apps.list_namespaced_replica_set.return_value = NS(items=[NS(
        metadata=client.V1ObjectMeta(uid="rs-1", labels={ID_LABEL:"vd-demo-001"},
                                   owner_references=[owner("Deployment", "deployment-1")]))])
    kube.v1.list_namespaced_pod.return_value = NS(items=[])
    kube.v1.list_node.return_value = NS(items=[NS(metadata=NS(name="server-test"), status=NS(conditions=[
        NS(type="Ready",status="True")]))])
    return kube


def status(p, ready=True):
    model = {"id":"iris-centroid", "version":"1.0.0", "sha256":"model-sha"}
    return {"virtualDeviceId":"vd-demo-001", "podUid":p["podUid"], "bootId":"boot-1",
            "observedAt":timestamp(), "model":model, "modelReady":ready, "draining":False,
            "inFlight":0, "succeeded":0, "failed":0, "lastSuccess":None,
            "usage":{"scope":"main_process", "cpuCores":None, "memoryBytes":None}}


def test_seven_lifecycle_scenarios():
    kube = kube_fixture()
    registry = VirtualDeviceRegistry.load()
    async def probe(p, definition):
        return status(p)
    observer = VirtualDeviceObserver(KubernetesVirtualDeviceReader(kube), probe)
    def read():
        observer.cached = None
        return run(observer.snapshot(registry))
    first = read()
    assert first["summary"] == {"physicalNodes":1, "definitions":1, "observedInstances":0}
    assert first["resources"][0]["executionState"] == "no_instance"
    assert first["resources"][0]["connectionState"] == "configured_unverified"
    kube.apps.read_namespaced_deployment.return_value.spec.replicas = 1
    kube.v1.list_namespaced_pod.return_value.items = [pod()]
    started = read()["resources"][0]
    assert started["id"] == "vd-demo-001"
    assert started["instances"][0]["node"] == "server-test"
    assert started["instances"][0]["modelReady"] is True
    assert started["executionState"] == "ready"
    assert started["instances"][0]["usage"]["cpuCores"] is None
    # Runtime counts alone don't claim request delivery to the configured target.
    async def delivered(p, definition):
        state = status(p)
        state["succeeded"] = 1
        state["lastSuccess"] = {"virtualDeviceId":"vd-demo-001","podUid":p["podUid"],"bootId":"boot-1",
            "requestId":"jetson-42","clientId":"etri-dev0001-jetorn","result":{"label":"setosa"},
            "completedAt":timestamp(), "model":state["model"]}
        return state
    observer.probe = delivered
    delivered_row = read()["resources"][0]
    assert delivered_row["connectionState"] == "request_observed"
    evidence = delivered_row["instances"][0]["runtime"]
    assert evidence["succeeded"] == 1 and evidence["lastSuccess"]["requestId"] == "jetson-42"
    kube.v1.list_namespaced_pod.return_value.items = [pod("pod-2")]
    replaced = read()["resources"][0]
    assert replaced["id"] == started["id"] and replaced["instances"][0]["podUid"] != started["instances"][0]["podUid"]
    assert replaced["instances"][0]["podUid"] == "pod-2"
    async def broken_model(p, definition):
        return status(p, False)
    observer.probe = broken_model
    assert read()["resources"][0]["executionState"] == "not_ready"
    async def disconnected(p, definition):
        raise httpx.ConnectError("offline")
    observer.probe = disconnected
    broken = read()["resources"][0]
    assert broken["executionState"] == broken["connectionState"] == "unknown"
    assert broken["instances"][0]["modelReady"] is None
    kube.v1.list_namespaced_pod.side_effect = ApiException(status=403, reason="Forbidden")
    unknown = read()
    assert unknown["summary"]["observedInstances"] is None
    assert unknown["resources"][0]["executionState"] == "unknown"
    kube.v1.list_namespaced_pod.side_effect = None
    kube.apps.read_namespaced_deployment.return_value.spec.replicas = 0
    # unrelated Pod on the SAME node is never counted
    kube.v1.list_namespaced_pod.return_value.items = [pod("sensor-pod", label="sensor")]
    stopped = read()
    assert stopped["summary"]["observedInstances"] == 0 and stopped["summary"]["definitions"] == 1
    assert stopped["resources"][0]["id"] == "vd-demo-001"
    assert stopped["resources"][0]["executionState"] == "no_instance"
    assert registry.connections[0].spec.targetDevice.name == "etri-dev0001-jetorn"


@pytest.mark.parametrize("case", ["wrong_owner", "stale_api", "wrong_runtime_id", "wrong_model", "workload_label", "disabled"])
def test_fail_closed_identity_and_freshness(case):
    kube = kube_fixture()
    kube.v1.list_namespaced_pod.return_value.items = [pod(owner_uid="other" if case == "wrong_owner" else "rs-1")]
    if case == "workload_label":
        kube.apps.read_namespaced_deployment.return_value.metadata.labels = {}
    if case == "disabled":
        kube.enabled = False
    async def probe(p, definition):
        result = status(p)
        if case == "stale_api": result["observedAt"] = "2000-01-01T00:00:00+00:00"
        if case == "wrong_runtime_id": result["podUid"] = "old-pod"
        if case == "wrong_model": result["model"]["version"] = "wrong"
        return result
    result = run(VirtualDeviceObserver(KubernetesVirtualDeviceReader(kube), probe).snapshot(VirtualDeviceRegistry.load()))
    assert result["resources"][0]["executionState"] == "unknown"


def test_terminating_terminal_and_not_yet_created():
    kube = kube_fixture()
    reader = KubernetesVirtualDeviceReader(kube)
    definition = VirtualDeviceRegistry.load().resources[0]
    p = pod()
    p.metadata.deletion_timestamp = datetime.now(timezone.utc)
    kube.v1.list_namespaced_pod.return_value.items = [p, pod("old-failed", phase="Failed")]
    observed = run(reader.workload(definition))
    assert len(observed["instances"]) == 1 and observed["instances"][0]["terminating"]
    assert len(observed["terminalPods"]) == 1
    kube.apps.read_namespaced_deployment.side_effect = ApiException(status=404)
    kube.v1.list_namespaced_pod.return_value.items = []
    assert run(reader.workload(definition))["instances"] == []
    kube.v1.list_namespaced_pod.side_effect = ApiException(status=404)
    with pytest.raises(ApiException):
        run(reader.workload(definition))


def test_old_cr_fields_preserved_but_insufficient_identity_is_unknown():
    registry = VirtualDeviceRegistry.load()
    resource = registry.resources[0]
    resource.spec.runtimeRef.workloadRef = None
    with pytest.raises(ValueError, match="explicit_identity"):
        run(KubernetesVirtualDeviceReader(kube_fixture()).workload(resource))
    assert resource.spec.resourceType == "cpu"


def test_api_is_get_only_and_preserves_registered_definition(monkeypatch, tmp_path):
    kube = kube_fixture()
    app = FastAPI()
    app.include_router(create_virtual_device_router(kube))
    with TestClient(app) as client_:
        assert client_.post("/api/virtual-devices", json={}).status_code == 405
        result = client_.get("/api/virtual-devices")
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["resources"][0]["id"] == "vd-demo-001"
        monkeypatch.setenv("VIRTUAL_DEVICE_REGISTRY_PATH", str(tmp_path / "missing"))
        assert client_.get("/api/virtual-devices").status_code == 503
    assert not kube.apps.patch_namespaced_deployment.called
    assert not kube.apps.create_namespaced_deployment.called
    assert not kube.apps.delete_namespaced_deployment.called


def test_freshness_rejects_future_missing_and_old():
    assert fresh(timestamp())
    assert not fresh(None)
    assert not fresh((datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat())
    assert not fresh((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())


def test_real_runtime_to_aggregator_http_evidence(monkeypatch, tmp_path):
    runtime_root = Path(__file__).resolve().parents[2] / "virtual-device-runtime"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    registry = VirtualDeviceRegistry.load()
    registry.resources[0].spec.runtimeRef.port = port
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(registry.model_dump_json())
    monkeypatch.setenv("VIRTUAL_DEVICE_REGISTRY_PATH", str(registry_path))
    kube = kube_fixture()
    kube.v1.list_namespaced_pod.return_value.items = [pod()]
    kube.apps.read_namespaced_deployment.return_value.spec.replicas = 1
    app = FastAPI()
    app.include_router(create_virtual_device_router(kube))
    env = {**os.environ, "PYTHONPATH":str(runtime_root), "PORT":str(port), "POD_UID":"pod-1"}
    with (tmp_path / "runtime.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "vd_runtime"], cwd=runtime_root,
                                   env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(timeout=3, trust_env=False) as http:
                url = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 10
                while True:
                    try:
                        if http.get(url + "/readyz").status_code == 200: break
                    except httpx.HTTPError:
                        pass
                    assert time.monotonic() < deadline
                    time.sleep(.03)
                result = http.post(url + "/infer", json={"requestId":"cross-stack-1",
                    "clientId":"etri-dev0001-jetorn","features":[5.1,3.5,1.4,.2]}).json()
                assert result["result"]["label"] == "setosa"
                with TestClient(app) as dashboard:
                    payload = dashboard.get("/api/virtual-devices").json()
                row = payload["resources"][0]
                assert row["executionState"] == "ready"
                assert row["connectionState"] == "request_observed"
                observed = row["instances"][0]["runtime"]
                assert observed["lastSuccess"] == result
                assert observed["succeeded"] == 1 and observed["podUid"] == "pod-1"
                assert row["instances"][0]["usage"]["memoryBytes"] > 0
                process.terminate()
                process.wait(timeout=5)
                # A still-listed Pod plus unreachable runtime never means Ready.
                failed = run(VirtualDeviceObserver(KubernetesVirtualDeviceReader(kube)).snapshot(registry))
                assert failed["resources"][0]["executionState"] == "unknown"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
