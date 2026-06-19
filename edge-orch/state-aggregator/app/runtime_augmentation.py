from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RecommendationState = Literal["none", "candidate", "selected", "blocked"]
ApplyState = Literal["observed-only", "pending-controller", "applied", "blocked"]

SCENARIO_ID = "jetson-vision-inspection"
AI_SERVICE = "factory-vision-inspection-ai"
TARGET_DEVICE = "etri-dev0001-jetorn"
INFERENCE_RESOURCE = "vd-x86-gpu-inference"
STORAGE_RESOURCE = "vd-storage-cache"


class RuntimeAugmentationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    none: int
    candidate: int
    selected: int
    blocked: int


class RuntimeAugmentationSelectedResource(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    name: str
    reason: str


class RuntimeAugmentationRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    virtual_device: str
    ai_service: str = AI_SERVICE
    scenario: str = SCENARIO_ID
    target_device: str = TARGET_DEVICE
    workload: str
    recommendation: RecommendationState
    pressure_score: int = Field(ge=0, le=100)
    pressure_reason: list[str] = Field(default_factory=list)
    selected_resources: list[RuntimeAugmentationSelectedResource] = Field(default_factory=list)
    apply_state: ApplyState
    explanation: str


class RuntimeAugmentationState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    scope: str = "runtime_resource_augmentation_demo_v1"
    scenario_id: str = SCENARIO_ID
    ai_service: str = AI_SERVICE
    summary: RuntimeAugmentationSummary
    recommendations: list[RuntimeAugmentationRecommendation] = Field(default_factory=list)


def build_runtime_augmentation_state() -> RuntimeAugmentationState:
    recommendations = [
        _recommendation(index, state)
        for index, state in [
            *[(index, "selected") for index in range(1, 6)],
            *[(index, "candidate") for index in range(6, 10)],
            *[(index, "blocked") for index in range(10, 12)],
            *[(index, "none") for index in range(12, 16)],
        ]
    ]
    return RuntimeAugmentationState(
        generated_at=datetime.now(timezone.utc),
        summary=RuntimeAugmentationSummary(
            total=len(recommendations),
            none=sum(1 for item in recommendations if item.recommendation == "none"),
            candidate=sum(1 for item in recommendations if item.recommendation == "candidate"),
            selected=sum(1 for item in recommendations if item.recommendation == "selected"),
            blocked=sum(1 for item in recommendations if item.recommendation == "blocked"),
        ),
        recommendations=recommendations,
    )


def _recommendation(index: int, state: RecommendationState) -> RuntimeAugmentationRecommendation:
    return RuntimeAugmentationRecommendation(
        virtual_device=f"vd-inspection-{index:03d}",
        workload=AI_SERVICE,
        recommendation=state,
        pressure_score=_pressure_score(index=index, state=state),
        pressure_reason=_pressure_reason(state),
        selected_resources=_selected_resources(state),
        apply_state=_apply_state(state),
        explanation=_explanation(state),
    )


def _pressure_score(*, index: int, state: RecommendationState) -> int:
    base = {
        "selected": 86,
        "candidate": 72,
        "blocked": 91,
        "none": 24,
    }[state]
    return min(100, base + (index % 4))


def _pressure_reason(state: RecommendationState) -> list[str]:
    if state == "none":
        return []
    if state == "blocked":
        return ["gpu_inference_pressure", "cache_required", "augmentation_resource_not_ready"]
    if state == "candidate":
        return ["gpu_inference_pressure", "candidate_resource_available"]
    return ["gpu_inference_pressure", "cache_required"]


def _selected_resources(state: RecommendationState) -> list[RuntimeAugmentationSelectedResource]:
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


def _apply_state(state: RecommendationState) -> ApplyState:
    if state == "blocked":
        return "blocked"
    return "observed-only"


def _explanation(state: RecommendationState) -> str:
    return {
        "none": "runtime pressure is below the augmentation threshold",
        "candidate": "pressure is observed and at least one augmentation candidate is available",
        "selected": "pressure is observed and both inference/cache resources are selected",
        "blocked": "pressure is observed but one or more required augmentation resources are not ready",
    }[state]
