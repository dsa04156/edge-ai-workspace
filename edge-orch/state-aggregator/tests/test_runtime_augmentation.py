from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_augmentation import build_runtime_augmentation_state


def test_runtime_augmentation_state_contains_15_virtual_devices_for_one_ai_service() -> None:
    state = build_runtime_augmentation_state()

    assert state.scope == "runtime_resource_augmentation_demo_v1"
    assert state.summary.total == 15
    assert len(state.recommendations) == 15
    assert state.ai_service == "factory-vision-inspection-ai"
    assert {item.ai_service for item in state.recommendations} == {"factory-vision-inspection-ai"}
    assert len({item.virtual_device for item in state.recommendations}) == 15
    assert state.summary.selected == 5
    assert state.summary.blocked == 2
    assert state.summary.candidate == 4
    assert state.summary.none == 4


def test_runtime_augmentation_selected_items_explain_pressure_and_resources() -> None:
    state = build_runtime_augmentation_state()

    selected = [item for item in state.recommendations if item.recommendation == "selected"]
    assert selected
    first = selected[0]
    assert first.scenario == "jetson-vision-inspection"
    assert first.ai_service == "factory-vision-inspection-ai"
    assert first.target_device == "etri-dev0001-jetorn"
    assert "gpu_inference_pressure" in first.pressure_reason
    assert [resource.name for resource in first.selected_resources] == [
        "vd-x86-gpu-inference",
        "vd-storage-cache",
    ]
    assert first.apply_state == "observed-only"


def test_runtime_augmentation_route_returns_demo_recommendations() -> None:
    with TestClient(app) as client:
        response = client.get("/state/runtime-resource-augmentation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_service"] == "factory-vision-inspection-ai"
    assert payload["summary"]["total"] == 15
    assert len(payload["recommendations"]) == 15
    assert {item["ai_service"] for item in payload["recommendations"]} == {"factory-vision-inspection-ai"}
    assert payload["recommendations"][0]["virtual_device"].startswith("vd-inspection-")
