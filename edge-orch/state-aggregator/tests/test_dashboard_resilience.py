import httpx
from fastapi.testclient import TestClient

from app.main import app, service


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
    assert payload["recommended_actions"] == ["현재 우선 점검 대상이 없으므로 dashboard KPI와 service demo group만 확인한다."]
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
