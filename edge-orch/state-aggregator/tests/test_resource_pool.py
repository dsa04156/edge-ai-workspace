from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.kube import KubeClient, KubeResourceReadError
from app.main import app, service
from app.models import (
    NodeSchedulingResource,
    NodeState,
    SchedulingResourceAmounts,
)
from app.resource_pool import (
    build_kubernetes_resource_snapshots,
    build_node_scheduling_resources,
)


def _container(requests: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(resources=SimpleNamespace(requests=requests))


def _pod(
    node: str,
    phase: str,
    containers: list[SimpleNamespace],
    *,
    init_containers: list[SimpleNamespace] | None = None,
    overhead: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        spec=SimpleNamespace(
            node_name=node,
            containers=containers,
            init_containers=init_containers or [],
            overhead=overhead or {},
        ),
        status=SimpleNamespace(phase=phase),
    )


def _node(
    name: str,
    *,
    ready: bool = True,
    unschedulable: bool = False,
    labels: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels={"kubernetes.io/arch": "amd64", **(labels or {})},
        ),
        spec=SimpleNamespace(unschedulable=unschedulable),
        status=SimpleNamespace(
            allocatable={"cpu": "8", "memory": "16Gi", "nvidia.com/gpu": "2"},
            conditions=[SimpleNamespace(type="Ready", status="True" if ready else "False")],
        ),
    )


def _node_state(name: str, *, health: str = "healthy") -> NodeState:
    return NodeState(
        hostname=name,
        instance="192.0.2.10:9100",
        node_type="cloud_server",
        collected_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        raw_metrics={
            "cpu_utilization": 0.25,
            "memory_usage_ratio": 0.5,
            "gpu_utilization": 0.4,
            "gpu_memory_usage_ratio": 0.6,
            "load_average": 1.2,
            "network_rx_rate": 1000,
            "network_tx_rate": 2000,
        },
        compute_pressure="low",
        memory_pressure="low",
        network_pressure="low",
        node_health=health,
    )


def test_build_resource_pool_uses_allocatable_minus_non_terminal_pod_requests():
    nodes = [_node("server01", labels={"accelerator": "RTX5060Ti"})]
    pods = [
        _pod(
            "server01",
            "Running",
            [
                _container({"cpu": "500m", "memory": "1Gi", "nvidia.com/gpu": "1"}),
                _container({"cpu": "1", "memory": "512Mi"}),
            ],
            init_containers=[_container({"cpu": "2", "memory": "256Mi"})],
            overhead={"cpu": "100m", "memory": "128Mi"},
        ),
        _pod("server01", "Pending", [_container({"cpu": "400m", "memory": "512Mi"})]),
        _pod("server01", "Succeeded", [_container({"cpu": "7", "memory": "12Gi"})]),
    ]

    snapshots = build_kubernetes_resource_snapshots(
        nodes,
        pods,
        lambda _: "cloud_server",
    )
    resources = build_node_scheduling_resources(snapshots, [_node_state("server01")])

    assert len(resources) == 1
    resource = resources[0]
    assert resource.cpu_available == 5.5
    assert resource.memory_available_gb == 14.898
    assert resource.accelerator == "RTX5060Ti"
    assert resource.health == "healthy"
    assert resource.schedulable is True
    assert resource.reason_codes == ["ready"]
    assert resource.requested.cpu_cores == 2.5
    assert resource.requested.memory_bytes == int(2.125 * 1024**3)
    assert resource.requested.accelerator_units == {"nvidia.com/gpu": 1.0}
    assert resource.available.memory_bytes == int(13.875 * 1024**3)
    assert resource.available.accelerator_units == {"nvidia.com/gpu": 1.0}
    assert resource.utilization is not None
    assert resource.utilization.cpu_ratio == 0.25
    assert resource.utilization.memory_ratio == 0.5


def test_kube_client_reads_nodes_and_all_namespaces_pods_for_resource_snapshot():
    nodes = [_node("server01")]
    pods = [_pod("server01", "Running", [_container({"cpu": "250m", "memory": "1Gi"})])]

    class FakeCoreV1:
        def __init__(self):
            self.node_reads = 0
            self.pod_reads = 0

        def list_node(self):
            self.node_reads += 1
            return SimpleNamespace(items=nodes)

        def list_pod_for_all_namespaces(self):
            self.pod_reads += 1
            return SimpleNamespace(items=pods)

    kube = KubeClient.__new__(KubeClient)
    kube.enabled = True
    kube.v1 = FakeCoreV1()

    snapshots = asyncio.run(kube.get_scheduling_resource_snapshots())

    assert kube.v1.node_reads == 1
    assert kube.v1.pod_reads == 1
    assert snapshots[0].node == "server01"
    assert snapshots[0].requested.cpu_cores == 0.25
    assert snapshots[0].requested.memory_bytes == 1024**3


def test_resource_pool_fails_closed_for_not_ready_or_unobserved_nodes():
    snapshots = build_kubernetes_resource_snapshots(
        [
            _node("not-ready", ready=False),
            _node("metrics-missing"),
        ],
        [],
        lambda _: "edge_device",
    )

    resources = build_node_scheduling_resources(
        snapshots,
        [_node_state("not-ready")],
    )
    by_node = {resource.node: resource for resource in resources}

    assert by_node["not-ready"].health == "unavailable"
    assert by_node["not-ready"].schedulable is False
    assert "node_not_ready" in by_node["not-ready"].reason_codes
    assert by_node["metrics-missing"].health == "unavailable"
    assert by_node["metrics-missing"].schedulable is False
    assert by_node["metrics-missing"].utilization is None
    assert "prometheus_metrics_unavailable" in by_node["metrics-missing"].reason_codes


def test_resource_pool_does_not_invent_capacity_for_requested_only_accelerator_keys():
    snapshots = build_kubernetes_resource_snapshots(
        [_node("server01")],
        [
            _pod(
                "server01",
                "Running",
                [_container({"nvidia.com/gpucores": "20"})],
            )
        ],
        lambda _: "cloud_server",
    )

    resource = build_node_scheduling_resources(
        snapshots,
        [_node_state("server01")],
    )[0]

    assert resource.requested.accelerator_units["nvidia.com/gpucores"] == 20
    assert "nvidia.com/gpucores" not in resource.available.accelerator_units
    assert "accelerator_capacity_unreported" in resource.reason_codes


def test_api_resources_returns_camel_case_scheduling_contract_without_changing_state_nodes(
    monkeypatch,
):
    original_node = _node_state("server01")
    monkeypatch.setattr(service.store, "nodes", {original_node.hostname: original_node})
    resource = NodeSchedulingResource(
        node="server01",
        cpu_available=5.5,
        memory_available_gb=14.898,
        accelerator="RTX5060Ti",
        health="healthy",
        schedulable=True,
        reason_codes=["ready"],
        architecture="amd64",
        node_type="cloud_server",
        allocatable=SchedulingResourceAmounts(
            cpu_cores=8,
            memory_bytes=16 * 1024**3,
            accelerator_units={"nvidia.com/gpu": 2},
        ),
        requested=SchedulingResourceAmounts(
            cpu_cores=2.5,
            memory_bytes=int(2.125 * 1024**3),
            accelerator_units={"nvidia.com/gpu": 1},
        ),
        available=SchedulingResourceAmounts(
            cpu_cores=5.5,
            memory_bytes=int(13.875 * 1024**3),
            accelerator_units={"nvidia.com/gpu": 1},
        ),
    )

    async def fake_resources():
        return [resource]

    monkeypatch.setattr(service, "get_scheduling_resources", fake_resources)

    with TestClient(app) as client:
        resource_response = client.get("/api/resources")
        node_response = client.get("/state/nodes")

    assert resource_response.status_code == 200
    payload = resource_response.json()
    assert payload[0]["node"] == "server01"
    assert payload[0]["cpuAvailable"] == 5.5
    assert payload[0]["memoryAvailableGB"] == 14.898
    assert payload[0]["accelerator"] == "RTX5060Ti"
    assert payload[0]["health"] == "healthy"
    assert payload[0]["schedulable"] is True
    assert payload[0]["allocatable"]["cpuCores"] == 8
    assert payload[0]["requested"]["acceleratorUnits"] == {"nvidia.com/gpu": 1.0}
    assert payload[0]["available"]["memoryBytes"] == int(13.875 * 1024**3)
    assert node_response.status_code == 200
    assert node_response.json()[0]["hostname"] == "server01"
    assert "cpuAvailable" not in node_response.json()[0]


def test_api_resources_returns_503_when_kubernetes_snapshot_is_unavailable(monkeypatch):
    async def unavailable():
        raise KubeResourceReadError("Kubernetes client is unavailable")

    monkeypatch.setattr(service, "get_scheduling_resources", unavailable)

    with TestClient(app) as client:
        response = client.get("/api/resources")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kubernetes_resource_snapshot_unavailable"
