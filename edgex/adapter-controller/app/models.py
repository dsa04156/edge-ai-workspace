from __future__ import annotations

import ipaddress
import re
from typing import Any, Literal

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
RuntimeSettingScalar = str | int | float | bool


class RuntimeSettingDefinition(ControllerModel):
    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9]*$",
    )
    type: Literal["string", "integer", "enum", "url"]
    required: bool = True
    default: RuntimeSettingScalar | None = None
    options: list[RuntimeSettingScalar] = Field(default_factory=list, max_length=32)
    pattern: str | None = Field(default=None, max_length=512)
    allowed_schemes: list[str] = Field(default_factory=list, max_length=8)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=64)
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=32)
    default_port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_setting_contract(self) -> "RuntimeSettingDefinition":
        if self.type == "url":
            if not self.allowed_schemes:
                raise ValueError("URL runtime setting requires allowedSchemes")
            if not self.allowed_hosts and not self.allowed_cidrs:
                raise ValueError(
                    "URL runtime setting requires an endpoint allowlist"
                )
            if self.options or self.pattern:
                raise ValueError(
                    "URL runtime setting cannot use options or pattern"
                )
            self.allowed_schemes = [
                item.casefold() for item in self.allowed_schemes
            ]
            self.allowed_hosts = [
                item.casefold() for item in self.allowed_hosts
            ]
            for cidr in self.allowed_cidrs:
                ipaddress.ip_network(cidr, strict=False)
        elif self.allowed_schemes or self.allowed_hosts or self.allowed_cidrs:
            raise ValueError(
                "endpoint allowlists are only valid for URL runtime settings"
            )
        if self.type == "enum" and not self.options:
            raise ValueError("enum runtime setting requires options")
        if self.type != "enum" and self.options:
            raise ValueError("runtime setting options require type=enum")
        if self.default is not None:
            from .runtime_settings import normalize_runtime_setting_value

            normalize_runtime_setting_value(self, self.default)
        return self


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


class RuntimeNetworkEgress(ControllerModel):
    namespace: str | None = Field(
        default=None,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    pod_selector: dict[str, str] = Field(default_factory=dict, max_length=16)
    cidr: str | None = Field(default=None, max_length=64)
    ports: list[int] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def enforce_bounded_destination(self) -> "RuntimeNetworkEgress":
        selector_mode = self.namespace is not None or bool(self.pod_selector)
        cidr_mode = self.cidr is not None
        if selector_mode == cidr_mode:
            raise ValueError(
                "runtime egress must use either namespace/pod selector or CIDR"
            )
        if selector_mode and (
            self.namespace is None or not self.pod_selector
        ):
            raise ValueError(
                "runtime selector egress requires namespace and podSelector"
            )
        if any(
            not key
            or not value
            or len(key) > 253
            or len(value) > 253
            for key, value in self.pod_selector.items()
        ):
            raise ValueError("runtime egress podSelector is invalid")
        if cidr_mode:
            network = ipaddress.ip_network(str(self.cidr), strict=False)
            if network.prefixlen == 0:
                raise ValueError("runtime egress cannot allow the entire Internet")
            self.cidr = str(network)
        if len(self.ports) != len(set(self.ports)):
            raise ValueError("runtime egress ports must be unique")
        if any(port < 1 or port > 65535 for port in self.ports):
            raise ValueError("runtime egress port is outside 1..65535")
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
    purpose: RuntimePurpose = "operational"
    verification_state: VerificationState
    deployment_enabled: bool = False
    image: str | None = None
    service_port: int = Field(ge=1024, le=65535)
    edge_x_service_base_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    hardware_bindings: list[HardwareBindingTemplate] = Field(default_factory=list)
    external_runtimes: list[ExternalRuntimeDefinition] = Field(default_factory=list)
    network_egress: list[RuntimeNetworkEgress] = Field(default_factory=list)
    runtime_config_renderer: Literal["none", "mqtt-broker-v1"] = "none"
    runtime_settings: list[RuntimeSettingDefinition] = Field(default_factory=list)
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
        setting_names = [item.name for item in self.runtime_settings]
        if len(setting_names) != len(set(setting_names)):
            raise ValueError("runtime setting names must be unique")
        if self.runtime_config_renderer == "none" and self.runtime_settings:
            raise ValueError(
                "runtime settings require an approved config renderer"
            )
        if (
            self.runtime_config_renderer == "mqtt-broker-v1"
            and self.protocol_name.casefold() != "mqtt"
        ):
            raise ValueError("MQTT config renderer requires protocolName=mqtt")
        return self

    def edge_x_service_instance(self, runtime_name: str) -> str | None:
        if self.edge_x_service_base_name is None:
            return None
        instance = runtime_name.rsplit("-", 1)[-1]
        if re.fullmatch(r"[a-z0-9]{10}", instance) is None:
            raise ValueError(
                "EdgeX instance runtime name must end with a 10-character ID"
            )
        return instance

    def edge_x_service_identity(self, runtime_name: str) -> str:
        instance = self.edge_x_service_instance(runtime_name)
        if instance is None:
            return runtime_name
        return f"{self.edge_x_service_base_name}_{instance}"


class RuntimeCatalogDocument(ControllerModel):
    version: int = Field(default=1, ge=1)
    namespace: Literal["edgex-edge"] = "edgex-edge"
    templates: list[RuntimeTemplate]


class RuntimePlanRequest(ControllerModel):
    adapter_id: str = Field(min_length=1, max_length=128)
    target_node: str = Field(min_length=1, max_length=253)
    hardware_binding_id: str = Field(min_length=1, max_length=128)
    mode: Literal["auto", "reuse", "deploy"] = "auto"
    settings: dict[str, RuntimeSettingScalar] = Field(
        default_factory=dict,
        max_length=32,
    )


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
    purpose: RuntimePurpose = "operational"
    verification_state: VerificationState
    phase: RuntimePhase
    consumers: int = Field(default=0, ge=0)
    mutable: bool = False
    workload_name: str | None = None
    image: str | None = None
    settings_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

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
    settings_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
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
