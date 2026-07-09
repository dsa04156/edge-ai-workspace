from __future__ import annotations

from datetime import datetime
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
    status: Literal["observed", "offload_planned"] = "offload_planned"
    automation_trigger: Literal["runtime_metrics_observed"] = "runtime_metrics_observed"
    progress_percent: int = Field(default=80, ge=0, le=100)
    current_step_id: str = "offload-plan"
    operator_summary: str = "GPU inference and result-cache offload are ready as an observed-only binding plan."
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
