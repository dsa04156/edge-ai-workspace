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
    reason: str | None = None
    fields: list[CatalogField] = Field(default_factory=list)
    profile_capabilities: ProfileCapabilities | None = None


class ValidationResult(ManagementModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)


class ManagementOperation(ManagementModel):
    request_id: str
    payload_hash: str
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
