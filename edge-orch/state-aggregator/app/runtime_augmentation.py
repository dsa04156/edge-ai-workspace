from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DecisionState = Literal["none", "candidate", "selected", "blocked"]
CandidateResourceKind = Literal["gpu-inference", "storage-cache", "model-cache"]
CandidateResourcePhase = Literal["Available", "Bound", "Blocked"]
AugmentedDevicePhase = Literal["Planned", "Bound", "Blocked"]
ApplyState = Literal["observed-only", "pending-controller", "applied", "blocked"]
WorkflowStepState = Literal["completed", "active", "planned"]
ScenarioPhaseId = Literal[
    "normal",
    "pressure_detected",
    "candidate_evaluating",
    "offload_planned",
    "binding_planned",
    "observed_only_complete",
]

SCENARIO_ID = "jetson-vision-inspection"
AI_SERVICE = "factory-vision-inspection-ai"
TARGET_DEVICE = "etri-dev0001-jetorn"
INFERENCE_RESOURCE = "vd-x86-gpu-inference"
STORAGE_RESOURCE = "vd-storage-cache"


class RuntimeAugmentationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_resource_total: int
    available: int
    bound: int
    blocked: int


class RuntimeAugmentationSelectedResource(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    name: str
    reason: str


class RuntimeAugmentationCandidateResource(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: CandidateResourceKind
    phase: CandidateResourcePhase = "Available"
    node: str
    capability: str


class RuntimeAugmentationAugmentedDevice(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "ad-jetorn-inspection-001"
    target_device: str = TARGET_DEVICE
    phase: AugmentedDevicePhase = "Planned"
    binding_mode: Literal["planned", "bound"] = "planned"


class RuntimeAugmentationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: DecisionState
    trigger: Literal["service_resource_request"] = "service_resource_request"
    ai_service: str = AI_SERVICE
    scenario: str = SCENARIO_ID
    target_device: str = TARGET_DEVICE
    pressure_score: int = Field(ge=0, le=100)
    pressure_reason: list[str] = Field(default_factory=list)
    candidate_resource_names: list[str] = Field(default_factory=list)
    selected_resources: list[RuntimeAugmentationSelectedResource] = Field(default_factory=list)
    resulting_augmented_device: RuntimeAugmentationAugmentedDevice
    apply_state: ApplyState
    explanation: str


class RuntimeAugmentationWorkflowStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    state: WorkflowStepState
    detail: str


class RuntimeAugmentationScenarioPhase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: ScenarioPhaseId
    label: str
    active_step_id: str
    progress_percent: int = Field(ge=0, le=100)
    summary: str


class RuntimeAugmentationOffloadPath(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    inference: str
    cache: str
    result: str


class RuntimeAugmentationWorkflowDemo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "inspection-resource-augmentation-demo"
    status: Literal["offload_planned"] = "offload_planned"
    automation_trigger: Literal["runtime_metrics_observed"] = "runtime_metrics_observed"
    progress_percent: int = Field(default=80, ge=0, le=100)
    current_step_id: str = "offload-plan"
    operator_summary: str = "GPU 추론과 결과 캐시 오프로딩이 observed-only 바인딩 계획으로 준비됨."
    auto_play: bool = True
    playback_interval_ms: int = Field(default=1600, ge=500, le=10000)
    scenario_timeline: list[RuntimeAugmentationScenarioPhase] = Field(default_factory=list)
    steps: list[RuntimeAugmentationWorkflowStep] = Field(default_factory=list)
    offload_path: RuntimeAugmentationOffloadPath


class RuntimeAugmentationState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    scope: str = "runtime_resource_augmentation_demo_v1"
    scenario_id: str = SCENARIO_ID
    ai_service: str = AI_SERVICE
    summary: RuntimeAugmentationSummary
    candidate_resources: list[RuntimeAugmentationCandidateResource] = Field(default_factory=list)
    decision: RuntimeAugmentationDecision
    workflow_demo: RuntimeAugmentationWorkflowDemo


def build_runtime_augmentation_state() -> RuntimeAugmentationState:
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
        apply_state=_apply_state(state),
        explanation=_explanation(state),
    )


def _workflow_demo() -> RuntimeAugmentationWorkflowDemo:
    return RuntimeAugmentationWorkflowDemo(
        scenario_timeline=_scenario_timeline(),
        steps=[
            RuntimeAugmentationWorkflowStep(
                id="service-request",
                label="AI 서비스 관측",
                state="completed",
                detail=f"{AI_SERVICE} running on {TARGET_DEVICE}",
            ),
            RuntimeAugmentationWorkflowStep(
                id="pressure-detected",
                label="부족 자원 판단",
                state="completed",
                detail="gpu_inference_pressure + cache_required",
            ),
            RuntimeAugmentationWorkflowStep(
                id="candidate-scan",
                label="증강 후보 검색",
                state="completed",
                detail="15 registered augmentation candidates scanned",
            ),
            RuntimeAugmentationWorkflowStep(
                id="offload-plan",
                label="오프로딩 계획",
                state="active",
                detail=f"{INFERENCE_RESOURCE} + {STORAGE_RESOURCE} selected",
            ),
            RuntimeAugmentationWorkflowStep(
                id="augmented-device-bind",
                label="가상디바이스 바인딩",
                state="planned",
                detail="ad-jetorn-inspection-001 planned for target device",
            ),
            RuntimeAugmentationWorkflowStep(
                id="observed-only-complete",
                label="관측 결과 고정",
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
        RuntimeAugmentationScenarioPhase(
            id="normal",
            label="정상 관측",
            active_step_id="service-request",
            progress_percent=0,
            summary="AI 서비스가 물리 엣지 디바이스에서 정상 실행 중입니다.",
        ),
        RuntimeAugmentationScenarioPhase(
            id="pressure_detected",
            label="부하 감지",
            active_step_id="pressure-detected",
            progress_percent=20,
            summary="GPU 추론 압력과 결과 캐시 요구가 관측되었습니다.",
        ),
        RuntimeAugmentationScenarioPhase(
            id="candidate_evaluating",
            label="후보 평가",
            active_step_id="candidate-scan",
            progress_percent=40,
            summary="등록된 증강 자원 후보 15개를 가용성 기준으로 평가합니다.",
        ),
        RuntimeAugmentationScenarioPhase(
            id="offload_planned",
            label="오프로딩 계획",
            active_step_id="offload-plan",
            progress_percent=60,
            summary=f"{INFERENCE_RESOURCE}와 {STORAGE_RESOURCE}를 선택했습니다.",
        ),
        RuntimeAugmentationScenarioPhase(
            id="binding_planned",
            label="바인딩 계획",
            active_step_id="augmented-device-bind",
            progress_percent=80,
            summary="선택 자원을 물리 디바이스에 종속된 가상디바이스로 묶을 계획입니다.",
        ),
        RuntimeAugmentationScenarioPhase(
            id="observed_only_complete",
            label="관측 완료",
            active_step_id="observed-only-complete",
            progress_percent=100,
            summary="observed-only 데모 결과를 대시보드에 기록했습니다.",
        ),
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
        resources.append(
            RuntimeAugmentationSelectedResource(
                role="storage",
                name=STORAGE_RESOURCE,
                reason="cache resource is available",
            )
        )
    return resources


def _apply_state(state: DecisionState) -> ApplyState:
    if state == "blocked":
        return "blocked"
    return "observed-only"


def _explanation(state: DecisionState) -> str:
    return {
        "none": "no service resource request is waiting for augmentation",
        "candidate": "a service resource request exists and matching augmentation resources are available",
        "selected": "a service resource request exists and selected augmentation resources can be bound as one augmented virtual device",
        "blocked": "a service resource request exists but required augmentation resources are not ready",
    }[state]
