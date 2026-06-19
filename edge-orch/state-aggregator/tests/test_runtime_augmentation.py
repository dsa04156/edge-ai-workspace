from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_augmentation import build_runtime_augmentation_state


def test_runtime_augmentation_state_contains_waiting_virtual_device_pool_for_one_ai_service() -> None:
    state = build_runtime_augmentation_state()

    assert state.scope == "runtime_resource_augmentation_demo_v1"
    assert state.ai_service == "factory-vision-inspection-ai"
    assert state.summary.virtual_device_total == 15
    assert state.summary.waiting == 15
    assert state.summary.running == 0
    assert state.summary.reserved == 0
    assert len(state.virtual_devices) == 15
    assert len({item.name for item in state.virtual_devices}) == 15
    assert {item.state for item in state.virtual_devices} == {"waiting"}
    assert not hasattr(state, "recommendations")


def test_runtime_augmentation_decision_explains_request_and_selected_resources() -> None:
    state = build_runtime_augmentation_state()

    decision = state.decision
    assert decision.scenario == "jetson-vision-inspection"
    assert decision.ai_service == "factory-vision-inspection-ai"
    assert decision.target_device == "etri-dev0001-jetorn"
    assert decision.trigger == "service_resource_request"
    assert decision.state == "selected"
    assert "gpu_inference_pressure" in decision.pressure_reason
    assert [resource.name for resource in decision.selected_resources] == [
        "vd-x86-gpu-inference",
        "vd-storage-cache",
    ]
    assert decision.apply_state == "observed-only"
    assert decision.virtual_device_candidates == [
        "vd-inspection-001",
        "vd-inspection-002",
        "vd-inspection-003",
    ]


def test_runtime_augmentation_route_returns_pool_and_single_decision() -> None:
    with TestClient(app) as client:
        response = client.get("/state/runtime-resource-augmentation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_service"] == "factory-vision-inspection-ai"
    assert payload["summary"]["virtual_device_total"] == 15
    assert len(payload["virtual_devices"]) == 15
    assert payload["virtual_devices"][0]["state"] == "waiting"
    assert payload["decision"]["state"] == "selected"
    assert payload["decision"]["selected_resources"][0]["name"] == "vd-x86-gpu-inference"
    assert "recommendations" not in payload
