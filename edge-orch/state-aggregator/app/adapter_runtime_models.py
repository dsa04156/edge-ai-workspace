from __future__ import annotations

from typing import Literal

from pydantic import Field

from .device_management_models import ManagementModel


VerificationState = Literal[
    "hardware-verified",
    "template-verified",
    "unverified",
]
RuntimePhase = Literal[
    "PLANNED",
    "DEPLOYING",
    "WORKLOAD_READY",
    "SERVICE_READY",
    "RESTARTING",
    "FAILED",
    "RETIRING",
    "RETIRED",
]


class RuntimePlanRequest(ManagementModel):
    adapter_id: str = Field(min_length=1, max_length=128)
    target_node: str = Field(min_length=1, max_length=253)
    hardware_binding_id: str = Field(min_length=1, max_length=128)
    mode: Literal["auto", "reuse", "deploy"] = "auto"


class RuntimeObservation(ManagementModel):
    runtime_name: str
    adapter_id: str
    template_id: str
    service_name: str
    target_node: str
    hardware_binding_id: str
    management_mode: Literal["external", "controller"]
    management_owner: Literal["argocd", "controller"]
    verification_state: VerificationState
    phase: RuntimePhase
    consumers: int = Field(default=0, ge=0)
    mutable: bool = False
    mutation_enabled: bool = False
    workload_name: str | None = None
    edge_x_service_observed: bool | None = None


class RuntimePlanReason(ManagementModel):
    code: str
    message: str


class RuntimePlan(ManagementModel):
    action: Literal["REUSE", "DEPLOY", "BLOCKED"]
    allowed: bool
    adapter_id: str
    template_id: str | None = None
    runtime_name: str | None = None
    service_name: str | None = None
    target_node: str
    hardware_binding_id: str
    management_mode: Literal["external", "controller"] | None = None
    verification_state: VerificationState
    reasons: list[RuntimePlanReason] = Field(default_factory=list)
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeRequestRef(ManagementModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeCreateRequest(ManagementModel):
    plan: RuntimePlanRequest
    request_ref: RuntimeRequestRef


class RuntimeActionRequest(ManagementModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
