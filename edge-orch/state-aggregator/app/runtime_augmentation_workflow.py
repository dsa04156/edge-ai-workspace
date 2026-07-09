from __future__ import annotations

from .runtime_augmentation_models import (
    TARGET_DEVICE,
    DecisionState,
    RuntimeAugmentationDecision,
    RuntimeAugmentationOffloadPath,
    RuntimeAugmentationScenarioPhase,
    RuntimeAugmentationWorkflowDemo,
    RuntimeAugmentationWorkflowStep,
)


def build_runtime_workflow_demo(decision: RuntimeAugmentationDecision, candidate_total: int) -> RuntimeAugmentationWorkflowDemo:
    selected_names = [resource.name for resource in decision.selected_resources]
    workflow = RuntimeAugmentationWorkflowDemo(
        progress_percent=_progress(decision.state),
        current_step_id=_current_step_id(decision.state),
        operator_summary=decision.explanation,
        scenario_timeline=_scenario_timeline(decision),
        steps=_workflow_steps(decision, candidate_total),
        auto_play=decision.state != "none",
        offload_path=RuntimeAugmentationOffloadPath(
            source=TARGET_DEVICE,
            inference=selected_names[0] if selected_names else "inference pending",
            cache=selected_names[1] if len(selected_names) > 1 else "cache pending",
            result=decision.resulting_augmented_device.name,
        ),
    )
    if decision.state == "none":
        return workflow.model_copy(update={"status": "observed"})
    return workflow


def _workflow_steps(decision: RuntimeAugmentationDecision, candidate_total: int) -> list[RuntimeAugmentationWorkflowStep]:
    pressure_state = "completed" if decision.state != "none" else "planned"
    scan_state = "completed" if decision.state in {"selected", "blocked", "candidate"} else "planned"
    plan_state = "active" if decision.state in {"selected", "candidate"} else "planned"
    return [
        RuntimeAugmentationWorkflowStep(id="service-request", label="Observe AI Service", state="completed", detail=f"{decision.ai_service} observation loaded"),
        RuntimeAugmentationWorkflowStep(id="pressure-detected", label="Detect Resource Pressure", state=pressure_state, detail=", ".join(decision.pressure_reason) or "no pressure observed"),
        RuntimeAugmentationWorkflowStep(id="candidate-scan", label="Scan Candidate Resources", state=scan_state, detail=f"{candidate_total} registered augmentation candidates scanned"),
        RuntimeAugmentationWorkflowStep(id="offload-plan", label="Plan Offload Path", state=plan_state, detail=", ".join(decision.candidate_resource_names) or "no resource selected"),
        RuntimeAugmentationWorkflowStep(id="augmented-device-bind", label="Plan Augmented Device Binding", state="planned", detail=f"{decision.resulting_augmented_device.name} status is {decision.resulting_augmented_device.phase}"),
        RuntimeAugmentationWorkflowStep(id="observed-only-complete", label="Record Observed Result", state="planned", detail="no Kubernetes mutation, dashboard-only decision recorded"),
    ]


def _scenario_timeline(decision: RuntimeAugmentationDecision) -> list[RuntimeAugmentationScenarioPhase]:
    phases = [
        RuntimeAugmentationScenarioPhase(id="normal", label="Normal Observation", active_step_id="service-request", progress_percent=0, summary="The AI service observation is loaded."),
        RuntimeAugmentationScenarioPhase(id="pressure_detected", label="Pressure Detected", active_step_id="pressure-detected", progress_percent=20, summary=", ".join(decision.pressure_reason) or "No pressure is observed."),
        RuntimeAugmentationScenarioPhase(id="candidate_evaluating", label="Candidate Evaluation", active_step_id="candidate-scan", progress_percent=40, summary="Registered augmentation resources are evaluated by readiness."),
        RuntimeAugmentationScenarioPhase(id="offload_planned", label="Offload Planned", active_step_id="offload-plan", progress_percent=60, summary=decision.explanation),
        RuntimeAugmentationScenarioPhase(id="binding_planned", label="Binding Planned", active_step_id="augmented-device-bind", progress_percent=80, summary="Selected resources remain observed-only until a controller applies them."),
        RuntimeAugmentationScenarioPhase(id="observed_only_complete", label="Observed Result Recorded", active_step_id="observed-only-complete", progress_percent=100, summary="The read-only dashboard result is recorded for operator review."),
    ]
    if decision.state == "none":
        return phases[:1]
    return phases


def _current_step_id(state: DecisionState) -> str:
    return {"none": "service-request", "candidate": "candidate-scan", "selected": "offload-plan", "blocked": "offload-plan"}[state]


def _progress(state: DecisionState) -> int:
    return {"none": 0, "candidate": 40, "selected": 80, "blocked": 60}[state]
