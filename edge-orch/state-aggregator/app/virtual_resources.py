from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import NodeState

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonMap = dict[str, JsonValue]
ResourceStatus = Literal[
    "configured_not_running", "idle", "allocated", "partially_available", "degraded", "unavailable", "unknown"
]


class VirtualResourceRegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    node: str
    resource_type: str
    desired_instances: int = 1
    stage_type: str
    capabilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class VirtualResourceInstance(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    node: str
    pod: str
    container: str | None = None
    runtime_ready: bool
    binding_state: Literal["free", "allocated", "unknown"] = "free"
    bound_workflow: str | None = None
    bound_stage: str | None = None
    current_load: str = "unknown"


class VirtualResourceTwin(BaseModel):
    model_config = ConfigDict(frozen=True)

    availability: ResourceStatus
    node_ready: bool
    pod_ready: bool
    endpoint_ready: bool
    current_load: str
    binding_state: Literal["not_running", "available", "allocated", "partial", "unknown"]
    status_reason: str


class VirtualResourceProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    node: str
    resource_type: str
    desired_instances: int
    observed_instances: int
    free_instances: int
    allocated_instances: int
    status: ResourceStatus
    capabilities: list[str] = Field(default_factory=list)
    supported_stage_types: list[str] = Field(default_factory=list)
    instances: list[VirtualResourceInstance] = Field(default_factory=list)
    twin: VirtualResourceTwin


class VirtualResourceState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    scope: str = "resource_augmentation_virtual_devices"
    observation_error: str | None = None
    resources: list[VirtualResourceProfile] = Field(default_factory=list)


def build_virtual_resource_state(
    *,
    registry: tuple[VirtualResourceRegistryEntry, ...],
    service_resource_profiles: list[JsonMap],
    nodes: list[NodeState],
    observation_error: str | None = None,
) -> VirtualResourceState:
    node_health = {node.hostname: node.node_health for node in nodes}
    return VirtualResourceState(
        generated_at=datetime.now(timezone.utc),
        observation_error=observation_error,
        resources=[
            _build_resource_profile(
                registry=entry,
                service_resource_profiles=service_resource_profiles,
                node_health=node_health,
            )
            for entry in registry
        ],
    )


def _build_resource_profile(
    *,
    registry: VirtualResourceRegistryEntry,
    service_resource_profiles: list[JsonMap],
    node_health: dict[str, str],
) -> VirtualResourceProfile:
    instances = [
        instance
        for profile in service_resource_profiles
        if _profile_matches(profile, registry)
        for instance in _instances_from_profile(profile, registry)
    ]
    allocated_instances = sum(1 for item in instances if item.binding_state == "allocated")
    free_instances = len(instances) - allocated_instances
    node_ready = node_health.get(registry.node) in {"available", "healthy"}
    status = _resource_status(
        observed_instances=len(instances),
        node_ready=node_ready,
        free_instances=free_instances,
        allocated_instances=allocated_instances,
    )
    twin = VirtualResourceTwin(
        availability=status,
        node_ready=node_ready,
        pod_ready=bool(instances),
        endpoint_ready=bool(instances) and node_ready,
        current_load="normal" if instances else "unknown",
        binding_state=_binding_state(len(instances), free_instances, allocated_instances),
        status_reason=_status_reason(status),
    )
    return VirtualResourceProfile(
        id=registry.id,
        display_name=registry.display_name,
        node=registry.node,
        resource_type=registry.resource_type,
        desired_instances=registry.desired_instances,
        observed_instances=len(instances),
        free_instances=free_instances,
        allocated_instances=allocated_instances,
        status=status,
        capabilities=registry.capabilities,
        supported_stage_types=[registry.stage_type],
        instances=instances,
        twin=twin,
    )


def _profile_matches(profile: JsonMap, registry: VirtualResourceRegistryEntry) -> bool:
    haystack = " ".join(_profile_terms(profile)).casefold()
    # A node identifies where a resource may run; it does not identify the
    # resource itself. Matching on the node alone made every running Pod on a
    # GPU/AI node look like another accelerator instance. Require an explicit
    # workload/resource keyword and use the node only to scope matched
    # containers in ``_containers_for_registry``.
    return any(keyword.casefold() in haystack for keyword in registry.keywords)


def _profile_terms(profile: JsonMap) -> list[str]:
    terms = [_string(profile.get("namespace")), _string(profile.get("service"))]
    terms.extend(_strings(profile.get("nodes")))
    pods_by_node = profile.get("pods_by_node")
    if isinstance(pods_by_node, dict):
        terms.extend(str(node) for node in pods_by_node)
    for container in _dicts(profile.get("containers")):
        terms.extend([_string(container.get("pod")), _string(container.get("container")), _string(container.get("node"))])
    return [term for term in terms if term]


def _instances_from_profile(profile: JsonMap, registry: VirtualResourceRegistryEntry) -> list[VirtualResourceInstance]:
    containers = _containers_for_registry(_dicts(profile.get("containers")), registry)
    if containers:
        return [
            VirtualResourceInstance(
                id=f"{registry.id}-{index + 1:03d}",
                node=_string(container.get("node")) or registry.node,
                pod=_string(container.get("pod")) or f"{registry.id}-pod-{index + 1}",
                container=_string(container.get("container")) or None,
                runtime_ready=True,
            )
            for index, container in enumerate(containers)
        ]
    nodes = _strings(profile.get("nodes"))
    if nodes and registry.node.casefold() not in [node.casefold() for node in nodes]:
        return []
    pod_count = _int(profile.get("pod_count")) or 0
    return [
        VirtualResourceInstance(
            id=f"{registry.id}-{index + 1:03d}",
            node=registry.node,
            pod=f"{_string(profile.get('service')) or registry.id}-pod-{index + 1}",
            runtime_ready=True,
        )
        for index in range(pod_count)
    ]


def _containers_for_registry(
    containers: list[JsonMap],
    registry: VirtualResourceRegistryEntry,
) -> list[JsonMap]:
    if not containers:
        return []
    containers_with_node = [container for container in containers if _string(container.get("node"))]
    if not containers_with_node:
        return containers
    return [
        container
        for container in containers_with_node
        if _string(container.get("node")).casefold() == registry.node.casefold()
    ]


def _resource_status(
    *,
    observed_instances: int,
    node_ready: bool,
    free_instances: int,
    allocated_instances: int,
) -> ResourceStatus:
    if observed_instances == 0:
        return "configured_not_running"
    if not node_ready:
        return "unavailable"
    if allocated_instances > 0 and free_instances > 0:
        return "partially_available"
    if allocated_instances > 0:
        return "allocated"
    return "idle"


def _binding_state(
    observed_instances: int,
    free_instances: int,
    allocated_instances: int,
) -> Literal["not_running", "available", "allocated", "partial", "unknown"]:
    if observed_instances == 0:
        return "not_running"
    if allocated_instances > 0 and free_instances > 0:
        return "partial"
    if allocated_instances > 0:
        return "allocated"
    return "available"


def _status_reason(status: ResourceStatus) -> str:
    return {
        "configured_not_running": "registry exists but no runtime instance is observed",
        "idle": "runtime instance is observed and not bound",
        "allocated": "all observed instances are bound",
        "partially_available": "some observed instances are free and some are bound",
        "degraded": "runtime instance is observed with degraded signal",
        "unavailable": "runtime instance is observed but node is not ready",
        "unknown": "resource state is incomplete",
    }[status]


def _string(value: JsonValue) -> str:
    match value:
        case str() as text:
            return text
        case None:
            return ""
        case int() | float() | bool() | list() | dict():
            return str(value)


def _strings(value: JsonValue) -> list[str]:
    match value:
        case list() as items:
            return [_string(item) for item in items]
        case str() | int() | float() | bool() | None | dict():
            return []


def _dicts(value: JsonValue) -> list[JsonMap]:
    match value:
        case list() as items:
            return [item for item in items if isinstance(item, dict)]
        case str() | int() | float() | bool() | None | dict():
            return []


def _int(value: JsonValue) -> int | None:
    match value:
        case bool():
            return None
        case int() as number:
            return number
        case float() as number:
            return int(number)
        case str() | None | list() | dict():
            return None
