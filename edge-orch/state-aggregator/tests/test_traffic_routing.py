from __future__ import annotations

import asyncio
import inspect
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.traffic_routing import (
    MANAGED_BY,
    RoutingContractCatalog,
    RuntimeExecutionRouting,
    TrafficRoutingContract,
    TrafficRoutingEngine,
    TrafficRoutingError,
)
from app.kube import KubeClient


def _contract(*, compatibility="verified") -> TrafficRoutingContract:
    return TrafficRoutingContract.model_validate(
        {
            "serviceId": "sensor-anomaly-demo",
            "contractVersion": "test-v1",
            "mode": "runtime-endpointslice",
            "compatibilityStatus": compatibility,
            "compatibilityReasonCodes": ["routing_mode_unsupported"] if compatibility == "blocked" else [],
            "serviceName": "sensor-anomaly-demo",
            "namespace": "edgex-edge",
            "endpointSliceName": "sensor-anomaly-demo-runtime-routing",
            "portName": "http",
            "port": 8080,
            "protocol": "TCP",
            "source": {
                "workload": "sensor-anomaly-demo",
                "selector": {"app.kubernetes.io/name": "sensor-anomaly-demo"},
            },
            "switchPolicy": {
                "requireCandidateValidation": True,
                "postSwitchObservationSeconds": 30,
                "pollIntervalSeconds": 5,
                "timeoutSeconds": 120,
                "requiredConsecutiveSuccesses": 6,
            },
            "rollbackPolicy": {"enabled": True, "target": "source"},
        }
    )


def _pod(name, namespace, node, ip, labels):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, labels=labels),
        spec=SimpleNamespace(node_name=node),
        status=SimpleNamespace(
            pod_ip=ip,
            conditions=[SimpleNamespace(type="Ready", status="True")],
        ),
    )


def _slice(*, target="source", address="10.1.0.1", owner=False):
    return {
        "apiVersion": "discovery.k8s.io/v1",
        "kind": "EndpointSlice",
        "metadata": {
            "name": "sensor-anomaly-demo-runtime-routing",
            "namespace": "edgex-edge",
            "resourceVersion": "1",
            "labels": {
                "kubernetes.io/service-name": "sensor-anomaly-demo",
                "endpointslice.kubernetes.io/managed-by": MANAGED_BY,
                "edge-ai.io/managed-by": "runtime-execution-controller",
                "edge-ai.io/service-id": "sensor-anomaly-demo",
                "edge-ai.io/execution-plan-id": "bootstrap",
                "edge-ai.io/routing-role": "active",
                "edge-ai.io/active-target": target,
            },
            **({"ownerReferences": [{"kind": "Service", "name": "sensor-anomaly-demo"}]} if owner else {}),
        },
        "addressType": "IPv4",
        "ports": [{"name": "http", "protocol": "TCP", "port": 8080}],
        "endpoints": [{
            "addresses": [address],
            "conditions": {"ready": True, "serving": True, "terminating": False},
            "nodeName": "edge-a" if target == "source" else "server-b",
            "targetRef": {"kind": "Pod", "namespace": "edgex-edge", "name": "source-pod"},
        }],
    }


class FakeRoutingKube:
    def __init__(self, *, selectorless=True, endpoint_slice=None):
        self.service = {
            "spec": {
                "selector": None if selectorless else {"app.kubernetes.io/name": "sensor-anomaly-demo"},
                "ports": [{"name": "http", "port": 8080, "targetPort": "http"}],
            }
        }
        self.endpoint_slice = deepcopy(endpoint_slice or _slice())
        self.replace_calls = 0
        self.source = _pod(
            "source-pod", "edgex-edge", "edge-a", "10.1.0.1",
            {"app.kubernetes.io/name": "sensor-anomaly-demo"},
        )
        self.candidate = _pod(
            "candidate-pod", "edge-ai-workloads", "server-b", "10.2.0.2",
            {"edge-ai.io/deployment": "candidate", "edge-ai.io/execution-plan-id": "runtime-plan-1234567890abcdef"},
        )

    async def read_service(self, namespace, name):
        return deepcopy(self.service)

    async def list_endpoint_slices(self, namespace, service_name):
        return [deepcopy(self.endpoint_slice)]

    async def read_endpoint_slice(self, namespace, name):
        return deepcopy(self.endpoint_slice)

    async def replace_endpoint_slice(self, namespace, name, body):
        self.replace_calls += 1
        self.endpoint_slice = deepcopy(body)
        self.endpoint_slice["metadata"]["resourceVersion"] = str(self.replace_calls + 1)
        return deepcopy(self.endpoint_slice)

    async def list_pods(self, namespace, selector):
        return [self.source] if namespace == "edgex-edge" else [self.candidate]


PLAN = "runtime-plan-1234567890abcdef"


def test_git_sensor_contract_is_explicitly_blocked_until_edgemesh_compatibility() -> None:
    catalog = RoutingContractCatalog.load(
        Path(__file__).resolve().parents[1] / "app/config/traffic_routing_contracts.json"
    )
    contract, error = catalog.resolve("sensor-anomaly-demo")
    assert error is None
    assert contract.compatibility_status == "blocked"
    assert contract.compatibility_reason_codes == ["routing_mode_unsupported"]


def test_switch_is_atomic_and_persists_exact_before_after_snapshot() -> None:
    kube = FakeRoutingKube()
    observed = []
    result = asyncio.run(
        TrafficRoutingEngine(kube).switch(
            contract=_contract(),
            plan_id=PLAN,
            candidate_namespace="edge-ai-workloads",
            candidate_name="candidate",
            candidate_node="server-b",
            snapshot_observer=lambda snapshot: observed.append(snapshot),
        )
    )

    assert kube.replace_calls == 1
    assert observed[0].before.addresses == ["10.1.0.1"]
    assert result.active_target == "candidate"
    assert result.before.addresses == ["10.1.0.1"]
    assert result.after.addresses == ["10.2.0.2"]
    assert result.rollback_available is True
    assert kube.endpoint_slice["metadata"]["labels"]["edge-ai.io/execution-plan-id"] == PLAN


def test_rollback_uses_persisted_snapshot_and_restores_source() -> None:
    kube = FakeRoutingKube()
    engine = TrafficRoutingEngine(kube)
    routing = asyncio.run(
        engine.switch(
            contract=_contract(), plan_id=PLAN,
            candidate_namespace="edge-ai-workloads", candidate_name="candidate", candidate_node="server-b",
        )
    )
    restored = asyncio.run(engine.rollback(contract=_contract(), plan_id=PLAN, routing=routing))

    assert kube.replace_calls == 2
    assert restored.active_target == "source"
    assert restored.rollback.addresses == ["10.1.0.1"]
    assert restored.reason_codes == ["traffic_rollback_succeeded"]


@pytest.mark.parametrize(
    ("kube", "contract", "reason"),
    [
        (FakeRoutingKube(selectorless=False), _contract(), "routing_precondition_failed"),
        (FakeRoutingKube(endpoint_slice=_slice(owner=True)), _contract(), "endpointslice_ownership_conflict"),
        (FakeRoutingKube(), _contract(compatibility="blocked"), "routing_mode_unsupported"),
        (FakeRoutingKube(endpoint_slice=_slice(target="candidate", address="10.2.0.2")), _contract(), "routing_state_conflict"),
    ],
)
def test_switch_fails_closed_without_mutation(kube, contract, reason) -> None:
    with pytest.raises(TrafficRoutingError) as caught:
        asyncio.run(
            TrafficRoutingEngine(kube).switch(
                contract=contract, plan_id=PLAN,
                candidate_namespace="edge-ai-workloads", candidate_name="candidate", candidate_node="server-b",
            )
        )
    assert caught.value.reason_code == reason
    assert kube.replace_calls == 0


def test_rollback_refuses_stale_routing_state() -> None:
    kube = FakeRoutingKube()
    engine = TrafficRoutingEngine(kube)
    routing = asyncio.run(
        engine.switch(
            contract=_contract(), plan_id=PLAN,
            candidate_namespace="edge-ai-workloads", candidate_name="candidate", candidate_node="server-b",
        )
    )
    kube.endpoint_slice["endpoints"][0]["addresses"] = ["10.3.0.3"]
    with pytest.raises(TrafficRoutingError) as caught:
        asyncio.run(engine.rollback(contract=_contract(), plan_id=PLAN, routing=routing))
    assert caught.value.reason_code == "routing_state_conflict"
    assert kube.replace_calls == 1


def test_controller_has_no_service_mutation_path_and_rbac_limits_write_to_endpointslice() -> None:
    source = inspect.getsource(KubeClient)
    assert "patch_namespaced_service" not in source
    assert "replace_namespaced_service" not in source
    rbac = (Path(__file__).resolve().parents[1] / "k8s/rbac.yaml").read_text(encoding="utf-8")
    assert 'resources: ["endpointslices"]' in rbac
    assert 'verbs: ["get", "list", "watch", "update"]' in rbac
    assert 'resources: ["services"]\n    verbs: ["update"' not in rbac
