from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .adapter_runtime_models import RuntimePlan
from .device_management_models import (
    DeviceInput,
    ManagementModel,
    ProfileSelection,
    ValidationIssue,
)


class RuntimeSelection(ManagementModel):
    mode: Literal["auto", "reuse", "deploy"] = "auto"
    target_node: str = Field(min_length=1, max_length=253)
    hardware_binding_id: str = Field(min_length=1, max_length=128)


class ConnectionOnboardingRequest(ManagementModel):
    adapter_id: str
    runtime: RuntimeSelection
    device: DeviceInput
    profile: ProfileSelection


class ConnectionValidationResult(ManagementModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    runtime_plan: RuntimePlan
    edge_x_plan: dict = Field(default_factory=dict)


ConnectionStatus = Literal[
    "PLANNED",
    "RUNTIME_REQUESTED",
    "RUNTIME_READY",
    "PROFILE_APPLIED",
    "DEVICE_APPLIED",
    "WAITING_EVENT",
    "ACTIVE",
    "COMPENSATING",
    "COMPENSATED",
    "FAILED",
]


class ConnectionOperation(ManagementModel):
    request_id: str
    payload_hash: str = Field(exclude=True)
    status: ConnectionStatus
    adapter_id: str
    runtime_action: Literal["REUSE", "DEPLOY"]
    runtime_name: str
    service_name: str
    device_name: str
    profile_name: str
    metadata_applied: bool = False
    first_event_verified: bool = False
    compensation_status: str | None = None
    actor: str
    started_at: datetime
    updated_at: datetime
    error: str | None = None
