from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item.capitalize() for item in tail)


class ControllerModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


VerificationState = Literal[
    "hardware-verified",
    "template-verified",
    "unverified",
]
ManagementMode = Literal["external", "controller"]
ManagementOwner = Literal["argocd", "controller"]
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


class HardwareBindingTemplate(ControllerModel):
    binding_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    display_name: str = Field(min_length=1, max_length=255)
    node_name: str = Field(min_length=1, max_length=253)
    host_device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/,:@+~-]+$",
    )
    container_device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/,:@+~-]+$",
    )
    device_type: Literal["CharDevice", "BlockDevice"] | None = None
    requires_privileged: bool = False

    @model_validator(mode="after")
    def require_complete_device_mount(self) -> "HardwareBindingTemplate":
        values = (
            self.host_device_path,
            self.container_device_path,
            self.device_type,
        )
        if any(item is not None for item in values) and not all(
            item is not None for item in values
        ):
            raise ValueError("hardware device mount fields must be provided together")
        return self


class ExternalRuntimeDefinition(ControllerModel):
    runtime_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    service_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    workload_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    target_node: str = Field(min_length=1, max_length=253)
    hardware_binding_id: str
    hardware_binding_ids: list[str] = Field(default_factory=list)
    management_owner: Literal["argocd"] = "argocd"

    @model_validator(mode="after")
    def normalize_hardware_bindings(self) -> "ExternalRuntimeDefinition":
        if not self.hardware_binding_ids:
            self.hardware_binding_ids = [self.hardware_binding_id]
        if self.hardware_binding_id not in self.hardware_binding_ids:
            raise ValueError("primary hardware binding must be in hardwareBindingIds")
        if len(self.hardware_binding_ids) != len(set(self.hardware_binding_ids)):
            raise ValueError("external runtime hardware bindings must be unique")
        return self


class RuntimeTemplate(ControllerModel):
    template_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    adapter_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    display_name: str = Field(min_length=1, max_length=255)
    protocol_name: str = Field(min_length=1, max_length=128)
    verification_state: VerificationState
    deployment_enabled: bool = False
    image: str | None = None
    service_port: int = Field(ge=1024, le=65535)
    hardware_bindings: list[HardwareBindingTemplate] = Field(default_factory=list)
    external_runtimes: list[ExternalRuntimeDefinition] = Field(default_factory=list)
    hidden: bool = False

    @model_validator(mode="after")
    def enforce_template_safety(self) -> "RuntimeTemplate":
        if self.image is not None and re.fullmatch(
            r"[A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}",
            self.image,
        ) is None:
            raise ValueError("runtime image must use an immutable sha256 digest")
        if self.deployment_enabled:
            if self.verification_state == "unverified":
                raise ValueError("unverified template cannot enable deployment")
            if self.image is None:
                raise ValueError("deployable template requires a digest-pinned image")
            if not self.hardware_bindings:
                raise ValueError("deployable template requires a hardware binding")
        binding_ids = [item.binding_id for item in self.hardware_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("template hardware binding IDs must be unique")
        known_bindings = set(binding_ids)
        binding_nodes = {
            binding.binding_id: binding.node_name for binding in self.hardware_bindings
        }
        for runtime in self.external_runtimes:
            if not set(runtime.hardware_binding_ids).issubset(known_bindings):
                raise ValueError("external runtime references an unknown hardware binding")
            if any(
                binding_nodes[binding_id] != runtime.target_node
                for binding_id in runtime.hardware_binding_ids
            ):
                raise ValueError(
                    "external runtime hardware bindings must target the runtime node"
                )
        return self


class RuntimeCatalogDocument(ControllerModel):
    version: int = Field(default=1, ge=1)
    namespace: Literal["edgex-edge"] = "edgex-edge"
    templates: list[RuntimeTemplate]


class RuntimePlanRequest(ControllerModel):
    adapter_id: str = Field(min_length=1, max_length=128)
    target_node: str = Field(min_length=1, max_length=253)
    hardware_binding_id: str = Field(min_length=1, max_length=128)
    mode: Literal["auto", "reuse", "deploy"] = "auto"


class RuntimeObservation(ControllerModel):
    runtime_name: str
    adapter_id: str
    template_id: str
    service_name: str
    target_node: str
    hardware_binding_id: str
    hardware_binding_ids: list[str] = Field(default_factory=list)
    management_mode: ManagementMode
    management_owner: ManagementOwner
    verification_state: VerificationState
    phase: RuntimePhase
    consumers: int = Field(default=0, ge=0)
    mutable: bool = False
    workload_name: str | None = None
    image: str | None = None

    @model_validator(mode="after")
    def normalize_hardware_bindings(self) -> "RuntimeObservation":
        if not self.hardware_binding_ids:
            self.hardware_binding_ids = [self.hardware_binding_id]
        if self.hardware_binding_id not in self.hardware_binding_ids:
            raise ValueError("primary hardware binding must be in hardwareBindingIds")
        if len(self.hardware_binding_ids) != len(set(self.hardware_binding_ids)):
            raise ValueError("runtime hardware bindings must be unique")
        return self


class PlanReason(ControllerModel):
    code: str
    message: str


class RuntimePlan(ControllerModel):
    action: Literal["REUSE", "DEPLOY", "BLOCKED"]
    allowed: bool
    adapter_id: str
    template_id: str | None = None
    runtime_name: str | None = None
    service_name: str | None = None
    target_node: str
    hardware_binding_id: str
    management_mode: ManagementMode | None = None
    verification_state: VerificationState
    reasons: list[PlanReason] = Field(default_factory=list)
    plan_hash: str


class RuntimeApplyRequest(ControllerModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeCreateRequest(ControllerModel):
    plan: RuntimePlanRequest
    request_ref: RuntimeApplyRequest


class RuntimeActionRequest(ControllerModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
