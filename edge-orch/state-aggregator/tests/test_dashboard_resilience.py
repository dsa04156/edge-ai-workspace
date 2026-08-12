from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from app.edgex import EdgeXBackendError
from app.main import app, service
from app.models import NodeState


def _healthy_node() -> NodeState:
    return NodeState(
        hostname="etri-ser0001-cg0msb",
        instance="192.168.0.56:9100",
        node_type="cloud_server",
        collected_at=datetime.now(timezone.utc),
        raw_metrics={"up": 1.0},
        compute_pressure="low",
        memory_pressure="low",
        network_pressure="low",
        node_health="healthy",
    )


async def _empty_resource_state(refresh=False):
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile_scope": "running_service_resource_requirements",
        "summary": {
            "profile_count": 0,
            "running_pod_count": 0,
            "container_count": 0,
            "declared_request_cpu_cores": 0,
            "declared_request_memory_mib": 0,
            "current_cpu_usage_cores": 0,
            "current_memory_working_set_mib": 0,
            "usage_coverage_ratio": 0,
            "declared_limit_gpu_units": 0,
            "fully_declared_profile_count": 0,
            "partially_declared_profile_count": 0,
        },
        "service_resource_profiles": [],
    }


def test_dashboard_endpoint_isolates_edgex_device_observation_failure(monkeypatch):
    async def failing_devices():
        raise EdgeXBackendError("Core Metadata unavailable")

    monkeypatch.setattr(service, "get_nodes", lambda: [_healthy_node()])
    monkeypatch.setattr(service, "get_devices", failing_devices)
    monkeypatch.setattr(service, "get_workflows", lambda: [])
    monkeypatch.setattr(service, "get_resource_profile_state", _empty_resource_state)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert [node["hostname"] for node in payload["nodes"]] == [
        "etri-ser0001-cg0msb"
    ]
    assert payload["devices"] == []
    assert payload["device_observation_error"] == (
        "EdgeX device observation unavailable: EdgeXBackendError"
    )


def test_dashboard_endpoint_has_no_device_observation_error_when_edgex_is_available(
    monkeypatch,
):
    async def fake_devices():
        return []

    monkeypatch.setattr(service, "get_nodes", lambda: [])
    monkeypatch.setattr(service, "get_devices", fake_devices)
    monkeypatch.setattr(service, "get_workflows", lambda: [])
    monkeypatch.setattr(service, "get_resource_profile_state", _empty_resource_state)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    assert response.json()["device_observation_error"] is None


def test_dashboard_endpoint_degrades_when_resource_observation_fails(monkeypatch):
    async def fake_devices():
        return []

    async def fake_resource_state(refresh=False):
        raise httpx.ConnectError("prometheus unavailable")

    monkeypatch.setattr(service, "get_nodes", lambda: [])
    monkeypatch.setattr(service, "get_devices", fake_devices)
    monkeypatch.setattr(service, "get_workflows", lambda: [])
    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource_profiles"]["observation_error"] == "service resource observation unavailable: ConnectError"
    assert payload["resource_profiles"]["service_resource_profiles"] == []
    assert payload["kpis"]["service_resource_profile_count"] == 0


def test_operator_assistant_endpoint_degrades_when_resource_observation_fails(monkeypatch):
    async def fake_devices():
        return []

    async def fake_resource_state(refresh=False):
        raise httpx.ConnectError("prometheus unavailable")

    monkeypatch.setattr(service, "get_nodes", lambda: [])
    monkeypatch.setattr(service, "get_devices", fake_devices)
    monkeypatch.setattr(service, "get_workflows", lambda: [])
    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)

    with TestClient(app) as client:
        response = client.get("/state/operator-assistant")

    assert response.status_code == 200
    payload = response.json()
    assert "등록 device 0개" in payload["summary_ko"]
    assert payload["recommended_actions"] == ["현재 우선 점검 대상이 없으므로 EdgeX KPI를 확인한다."]
    assert payload["source_endpoints"] == [
        "/state/dashboard",
        "/state/devices",
        "/state/nodes",
        "/state/summary",
        "/state/virtual-resources",
    ]


def test_operator_chat_endpoint_degrades_when_resource_observation_fails(monkeypatch):
    async def fake_devices():
        return []

    async def fake_resource_state(refresh=False):
        raise httpx.ConnectError("prometheus unavailable")

    monkeypatch.setattr(service, "get_nodes", lambda: [])
    monkeypatch.setattr(service, "get_devices", fake_devices)
    monkeypatch.setattr(service, "get_workflows", lambda: [])
    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)

    with TestClient(app) as client:
        response = client.post("/state/operator-chat", json={"message": "현재 상태 알려줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["upstream_status"] == "degraded_observation"
    assert "observation_error" in payload["answer"]
    assert payload["source_endpoints"] == [
        "/state/dashboard",
        "/state/devices",
        "/state/nodes",
        "/state/summary",
        "/state/virtual-resources",
    ]
