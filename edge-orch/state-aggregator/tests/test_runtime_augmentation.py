from __future__ import annotations

from datetime import datetime, timezone

import app.main as main
from fastapi.testclient import TestClient

from app.augmentation_crds import (
    AugmentationResourceCrd,
    AugmentationResourceCrdState,
    DeviceAugmentationCrd,
    DeviceAugmentationCrdState,
    SelectedAugmentationResource,
)
from app.main import app
from app.runtime_augmentation import RuntimeMap, build_runtime_augmentation_state


def _profile(
    *,
    cpu_usage: float,
    memory_usage: float,
    cpu_limit: float = 1.0,
    memory_limit: float = 1024.0,
    gpu_units: float = 1.0,
) -> RuntimeMap:
    return {
        "namespace": "default",
        "service": "factory-vision-inspection-ai",
        "nodes": ["etri-dev0001-jetorn"],
        "resource_requirements": {
            "limits": {
                "cpu_cores": cpu_limit,
                "memory_mib": memory_limit,
                "gpu_units": gpu_units,
            },
        },
        "current_usage": {
            "cpu_cores": cpu_usage,
            "memory_working_set_mib": memory_usage,
            "usage_coverage_ratio": 1.0,
        },
        "usage_profile": {
            "p95_cpu_usage_cores": cpu_usage,
            "p95_memory_working_set_mib": memory_usage,
        },
    }


def _resource(name: str, capabilities: list[str], *, phase: str = "Available", endpoint_ready: bool = True) -> AugmentationResourceCrd:
    return AugmentationResourceCrd(
        name=name,
        display_name=name,
        resource_type="storage-cache" if "cache" in name else "gpu",
        node="etri-ser0002-cgnmsb",
        capabilities=capabilities,
        phase=phase,
        observed_instances=1 if phase == "Available" else 0,
        free_instances=1 if phase == "Available" else 0,
        binding_state="available" if phase == "Available" else "not_running",
        endpoint_ready=endpoint_ready,
        reason="ready" if endpoint_ready else "endpoint is not ready",
    )


def _binding() -> DeviceAugmentationCrd:
    return DeviceAugmentationCrd(
        name="jetson-gpu-storage-augmentation",
        namespace="default",
        target_device_kind="EdgeNode",
        target_device_name="etri-dev0001-jetorn",
        phase="Ready",
        required_capabilities=["gpu_inference", "result_cache"],
        bound_resources=["vd-x86-gpu-inference", "vd-storage-cache"],
        selected_resources=[
            SelectedAugmentationResource(role="inference", name="vd-x86-gpu-inference", endpoint_ready=True),
            SelectedAugmentationResource(role="storage", name="vd-storage-cache", endpoint_ready=True),
        ],
        workload_policy={"mode": "read_only", "automaticOffloading": False},
    )


def test_runtime_augmentation_state_contains_fallback_candidate_resources_not_waiting_virtual_devices() -> None:
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


def test_runtime_augmentation_state_selects_ready_crd_resources_when_workload_has_pressure() -> None:
    state = build_runtime_augmentation_state(
        service_resource_profiles=[_profile(cpu_usage=0.92, memory_usage=940)],
        augmentation_resources=[
            _resource("vd-x86-gpu-inference", ["gpu_inference", "vision_inference"]),
            _resource("vd-storage-cache", ["result_cache", "model_cache"]),
        ],
        device_augmentations=[_binding()],
    )

    decision = state.decision
    assert state.summary.candidate_resource_total == 2
    assert state.summary.available == 2
    assert decision.state == "selected"
    assert decision.pressure_score >= 80
    assert decision.pressure_reason == ["cpu_pressure", "memory_pressure", "gpu_inference_pressure", "cache_required"]
    assert decision.candidate_resource_names == ["vd-x86-gpu-inference", "vd-storage-cache"]
    assert [resource.name for resource in decision.selected_resources] == ["vd-x86-gpu-inference", "vd-storage-cache"]
    assert decision.apply_state == "observed-only"


def test_runtime_augmentation_state_blocks_when_required_resource_endpoint_is_not_ready() -> None:
    state = build_runtime_augmentation_state(
        service_resource_profiles=[_profile(cpu_usage=0.91, memory_usage=930)],
        augmentation_resources=[
            _resource("vd-x86-gpu-inference", ["gpu_inference"], phase="Pending", endpoint_ready=False),
            _resource("vd-storage-cache", ["result_cache"]),
        ],
        device_augmentations=[_binding()],
    )

    decision = state.decision
    assert decision.state == "blocked"
    assert decision.apply_state == "blocked"
    assert decision.selected_resources == []
    assert "required_resource_not_ready:vd-x86-gpu-inference" in decision.pressure_reason
    assert decision.resulting_augmented_device.phase == "Blocked"


def test_runtime_augmentation_state_blocks_when_device_augmentation_status_is_not_ready() -> None:
    blocked_binding = _binding().model_copy(
        update={
            "phase": "Blocked",
            "missing_capabilities": ["result_cache"],
            "selected_resources": [
                SelectedAugmentationResource(role="inference", name="vd-x86-gpu-inference", endpoint_ready=True),
                SelectedAugmentationResource(
                    role="storage",
                    name="vd-storage-cache",
                    phase="Pending",
                    endpoint_ready=False,
                ),
            ],
        }
    )
    state = build_runtime_augmentation_state(
        service_resource_profiles=[_profile(cpu_usage=0.91, memory_usage=930)],
        augmentation_resources=[
            _resource("vd-x86-gpu-inference", ["gpu_inference"]),
            _resource("vd-storage-cache", ["result_cache"]),
        ],
        device_augmentations=[blocked_binding],
    )

    decision = state.decision
    assert decision.state == "blocked"
    assert decision.apply_state == "blocked"
    assert decision.selected_resources == []
    assert "device_augmentation_not_ready:Blocked" in decision.pressure_reason
    assert "device_augmentation_missing_capability:result_cache" in decision.pressure_reason
    assert "selected_resource_endpoint_not_ready:vd-storage-cache" in decision.pressure_reason
    assert "selected_resource_not_ready:vd-storage-cache:Pending" in decision.pressure_reason


def test_runtime_augmentation_state_stays_none_without_resource_pressure_even_with_gpu_limit() -> None:
    state = build_runtime_augmentation_state(
        service_resource_profiles=[_profile(cpu_usage=0.15, memory_usage=120)],
        augmentation_resources=[
            _resource("vd-x86-gpu-inference", ["gpu_inference"]),
            _resource("vd-storage-cache", ["result_cache"]),
        ],
        device_augmentations=[_binding()],
    )

    assert state.decision.state == "none"
    assert state.decision.pressure_score == 0
    assert state.decision.selected_resources == []
    assert state.workflow_demo.status == "observed"
    assert state.workflow_demo.auto_play is False
    assert state.workflow_demo.current_step_id == "service-request"
    assert [phase.id for phase in state.workflow_demo.scenario_timeline] == ["normal"]


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


class FakeAugmentationCrdReader:
    async def get_augmentation_resources(self) -> AugmentationResourceCrdState:
        return AugmentationResourceCrdState(
            generated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            resources=[
                _resource("vd-x86-gpu-inference", ["gpu_inference", "vision_inference"]),
                _resource("vd-storage-cache", ["result_cache", "model_cache"]),
            ],
        )

    async def get_device_augmentations(self, namespace: str = "default") -> DeviceAugmentationCrdState:
        return DeviceAugmentationCrdState(
            generated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            namespace=namespace,
            device_augmentations=[_binding()],
        )


def test_runtime_augmentation_route_returns_observed_pool_and_single_decision(monkeypatch) -> None:
    async def fake_resource_profile_state(refresh: bool = False) -> dict[str, list[RuntimeMap]]:
        return {"service_resource_profiles": [_profile(cpu_usage=0.92, memory_usage=940)]}

    monkeypatch.setattr(main.service, "get_resource_profile_state", fake_resource_profile_state)
    monkeypatch.setattr(main, "augmentation_crds", FakeAugmentationCrdReader())

    with TestClient(app) as client:
        response = client.get("/state/runtime-resource-augmentation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_service"] == "factory-vision-inspection-ai"
    assert payload["summary"]["candidate_resource_total"] == 2
    assert len(payload["candidate_resources"]) == 2
    assert {item["name"] for item in payload["candidate_resources"]} >= {"vd-x86-gpu-inference", "vd-storage-cache"}
    assert payload["decision"]["state"] == "selected"
    assert payload["decision"]["resulting_augmented_device"]["name"] == "ad-jetorn-inspection-001"
    assert payload["decision"]["selected_resources"][0]["name"] == "vd-x86-gpu-inference"
    assert "virtual_devices" not in payload
    assert "recommendations" not in payload


def test_runtime_augmentation_route_keeps_deterministic_demo_mode() -> None:
    with TestClient(app) as client:
        response = client.get("/state/runtime-resource-augmentation?mode=demo")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["candidate_resource_total"] == 15
    assert payload["decision"]["state"] == "selected"
    assert payload["workflow_demo"]["current_step_id"] == "offload-plan"


def test_runtime_augmentation_state_exposes_workflow_demo_and_offload_path() -> None:
    state = build_runtime_augmentation_state()

    workflow = state.workflow_demo
    assert workflow.name == "inspection-resource-augmentation-demo"
    assert workflow.status == "offload_planned"
    assert workflow.automation_trigger == "runtime_metrics_observed"
    assert workflow.progress_percent == 80
    assert workflow.current_step_id == "offload-plan"
    assert workflow.operator_summary == "GPU inference and result-cache offload are ready as an observed-only binding plan."
    assert workflow.auto_play is True
    assert workflow.playback_interval_ms == 1600
    assert [phase.id for phase in workflow.scenario_timeline] == [
        "normal",
        "pressure_detected",
        "candidate_evaluating",
        "offload_planned",
        "binding_planned",
        "observed_only_complete",
    ]
    assert [phase.progress_percent for phase in workflow.scenario_timeline] == [0, 20, 40, 60, 80, 100]
    assert [phase.active_step_id for phase in workflow.scenario_timeline] == [
        "service-request",
        "pressure-detected",
        "candidate-scan",
        "offload-plan",
        "augmented-device-bind",
        "observed-only-complete",
    ]
    assert [step.state for step in workflow.steps] == [
        "completed",
        "completed",
        "completed",
        "active",
        "planned",
        "planned",
    ]
    assert [step.id for step in workflow.steps] == [
        "service-request",
        "pressure-detected",
        "candidate-scan",
        "offload-plan",
        "augmented-device-bind",
        "observed-only-complete",
    ]
    assert workflow.offload_path.source == "etri-dev0001-jetorn"
    assert workflow.offload_path.inference == "vd-x86-gpu-inference"
    assert workflow.offload_path.cache == "vd-storage-cache"
    assert workflow.offload_path.result == "ad-jetorn-inspection-001"
