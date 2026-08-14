from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.device_twins import build_device_twin_state
from app.main import app, service, service_demo_client
from app.models import DeviceState, TelemetryPoint
from app.service_demo_models import (
    DeployedServiceItem,
    ServiceDemoBinding,
    ServiceDemoState,
)


def _device(*, name: str = "acceleration-x", status: str = "available") -> DeviceState:
    now = datetime.now(timezone.utc)
    return DeviceState(
        name=name,
        profile_name="acceleration-profile",
        device_service_name="device-serial-jetson",
        admin_state="UNLOCKED",
        operating_state="UP",
        connection_state="connected",
        device_service_available=True,
        latest_event_timestamp=now,
        latest_readings=[
            TelemetryPoint(
                device_name=name,
                source_name="acceleration",
                resource_name="acceleration_x_raw",
                value_type="Float64",
                value=0.2,
                timestamp=now,
                origin=1,
            )
        ],
        telemetry_freshness="fresh" if status == "available" else "stale",
        overall_status=status,
        reason="latest EdgeX event is fresh",
        node_name="etri-dev0001-jetorn",
        physical_device_id="arduino-001",
    )


def _deployed_service(
    service_id: str,
    display_name: str,
    *,
    mode: str = "live",
) -> DeployedServiceItem:
    return DeployedServiceItem(
        service_id=service_id,
        display_name=display_name,
        description=f"{display_name} service",
        mode=mode,
        status="normal" if mode == "live" else "degraded",
        input_state="fresh" if mode == "live" else "unobserved",
        model_state="ready" if mode == "live" else "unobserved",
        node="etri-dev0001-jetorn",
        physical_source="arduino-001",
        device_service="device-serial-jetson",
        input_devices=["acceleration-x"],
        descriptor={"input_contract": {"schema": f"{service_id}/v1"}},
    )


def test_device_twin_state_keeps_physical_source_and_observed_scope():
    state = build_device_twin_state(devices=[_device()])

    assert state.mode == "read_only"
    assert state.twin_scope == "observed_state_not_control"
    assert state.summary.physical_devices == 1
    assert state.summary.device_twins == 1
    assert state.summary.unbound_twins == 1
    twin = state.twins[0]
    assert twin.id == "twin:acceleration-x"
    assert twin.physical_device_id == "arduino-001"
    assert twin.observed_resources == ["acceleration_x_raw"]
    assert twin.authority == "edgex"


def test_device_twin_binding_is_separate_from_twin_health():
    state = build_device_twin_state(
        devices=[_device()],
        deployed_services=[
            _deployed_service("sensor-anomaly-demo", "센서 이상 탐지")
        ],
    )

    assert state.summary.service_bound_twins == 1
    assert state.summary.service_connections == 1
    assert state.summary.attention_twins == 0
    assert state.twins[0].health == "ready"
    assert state.twins[0].service_bindings[0].status == "active"
    assert state.twins[0].service_bindings[0].service_name == "센서 이상 탐지"


def test_one_device_twin_can_bind_multiple_services_independently():
    state = build_device_twin_state(
        devices=[_device()],
        deployed_services=[
            _deployed_service("sensor-anomaly-demo", "센서 이상 탐지"),
            _deployed_service(
                "production-quality-demo",
                "생산품질 판별",
                mode="unavailable",
            ),
        ],
    )

    assert state.summary.service_bound_twins == 1
    assert state.summary.service_connections == 2
    assert [binding.service_id for binding in state.twins[0].service_bindings] == [
        "production-quality-demo",
        "sensor-anomaly-demo",
    ]
    assert [binding.status for binding in state.twins[0].service_bindings] == [
        "unavailable",
        "active",
    ]


def test_device_twin_state_omits_raw_physical_source_without_projection_provenance():
    raw_source = _device(name="arduino-source").model_copy(
        update={"physical_device_id": None}
    )

    state = build_device_twin_state(devices=[raw_source, _device()])

    assert [twin.name for twin in state.twins] == ["acceleration-x"]


def test_device_twin_api_exposes_edge_observation_and_service_binding(monkeypatch):
    async def devices():
        return [_device()]

    async def demo_state():
        return ServiceDemoState(
            generated_at=datetime.now(timezone.utc),
            mode="live",
            status="normal",
            input_state="fresh",
            model_state="ready",
            binding=ServiceDemoBinding(devices=["acceleration-x"]),
        )

    monkeypatch.setattr(service, "get_devices", devices)
    monkeypatch.setattr(service_demo_client, "get_state", demo_state)

    with TestClient(app) as client:
        response = client.get("/state/device-twins")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authority"] == "edgex_metadata_and_core_data"
    assert payload["summary"]["service_bound_twins"] == 1
    assert payload["twins"][0]["physical_device_id"] == "arduino-001"
    assert payload["twins"][0]["service_bindings"][0]["status"] == "active"


def test_device_twin_api_uses_all_services_from_canonical_inventory(monkeypatch):
    async def devices():
        return [_device()]

    async def demo_state():
        return ServiceDemoState(
            generated_at=datetime.now(timezone.utc),
            mode="live",
            status="normal",
            input_state="fresh",
            model_state="ready",
            binding=ServiceDemoBinding(devices=["acceleration-x"]),
        )

    monkeypatch.setattr(service, "get_devices", devices)
    monkeypatch.setattr(service_demo_client, "get_state", demo_state)
    monkeypatch.setattr(
        main,
        "_deployed_service_state",
        lambda _: SimpleNamespace(
            services=[
                _deployed_service("sensor-anomaly-demo", "센서 이상 탐지"),
                _deployed_service("production-quality-demo", "생산품질 판별"),
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.get("/state/device-twins")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["service_connections"] == 2
    assert [
        binding["service_id"]
        for binding in payload["twins"][0]["service_bindings"]
    ] == ["production-quality-demo", "sensor-anomaly-demo"]
