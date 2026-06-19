from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DecisionState = Literal["none", "candidate", "selected", "blocked"]
VirtualDeviceState = Literal["waiting", "running", "reserved"]
ApplyState = Literal["observed-only", "pending-controller", "applied", "blocked"]

SCENARIO_ID = "jetson-vision-inspection"
AI_SERVICE = "factory-vision-inspection-ai"
TARGET_DEVICE = "etri-dev0001-jetorn"
INFERENCE_RESOURCE = "vd-x86-gpu-inference"
STORAGE_RESOURCE = "vd-storage-cache"


class RuntimeAugmentationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    virtual_device_total: int
    waiting: int
    running: int
    reserved: int


class RuntimeAugmentationSelectedResource(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    name: str
    reason: str


class RuntimeAugmentationVirtualDevice(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    state: VirtualDeviceState = "waiting"
    capability: str = "vision-inference-slot"
    node: str = "virtual-pool"
    activation: Literal["on_request"] = "on_request"


class RuntimeAugmentationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: DecisionState
    trigger: Literal["service_resource_request"] = "service_resource_request"
    ai_service: str = AI_SERVICE
    scenario: str = SCENARIO_ID
    target_device: str = TARGET_DEVICE
    pressure_score: int = Field(ge=0, le=100)
    pressure_reason: list[str] = Field(default_factory=list)
    selected_resources: list[RuntimeAugmentationSelectedResource] = Field(default_factory=list)
    virtual_device_candidates: list[str] = Field(default_factory=list)
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
    virtual_devices: list[RuntimeAugmentationVirtualDevice] = Field(default_factory=list)
    decision: RuntimeAugmentationDecision


def build_runtime_augmentation_state() -> RuntimeAugmentationState:
    virtual_devices = [_virtual_device(index) for index in range(1, 16)]
    return RuntimeAugmentationState(
        generated_at=datetime.now(timezone.utc),
        summary=RuntimeAugmentationSummary(
            virtual_device_total=len(virtual_devices),
            waiting=sum(1 for item in virtual_devices if item.state == "waiting"),
            running=sum(1 for item in virtual_devices if item.state == "running"),
            reserved=sum(1 for item in virtual_devices if item.state == "reserved"),
        ),
        virtual_devices=virtual_devices,
        decision=_decision(),
    )


def _virtual_device(index: int) -> RuntimeAugmentationVirtualDevice:
    return RuntimeAugmentationVirtualDevice(name=f"vd-inspection-{index:03d}")


def _decision() -> RuntimeAugmentationDecision:
    state: DecisionState = "selected"
    return RuntimeAugmentationDecision(
        state=state,
        pressure_score=88,
        pressure_reason=["gpu_inference_pressure", "cache_required"],
        selected_resources=_selected_resources(state),
        virtual_device_candidates=[
            "vd-inspection-001",
            "vd-inspection-002",
            "vd-inspection-003",
        ],
        apply_state=_apply_state(state),
        explanation=_explanation(state),
    )


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
        "candidate": "a service resource request exists and matching virtual devices are waiting",
        "selected": "a service resource request exists and waiting virtual devices can be activated with inference/cache resources",
        "blocked": "a service resource request exists but required augmentation resources are not ready",
    }[state]
