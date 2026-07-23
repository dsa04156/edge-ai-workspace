from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item.capitalize() for item in tail)


class ManagementModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class CatalogField(ManagementModel):
    name: str
    label: str
    type: Literal["string", "integer", "enum"]
    required: bool = True
    secret: bool = False
    default: Any | None = None
    const: Any | None = None
    options: list[Any] = Field(default_factory=list)
    pattern: str | None = None


class DeviceResourceProperties(ManagementModel):
    value_type: Literal[
        "Bool",
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "Uint8",
        "Uint16",
        "Uint32",
        "Uint64",
        "Float32",
        "Float64",
        "String",
        "Binary",
        "Object",
    ]
    read_write: Literal["R", "W", "RW"] = "R"
    units: str | None = None


class DeviceResourceTemplate(ManagementModel):
    name: str
    description: str = ""
    is_hidden: bool = False
    properties: DeviceResourceProperties


class ResourceOperationTemplate(ManagementModel):
    device_resource: str


class DeviceCommandTemplate(ManagementModel):
    name: str
    read_write: Literal["R", "W", "RW"] = "R"
    is_hidden: bool = False
    resource_operations: list[ResourceOperationTemplate]


class ProfileTemplate(ManagementModel):
    selector_value: str
    device_resources: list[DeviceResourceTemplate]
    device_commands: list[DeviceCommandTemplate] = Field(default_factory=list)


class ProfileCapabilities(ManagementModel):
    selector_field: str
    value_types: list[str]
    read_write: list[Literal["R", "W", "RW"]]
    templates: list[ProfileTemplate]


class HardwareBinding(ManagementModel):
    binding_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    display_name: str = Field(min_length=1, max_length=255)
    node_name: str = Field(min_length=1, max_length=253)
    device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/~-]+$",
    )
    protocol_properties: dict[str, Any] = Field(default_factory=dict)


class ReusePolicy(ManagementModel):
    multi_device: bool = True
    binding_fields: list[str] = Field(default_factory=list)
    route_fields: list[str] = Field(default_factory=list)
    max_devices: int | None = Field(default=None, ge=1, le=100000)

    @model_validator(mode="after")
    def require_unique_fields(self) -> "ReusePolicy":
        fields = [*self.binding_fields, *self.route_fields]
        if len(fields) != len(set(fields)):
            raise ValueError("reuse policy fields must be unique")
        return self


class RuntimeCapability(ManagementModel):
    mode: Literal["external", "managed-template", "unavailable"] = "unavailable"
    management_owner: Literal["argocd", "controller", "none"] = "none"
    verification_state: Literal[
        "hardware-verified",
        "template-verified",
        "unverified",
    ] = "unverified"
    template_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    deployment_enabled: bool = False
    hardware_bindings: list[HardwareBinding] = Field(default_factory=list)
    reuse_policy: ReusePolicy = Field(default_factory=ReusePolicy)

    @model_validator(mode="after")
    def enforce_deployment_safety(self) -> "RuntimeCapability":
        if self.verification_state == "unverified" and self.deployment_enabled:
            raise ValueError("unverified runtime cannot enable deployment")
        if self.deployment_enabled and self.template_id is None:
            raise ValueError("deployable runtime requires templateId")
        if self.mode == "unavailable" and self.deployment_enabled:
            raise ValueError("unavailable runtime cannot enable deployment")
        binding_ids = [item.binding_id for item in self.hardware_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("hardware binding IDs must be unique")
        return self


class AdapterDefinition(ManagementModel):
    adapter_id: str
    display_name: str
    service_name: str | None = None
    protocol_name: str
    node_name: str | None = None
    declared_status: Literal["installed", "unsupported"]
    reason: str | None = None
    fields: list[CatalogField] = Field(default_factory=list)
    profile_capabilities: ProfileCapabilities | None = None
    runtime: RuntimeCapability = Field(default_factory=RuntimeCapability)

    @model_validator(mode="after")
    def enforce_binding_contract(self) -> "AdapterDefinition":
        field_names = {item.name for item in self.fields}
        policy = self.runtime.reuse_policy
        policy_fields = [*policy.binding_fields, *policy.route_fields]
        unknown = sorted(set(policy_fields) - field_names)
        if unknown:
            raise ValueError(
                f"reuse policy references unknown protocol fields: {', '.join(unknown)}"
            )
        binding_field_set = set(policy.binding_fields)
        binding_identities: set[tuple[tuple[str, str], ...]] = set()
        for binding in self.runtime.hardware_bindings:
            property_names = set(binding.protocol_properties)
            if property_names != binding_field_set:
                raise ValueError(
                    f"hardware binding {binding.binding_id!r} protocol properties "
                    "must exactly match reuse policy binding fields"
                )
            identity = tuple(
                (name, repr(binding.protocol_properties[name]))
                for name in policy.binding_fields
            )
            if identity in binding_identities:
                raise ValueError("hardware binding protocol identities must be unique")
            binding_identities.add(identity)
        return self


class AdapterCatalogDocument(ManagementModel):
    version: int = 1
    adapters: list[AdapterDefinition]


class ValidationIssue(ManagementModel):
    code: str
    message: str
    field: str | None = None


EdgeXScalar = str | int | float | bool | None


class DeviceInput(ManagementModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._~-]+$")
    description: str = Field(default="", max_length=1000)
    labels: list[str] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)
    protocol_properties: dict[str, Any]
    admin_state: Literal["LOCKED", "UNLOCKED"] = "UNLOCKED"


class ProfileSelection(ManagementModel):
    mode: Literal["existing", "create"]
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._~-]+$")
    description: str | None = Field(default=None, max_length=1000)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_create_metadata(self) -> "ProfileSelection":
        if self.mode == "create":
            missing = [
                field_name
                for field_name in ("description", "manufacturer", "model")
                if (value := getattr(self, field_name)) is None or not value.strip()
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} are required when profile mode is create"
                )
        return self


class DeviceOnboardingRequest(ManagementModel):
    adapter_id: str
    hardware_binding_id: str | None = Field(default=None, min_length=1, max_length=128)
    device: DeviceInput
    profile: ProfileSelection


class DevicePatchRequest(ManagementModel):
    description: str | None = Field(default=None, max_length=1000)
    labels: list[str] | None = None
    tags: dict[str, Any] | None = None
    protocol_properties: dict[str, Any] | None = None
    admin_state: Literal["LOCKED", "UNLOCKED"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "DevicePatchRequest":
        if not self.model_fields_set:
            raise ValueError("at least one allowlisted field is required")
        return self


class AdapterStatusView(ManagementModel):
    adapter_id: str
    display_name: str
    service_name: str | None = None
    protocol_name: str
    node_name: str | None = None
    status: Literal["installed", "unavailable", "unsupported"]
    mutation_enabled: bool = False
    reason: str | None = None
    fields: list[CatalogField] = Field(default_factory=list)
    profile_capabilities: ProfileCapabilities | None = None
    runtime: RuntimeCapability = Field(default_factory=RuntimeCapability)


class ValidationResult(ManagementModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)


class ManagementOperation(ManagementModel):
    request_id: str
    payload_hash: str = Field(exclude=True)
    action: Literal["create", "patch"]
    device_name: str
    profile_name: str
    status: Literal["metadata_applied", "waiting_for_event", "verified", "failed"]
    metadata_applied: bool = False
    first_event_verified: bool = False
    created_profile: bool = False
    actor: str
    started_at: datetime
    updated_at: datetime
    error: str | None = None


def matches_pattern(pattern: str | None, value: str) -> bool:
    return pattern is None or re.fullmatch(pattern, value) is not None
