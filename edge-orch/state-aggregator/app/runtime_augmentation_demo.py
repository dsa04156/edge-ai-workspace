from __future__ import annotations

from datetime import datetime, timezone

from .runtime_augmentation_models import (
    AI_SERVICE,
    INFERENCE_RESOURCE,
    SCENARIO_ID,
    STORAGE_RESOURCE,
    TARGET_DEVICE,
    DecisionState,
    RuntimeAugmentationAugmentedDevice,
    RuntimeAugmentationCandidateResource,
    RuntimeAugmentationDecision,
    RuntimeAugmentationOffloadPath,
    RuntimeAugmentationScenarioPhase,
    RuntimeAugmentationSelectedResource,
    RuntimeAugmentationState,
    RuntimeAugmentationSummary,
    RuntimeAugmentationWorkflowDemo,
    RuntimeAugmentationWorkflowStep,
)


def build_demo_runtime_augmentation_state() -> RuntimeAugmentationState:
    candidate_resources = _candidate_resources()
    return RuntimeAugmentationState(
        generated_at=datetime.now(timezone.utc),
        summary=RuntimeAugmentationSummary(
            candidate_resource_total=len(candidate_resources),
            available=sum(1 for item in candidate_resources if item.phase == "Available"),
            bound=sum(1 for item in candidate_resources if item.phase == "Bound"),
            blocked=sum(1 for item in candidate_resources if item.phase == "Blocked"),
        ),
        candidate_resources=candidate_resources,
        decision=_decision(),
        workflow_demo=_workflow_demo(),
    )


def _candidate_resources() -> list[RuntimeAugmentationCandidateResource]:
    resources = [
        RuntimeAugmentationCandidateResource(
            name=INFERENCE_RESOURCE,
            kind="gpu-inference",
            node="x86-gpu-pool",
            capability="remote gpu inference runtime",
        ),
        RuntimeAugmentationCandidateResource(
            name=STORAGE_RESOURCE,
            kind="storage-cache",
            node="storage-pool",
            capability="result window cache",
        ),
        *[
            RuntimeAugmentationCandidateResource(
                name=f"aug-gpu-x86-{index:03d}",
                kind="gpu-inference",
                node="x86-gpu-pool",
                capability="remote gpu inference runtime",
            )
            for index in range(1, 9)
        ],
        RuntimeAugmentationCandidateResource(
            name="aug-storage-cache-001",
            kind="storage-cache",
            node="storage-pool",
            capability="result window cache",
        ),
        RuntimeAugmentationCandidateResource(
            name="aug-model-cache-001",
            kind="model-cache",
            node="storage-pool",
            capability="model artifact cache",
        ),
    ]
    resources.extend(
        [
            RuntimeAugmentationCandidateResource(
                name="aug-jetson-gpu-001",
                kind="gpu-inference",
                phase="Blocked",
                node="jetson-pool",
                capability="jetson gpu runtime",
            ),
            RuntimeAugmentationCandidateResource(
                name="aug-jetson-gpu-002",
                kind="gpu-inference",
                phase="Blocked",
                node="jetson-pool",
                capability="jetson gpu runtime",
            ),
            RuntimeAugmentationCandidateResource(
                name="aug-storage-cache-002",
                kind="storage-cache",
                phase="Blocked",
                node="storage-pool",
                capability="result window cache",
            ),
        ]
    )
    return resources


def _decision() -> RuntimeAugmentationDecision:
    state: DecisionState = "selected"
    return RuntimeAugmentationDecision(
        state=state,
        pressure_score=88,
        pressure_reason=["gpu_inference_pressure", "cache_required"],
        candidate_resource_names=[INFERENCE_RESOURCE, STORAGE_RESOURCE],
        selected_resources=_selected_resources(state),
        resulting_augmented_device=RuntimeAugmentationAugmentedDevice(),
        apply_state="observed-only",
        explanation=_explanation(state),
    )


def _workflow_demo() -> RuntimeAugmentationWorkflowDemo:
    return RuntimeAugmentationWorkflowDemo(
        scenario_timeline=_scenario_timeline(),
        steps=[
            RuntimeAugmentationWorkflowStep(
                id="service-request",
                label="Observe AI Service",
                state="completed",
                detail=f"{AI_SERVICE} running on {TARGET_DEVICE}",
            ),
            RuntimeAugmentationWorkflowStep(
                id="pressure-detected",
                label="Detect Resource Pressure",
                state="completed",
                detail="gpu_inference_pressure + cache_required",
            ),
            RuntimeAugmentationWorkflowStep(
                id="candidate-scan",
                label="Scan Candidate Resources",
                state="completed",
                detail="15 registered augmentation candidates scanned",
            ),
            RuntimeAugmentationWorkflowStep(
                id="offload-plan",
                label="Plan Offload Path",
                state="active",
                detail=f"{INFERENCE_RESOURCE} + {STORAGE_RESOURCE} selected",
            ),
            RuntimeAugmentationWorkflowStep(
                id="augmented-device-bind",
                label="Plan Augmented Device Binding",
                state="planned",
                detail="ad-jetorn-inspection-001 planned for target device",
            ),
            RuntimeAugmentationWorkflowStep(
                id="observed-only-complete",
                label="Record Observed Result",
                state="planned",
                detail="no Kubernetes mutation, dashboard-only decision recorded",
            ),
        ],
        offload_path=RuntimeAugmentationOffloadPath(
            source=TARGET_DEVICE,
            inference=INFERENCE_RESOURCE,
            cache=STORAGE_RESOURCE,
            result="ad-jetorn-inspection-001",
        ),
    )


def _scenario_timeline() -> list[RuntimeAugmentationScenarioPhase]:
    return [
        RuntimeAugmentationScenarioPhase(id="normal", label="Normal Observation", active_step_id="service-request", progress_percent=0, summary="The AI service is running on the physical edge device."),
        RuntimeAugmentationScenarioPhase(id="pressure_detected", label="Pressure Detected", active_step_id="pressure-detected", progress_percent=20, summary="GPU inference pressure and result-cache demand were observed."),
        RuntimeAugmentationScenarioPhase(id="candidate_evaluating", label="Candidate Evaluation", active_step_id="candidate-scan", progress_percent=40, summary="The scheduler evaluates 15 registered augmentation candidates by availability."),
        RuntimeAugmentationScenarioPhase(id="offload_planned", label="Offload Planned", active_step_id="offload-plan", progress_percent=60, summary=f"{INFERENCE_RESOURCE} and {STORAGE_RESOURCE} were selected."),
        RuntimeAugmentationScenarioPhase(id="binding_planned", label="Binding Planned", active_step_id="augmented-device-bind", progress_percent=80, summary="Selected resources will be bound as one augmented device plan for the target edge device."),
        RuntimeAugmentationScenarioPhase(id="observed_only_complete", label="Observed Result Recorded", active_step_id="observed-only-complete", progress_percent=100, summary="The observed-only demo result was recorded for dashboard review."),
    ]


def _selected_resources(state: DecisionState) -> list[RuntimeAugmentationSelectedResource]:
    if state not in {"selected", "candidate"}:
        return []
    resources = [
        RuntimeAugmentationSelectedResource(
            role="inference",
            name=INFERENCE_RESOURCE,
            reason="x86 GPU inference endpoint is available",
        ),
    ]
    if state == "selected":
        resources.append(RuntimeAugmentationSelectedResource(role="storage", name=STORAGE_RESOURCE, reason="cache resource is available"))
    return resources


def _explanation(state: DecisionState) -> str:
    return {
        "none": "no service resource request is waiting for augmentation",
        "candidate": "a service resource request exists and matching augmentation resources are available",
        "selected": "a service resource request exists and selected augmentation resources can be bound as one augmented virtual device",
        "blocked": "a service resource request exists but required augmentation resources are not ready",
    }[state]
