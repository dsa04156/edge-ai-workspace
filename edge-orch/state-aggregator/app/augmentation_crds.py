from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, ConfigDict, Field

from .virtual_resources import JsonMap, JsonValue

GROUP = "augmentation.edge-ai.io"
VERSION = "v1alpha1"
RESOURCE_PLURAL = "augmentationresources"
BINDING_PLURAL = "deviceaugmentations"

logger = logging.getLogger(__name__)


class CustomObjectsReader(Protocol):
    def list_cluster_custom_object(self, *, group: str, version: str, plural: str) -> JsonMap: ...

    def list_namespaced_custom_object(self, *, group: str, version: str, namespace: str, plural: str) -> JsonMap: ...


class CrdCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    status: str
    reason: str | None = None
    message: str | None = None
    last_transition_time: str | None = None


class AugmentationResourceCrd(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    resource_type: str
    node: str
    capabilities: list[str] = Field(default_factory=list)
    stage_types: list[str] = Field(default_factory=list)
    phase: str = "Unknown"
    observed_instances: int = 0
    free_instances: int = 0
    allocated_instances: int = 0
    binding_state: str = "unknown"
    endpoint_ready: bool = False
    reason: str | None = None
    conditions: list[CrdCondition] = Field(default_factory=list)


class SelectedAugmentationResource(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    name: str
    phase: str | None = None
    node: str | None = None
    observed_instances: int | None = None
    binding_state: str | None = None
    endpoint_ready: bool | None = None


class DeviceAugmentationCrd(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    namespace: str
    target_device_kind: str
    target_device_name: str
    phase: str = "Unknown"
    required_capabilities: list[str] = Field(default_factory=list)
    bound_resources: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    selected_resources: list[SelectedAugmentationResource] = Field(default_factory=list)
    workload_policy: dict[str, str | bool] = Field(default_factory=dict)
    reason: str | None = None
    conditions: list[CrdCondition] = Field(default_factory=list)


class AugmentationResourceCrdState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: str = "read_only"
    scope: str = "resource_augmentation_crds"
    observation_error: str | None = None
    resources: list[AugmentationResourceCrd] = Field(default_factory=list)


class DeviceAugmentationCrdState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: str = "read_only"
    scope: str = "device_augmentation_crds"
    namespace: str
    observation_error: str | None = None
    device_augmentations: list[DeviceAugmentationCrd] = Field(default_factory=list)


class AugmentationCrdReader:
    def __init__(self, custom_api: CustomObjectsReader | None = None) -> None:
        self.enabled = True
        if custom_api is not None:
            self.custom = custom_api
            return
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException:
                logger.warning("Failed to load kube config, augmentation CRD reads are disabled")
                self.enabled = False
        self.custom = client.CustomObjectsApi()

    async def get_augmentation_resources(self) -> AugmentationResourceCrdState:
        generated_at = datetime.now(timezone.utc)
        if not self.enabled:
            return AugmentationResourceCrdState(generated_at=generated_at, observation_error="kubernetes config unavailable")
        try:
            response = self.custom.list_cluster_custom_object(group=GROUP, version=VERSION, plural=RESOURCE_PLURAL)
        except ApiException as exc:
            logger.warning("Failed to list AugmentationResource CRDs: %s", exc.reason)
            return AugmentationResourceCrdState(generated_at=generated_at, observation_error=f"kubernetes api error: {exc.reason}")
        return AugmentationResourceCrdState(
            generated_at=generated_at,
            resources=[augmentation_resource_from_item(item) for item in response_items(response)],
        )

    async def get_device_augmentations(self, namespace: str = "default") -> DeviceAugmentationCrdState:
        generated_at = datetime.now(timezone.utc)
        if not self.enabled:
            return DeviceAugmentationCrdState(
                generated_at=generated_at,
                namespace=namespace,
                observation_error="kubernetes config unavailable",
            )
        try:
            response = self.custom.list_namespaced_custom_object(
                group=GROUP,
                version=VERSION,
                namespace=namespace,
                plural=BINDING_PLURAL,
            )
        except ApiException as exc:
            logger.warning("Failed to list DeviceAugmentation CRDs: %s", exc.reason)
            return DeviceAugmentationCrdState(
                generated_at=generated_at,
                namespace=namespace,
                observation_error=f"kubernetes api error: {exc.reason}",
            )
        return DeviceAugmentationCrdState(
            generated_at=generated_at,
            namespace=namespace,
            device_augmentations=[device_augmentation_from_item(item) for item in response_items(response)],
        )


def response_items(response: JsonMap) -> list[JsonMap]:
    items = response.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def augmentation_resource_from_item(item: JsonMap) -> AugmentationResourceCrd:
    metadata = nested_map(item.get("metadata"))
    spec = nested_map(item.get("spec"))
    status = nested_map(item.get("status"))
    return AugmentationResourceCrd(
        name=text(metadata.get("name")),
        display_name=text(spec.get("displayName"), text(metadata.get("name"))),
        resource_type=text(spec.get("resourceType")),
        node=text(nested_map(spec.get("nodeSelector")).get("kubernetes.io/hostname")),
        capabilities=text_list(spec.get("capabilities")),
        stage_types=text_list(spec.get("stageTypes")),
        phase=text(status.get("phase"), "Unknown"),
        observed_instances=number(status.get("observedInstances")),
        free_instances=number(status.get("freeInstances")),
        allocated_instances=number(status.get("allocatedInstances")),
        binding_state=text(status.get("bindingState"), "unknown"),
        endpoint_ready=flag(status.get("endpointReady")),
        reason=optional_text(status.get("reason")),
        conditions=conditions(status.get("conditions")),
    )


def device_augmentation_from_item(item: JsonMap) -> DeviceAugmentationCrd:
    metadata = nested_map(item.get("metadata"))
    spec = nested_map(item.get("spec"))
    status = nested_map(item.get("status"))
    target = nested_map(spec.get("targetDevice"))
    return DeviceAugmentationCrd(
        name=text(metadata.get("name")),
        namespace=text(metadata.get("namespace"), "default"),
        target_device_kind=text(target.get("kind")),
        target_device_name=text(target.get("name")),
        phase=text(status.get("phase"), "Unknown"),
        required_capabilities=text_list(spec.get("requiredCapabilities")),
        bound_resources=text_list(status.get("boundResources")),
        missing_capabilities=text_list(status.get("missingCapabilities")),
        selected_resources=selected_resources(status.get("selectedResources")),
        workload_policy=workload_policy(spec.get("workloadPolicy")),
        reason=optional_text(status.get("reason")),
        conditions=conditions(status.get("conditions")),
    )


def selected_resources(value: JsonValue) -> list[SelectedAugmentationResource]:
    return [
        SelectedAugmentationResource(
            role=text(item.get("role")),
            name=text(item.get("name")),
            phase=optional_text(item.get("phase")),
            node=optional_text(item.get("node")),
            observed_instances=optional_number(item.get("observedInstances")),
            binding_state=optional_text(item.get("bindingState")),
            endpoint_ready=optional_flag(item.get("endpointReady")),
        )
        for item in dicts(value)
    ]


def conditions(value: JsonValue) -> list[CrdCondition]:
    return [
        CrdCondition(
            type=text(item.get("type")),
            status=text(item.get("status"), "Unknown"),
            reason=optional_text(item.get("reason")),
            message=optional_text(item.get("message")),
            last_transition_time=optional_text(item.get("lastTransitionTime")),
        )
        for item in dicts(value)
    ]


def workload_policy(value: JsonValue) -> dict[str, str | bool]:
    policy = nested_map(value)
    return {
        key: item
        for key, item in policy.items()
        if isinstance(key, str) and isinstance(item, str | bool)
    }


def nested_map(value: JsonValue) -> JsonMap:
    return value if isinstance(value, dict) else {}


def dicts(value: JsonValue) -> list[JsonMap]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def text_list(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def text(value: JsonValue, fallback: str = "") -> str:
    return value if isinstance(value, str) and value else fallback


def optional_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def number(value: JsonValue) -> int:
    result = optional_number(value)
    return result if result is not None else 0


def optional_number(value: JsonValue) -> int | None:
    match value:
        case bool():
            return None
        case int() as number_value:
            return number_value
        case float() as number_value:
            return int(number_value)
        case str() | None | list() | dict():
            return None


def flag(value: JsonValue) -> bool:
    return value if isinstance(value, bool) else False


def optional_flag(value: JsonValue) -> bool | None:
    return value if isinstance(value, bool) else None
