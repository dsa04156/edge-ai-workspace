from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .device_management_models import ManagementModel


VerificationState = Literal[
    "hardware-verified",
    "template-verified",
    "unverified",
]
RuntimePurpose = Literal["operational", "development-fixture"]
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
    hardware_binding_ids: list[str] = Field(default_factory=list)
    management_mode: Literal["external", "controller"]
    management_owner: Literal["argocd", "controller"]
    purpose: RuntimePurpose = "operational"
    verification_state: VerificationState
    phase: RuntimePhase
    consumers: int = Field(default=0, ge=0)
    mutable: bool = False
    mutation_enabled: bool = False
    workload_name: str | None = None
    image: str | None = None
    edge_x_service_observed: bool | None = None

    @model_validator(mode="after")
    def normalize_hardware_bindings(self) -> "RuntimeObservation":
        if not self.hardware_binding_ids:
            self.hardware_binding_ids = [self.hardware_binding_id]
        if self.hardware_binding_id not in self.hardware_binding_ids:
            raise ValueError("primary hardware binding must be in hardwareBindingIds")
        if len(self.hardware_binding_ids) != len(set(self.hardware_binding_ids)):
            raise ValueError("runtime hardware bindings must be unique")
        return self


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
