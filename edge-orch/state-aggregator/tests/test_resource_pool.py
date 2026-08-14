from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app, service, service_demo_client
from app.models import DeviceState, NodeState, TelemetryPoint
from app.resource_pool import (
    ResourcePoolPlanRequest,
    build_resource_pool_plan,
    build_resource_pool_state,
)
from app.virtual_resources import VirtualResourceState
from app.service_demo import ServiceDemoError


def _devices(status: str = "ready") -> list[DeviceState]:
    now = datetime.now(timezone.utc)
    return [
        DeviceState(
            name="sensor-001",
            profile_name="vibration-profile",
            device_service_name="device-serial",
            admin_state="UNLOCKED",
            operating_state="UP",
            connection_state="connected",
            device_service_available=True,
            latest_event_timestamp=now,
            latest_readings=[
                TelemetryPoint(
                    device_name="sensor-001",
                    source_name="acceleration",
                    resource_name="acceleration_x",
                    value_type="Float64",
                    value=0.2,
                    timestamp=now,
                    origin=1,
                )
            ],
            telemetry_freshness="fresh" if status == "ready" else "stale",
            overall_status="available" if status == "ready" else "degraded",
            reason="EdgeX Core Data fresh" if status == "ready" else "Core Data stale",
            node_name="edge-node",
            physical_device_id="physical-sensor-001",
        )
    ]


def _node() -> NodeState:
    return NodeState(
        hostname="edge-node",
        instance="edge-node:9100",
        node_type="edge_device",
        collected_at=datetime.now(timezone.utc),
        raw_metrics={"up": 1.0, "cpu_utilization": 0.2},
        compute_pressure="low",
        memory_pressure="low",
        network_pressure="low",
        node_health="healthy",
    )


def _state(status: str = "ready"):
    return build_resource_pool_state(
        devices=_devices(status),
        virtual_resources=VirtualResourceState(
            generated_at=datetime.now(timezone.utc), resources=[]
        ),
        nodes=[_node()],
        service_observations={"sensor-anomaly-demo": "ready"},
        service_bindings={"sensor-anomaly-demo": ["sensor-001"]},
    )


def test_resource_pool_combines_authoritative_resources_and_bindings():
    state = _state()

    assert state.mode == "read_only"
    assert state.reservation_mode == "dry_run"
    assert state.summary.total_resources == 3
    assert state.summary.data_resources == 1
    assert state.summary.compute_resources == 1
    assert state.summary.service_resources == 1
    assert state.summary.virtual_devices == 1
    assert state.summary.used_virtual_devices == 1
    assert state.summary.available_virtual_devices == 0
    assert state.summary.ready_resources == 3
    assert state.summary.active_bindings == 1
    assert {item.authority for item in state.resources} == {
        "edgex",
        "kubernetes",
        "service_catalog",
    }
    assert state.bindings[0].data_resource_id == "data:sensor-001"
    virtual_device = next(item for item in state.resources if item.category == "data")
    assert virtual_device.kind == "edgex_virtual_device"
    assert virtual_device.metadata["usage_state"] == "in_use"
    assert virtual_device.metadata["physical_device_id"] == "physical-sensor-001"


def test_resource_pool_only_exposes_split_virtual_devices_as_service_inputs():
    raw_source = _devices()[0].model_copy(
        update={
            "name": "physical-sensor-source",
            "profile_name": "multi-resource-profile",
            "physical_device_id": None,
        }
    )

    state = build_resource_pool_state(
        devices=[raw_source, *_devices()],
        virtual_resources=VirtualResourceState(
            generated_at=datetime.now(timezone.utc), resources=[]
        ),
        nodes=[_node()],
    )

    assert "data:physical-sensor-source" not in {item.id for item in state.resources}
    assert "data:sensor-001" in {item.id for item in state.resources}
    assert state.summary.virtual_devices == 1


def test_resource_pool_filters_without_changing_total_summary():
    state = build_resource_pool_state(
        devices=_devices(),
        virtual_resources=VirtualResourceState(
            generated_at=datetime.now(timezone.utc), resources=[]
        ),
        nodes=[_node()],
        search="vibration-profile",
        category="data",
        status="ready",
    )

    assert [item.id for item in state.resources] == ["data:sensor-001"]
    assert state.summary.total_resources == 3
    assert state.summary.visible_resources == 1
    assert state.query.search == "vibration-profile"


def test_resource_pool_uses_explicit_live_service_observation_over_binding_inference():
    state = build_resource_pool_state(
        devices=_devices(),
        virtual_resources=VirtualResourceState(
            generated_at=datetime.now(timezone.utc), resources=[]
        ),
        nodes=[_node()],
        service_observations={"sensor-anomaly-demo": "unavailable"},
    )

    service_item = next(item for item in state.resources if item.category == "service")
    assert service_item.status == "unavailable"
    assert service_item.selectable is True


def test_resource_pool_plan_selects_compatible_ready_data_without_mutation():
    plan = build_resource_pool_plan(
        ResourcePoolPlanRequest(service_id="sensor-anomaly-demo"),
        _state(),
        now=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )

    assert plan.compatible is True
    assert plan.mode == "dry_run"
    assert plan.selection.data_resource_id == "data:sensor-001"
    assert plan.lease_preview is not None
    assert plan.lease_preview.persisted is False
    assert plan.lease_preview.id.startswith("dryrun-")
    assert {check.status for check in plan.checks} <= {"pass", "not_required"}
    assert any("변경" in check.detail for check in plan.checks)


def test_resource_pool_plan_blocks_stale_data():
    plan = build_resource_pool_plan(
        ResourcePoolPlanRequest(
            service_id="sensor-anomaly-demo",
            data_resource_id="data:sensor-001",
        ),
        _state("degraded"),
    )

    assert plan.compatible is False
    assert plan.lease_preview is None
    assert plan.blocked_reasons
    assert next(check for check in plan.checks if check.code == "data_compatible").status == "fail"


def test_resource_pool_api_is_read_only_and_plan_is_non_persistent(monkeypatch):
    async def devices():
        return []

    async def resource_state(refresh=False):
        return {"service_resource_profiles": []}

    async def unavailable_demo():
        raise ServiceDemoError("unavailable")

    monkeypatch.setattr(service, "get_devices", devices)
    monkeypatch.setattr(service, "get_resource_profile_state", resource_state)
    monkeypatch.setattr(service_demo_client, "get_state", unavailable_demo)
    service.store.nodes = {}

    with TestClient(app) as client:
        pool_response = client.get("/state/resource-pool?category=service")
        plan_response = client.post(
            "/state/resource-pool/plan",
            json={"service_id": "sensor-anomaly-demo"},
        )

    assert pool_response.status_code == 200
    assert pool_response.json()["mode"] == "read_only"
    assert pool_response.json()["reservation_mode"] == "dry_run"
    assert [item["id"] for item in pool_response.json()["resources"]] == [
        "service:sensor-anomaly-demo"
    ]
    assert plan_response.status_code == 200
    assert plan_response.json()["mode"] == "dry_run"
    assert plan_response.json()["lease_preview"] is None
