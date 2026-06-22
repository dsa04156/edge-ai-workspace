from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_augmentation import build_runtime_augmentation_state


def test_runtime_augmentation_state_contains_candidate_resources_not_waiting_virtual_devices() -> None:
    state = build_runtime_augmentation_state()

    assert state.scope == "runtime_resource_augmentation_demo_v1"
    assert state.ai_service == "factory-vision-inspection-ai"
    assert state.summary.candidate_resource_total == 15
    assert state.summary.available == 12
    assert state.summary.bound == 0
    assert state.summary.blocked == 3
    assert len(state.candidate_resources) == 15
    assert len({item.name for item in state.candidate_resources}) == 15
    assert {item.name for item in state.candidate_resources} >= {"vd-x86-gpu-inference", "vd-storage-cache"}
    assert {item.kind for item in state.candidate_resources} >= {"gpu-inference", "storage-cache", "model-cache"}
    assert not hasattr(state, "virtual_devices")
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
    assert decision.resulting_augmented_device.name == "ad-jetorn-inspection-001"
    assert decision.resulting_augmented_device.target_device == "etri-dev0001-jetorn"
    assert decision.resulting_augmented_device.phase == "Planned"
    assert [resource.name for resource in decision.selected_resources] == [
        "vd-x86-gpu-inference",
        "vd-storage-cache",
    ]
    assert decision.apply_state == "observed-only"
    assert decision.candidate_resource_names == [
        "vd-x86-gpu-inference",
        "vd-storage-cache",
    ]


def test_runtime_augmentation_route_returns_pool_and_single_decision() -> None:
    with TestClient(app) as client:
        response = client.get("/state/runtime-resource-augmentation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_service"] == "factory-vision-inspection-ai"
    assert payload["summary"]["candidate_resource_total"] == 15
    assert len(payload["candidate_resources"]) == 15
    assert {item["name"] for item in payload["candidate_resources"]} >= {"vd-x86-gpu-inference", "vd-storage-cache"}
    assert payload["decision"]["state"] == "selected"
    assert payload["decision"]["resulting_augmented_device"]["name"] == "ad-jetorn-inspection-001"
    assert payload["decision"]["selected_resources"][0]["name"] == "vd-x86-gpu-inference"
    assert "virtual_devices" not in payload
    assert "recommendations" not in payload


def test_runtime_augmentation_state_exposes_workflow_demo_and_offload_path() -> None:
    state = build_runtime_augmentation_state()

    workflow = state.workflow_demo
    assert workflow.name == "inspection-resource-augmentation-demo"
    assert workflow.status == "offload_planned"
    assert workflow.automation_trigger == "runtime_metrics_observed"
    assert workflow.progress_percent == 80
    assert workflow.current_step_id == "offload-plan"
    assert workflow.operator_summary == "GPU 추론과 결과 캐시 오프로딩이 observed-only 바인딩 계획으로 준비됨."
    assert [step.state for step in workflow.steps] == [
        "completed",
        "completed",
        "completed",
        "active",
        "planned",
    ]
    assert [step.id for step in workflow.steps] == [
        "service-request",
        "pressure-detected",
        "candidate-scan",
        "offload-plan",
        "augmented-device-bind",
    ]
    assert workflow.offload_path.source == "etri-dev0001-jetorn"
    assert workflow.offload_path.inference == "vd-x86-gpu-inference"
    assert workflow.offload_path.cache == "vd-storage-cache"
    assert workflow.offload_path.result == "ad-jetorn-inspection-001"
