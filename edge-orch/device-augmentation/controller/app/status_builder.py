from __future__ import annotations

from datetime import datetime, timezone
from typing import Final

from .models import JsonMap, JsonValue, VirtualResourceProfile

AVAILABLE_STATES: Final[frozenset[str]] = frozenset({"idle", "allocated", "partially_available"})
BINDING_ROLES: Final[tuple[tuple[str, str], ...]] = (
    ("inference", "inferenceResource"),
    ("preprocess", "preprocessResource"),
    ("storage", "storageResource"),
    ("modelCache", "modelCacheResource"),
)


def phase_from_resource_status(status: str) -> str:
    match status:
        case "idle" | "partially_available":
            return "Available"
        case "allocated":
            return "Allocated"
        case "configured_not_running":
            return "Pending"
        case "degraded":
            return "Degraded"
        case "unavailable":
            return "Unavailable"
        case "unknown":
            return "Unknown"
        case _:
            return "Unknown"


def augmentation_resource_status(resource: VirtualResourceProfile, observed_at: datetime | None = None) -> JsonMap:
    timestamp = observed_at or datetime.now(timezone.utc)
    phase = phase_from_resource_status(resource.status)
    return {
        "status": {
            "phase": phase,
            "observedInstances": resource.observed_instances,
            "freeInstances": resource.free_instances,
            "allocatedInstances": resource.allocated_instances,
            "bindingState": resource.twin.binding_state,
            "nodeReady": resource.twin.node_ready,
            "podReady": resource.twin.pod_ready,
            "endpointReady": resource.twin.endpoint_ready,
            "reason": resource.twin.status_reason,
            "lastObservedAt": timestamp.isoformat(),
            "conditions": augmentation_resource_conditions(resource, phase, timestamp),
        }
    }


def condition(condition_type: str, status: bool, reason: str, message: str, timestamp: datetime) -> JsonMap:
    return {
        "type": condition_type,
        "status": "True" if status else "False",
        "reason": reason,
        "message": message,
        "lastTransitionTime": timestamp.isoformat(),
    }


def augmentation_resource_conditions(resource: VirtualResourceProfile, phase: str, timestamp: datetime) -> list[JsonMap]:
    observed = resource.observed_instances > 0
    endpoint_ready = resource.twin.endpoint_ready
    available = phase in {"Available", "Allocated"}
    return [
        condition(
            "RuntimeObserved",
            observed,
            "InstancesObserved" if observed else "NoInstancesObserved",
            f"{resource.observed_instances} runtime instance(s) observed",
            timestamp,
        ),
        condition(
            "EndpointReady",
            endpoint_ready,
            "EndpointReady" if endpoint_ready else "EndpointNotReady",
            "runtime endpoint is ready" if endpoint_ready else "runtime endpoint is not ready",
            timestamp,
        ),
        condition(
            "Available",
            available,
            "ResourceAvailable" if available else "ResourceUnavailable",
            resource.twin.status_reason,
            timestamp,
        ),
    ]


def text_list(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def nested_map(value: JsonValue | None) -> JsonMap:
    if not isinstance(value, dict):
        return {}
    return value


def binding_refs(device_augmentation: JsonMap) -> tuple[str, ...]:
    return tuple(ref for _, ref in binding_roles(device_augmentation))


def binding_roles(device_augmentation: JsonMap) -> tuple[tuple[str, str], ...]:
    spec = nested_map(device_augmentation.get("spec"))
    bindings = nested_map(spec.get("bindings"))
    refs = []
    for role, field in BINDING_ROLES:
        ref = bindings.get(field)
        if isinstance(ref, str) and ref:
            refs.append((role, ref))
    return tuple(refs)


def device_augmentation_status(
    device_augmentation: JsonMap,
    resources: dict[str, VirtualResourceProfile],
    declared_capabilities: dict[str, tuple[str, ...]] | None = None,
    observed_at: datetime | None = None,
) -> JsonMap:
    timestamp = observed_at or datetime.now(timezone.utc)
    capability_overrides = declared_capabilities or {}
    role_refs = binding_roles(device_augmentation)
    refs = tuple(ref for _, ref in role_refs)
    bound = tuple(ref for ref in refs if ref in resources)
    spec = nested_map(device_augmentation.get("spec"))
    required = set(text_list(spec.get("requiredCapabilities")))
    provided = {
        capability
        for ref in bound
        for capability in (*resources[ref].capabilities, *capability_overrides.get(ref, ()))
    }
    missing = tuple(sorted(required - provided))
    unavailable = tuple(ref for ref in bound if resources[ref].status not in AVAILABLE_STATES)
    phase = device_augmentation_phase(refs=refs, bound=bound, missing=missing, unavailable=unavailable)
    reason = reason_for_device_augmentation(refs=refs, bound=bound, missing=missing, unavailable=unavailable)
    return {
        "status": {
            "phase": phase,
            "boundResources": list(bound),
            "selectedResources": selected_resources(role_refs, resources),
            "missingCapabilities": list(missing),
            "reason": reason,
            "lastValidatedAt": timestamp.isoformat(),
            "conditions": device_augmentation_conditions(refs, bound, missing, unavailable, phase, reason, timestamp),
        }
    }


def selected_resources(role_refs: tuple[tuple[str, str], ...], resources: dict[str, VirtualResourceProfile]) -> list[JsonMap]:
    selected = []
    for role, ref in role_refs:
        resource = resources.get(ref)
        if resource is None:
            continue
        selected.append(
            {
                "role": role,
                "name": ref,
                "phase": phase_from_resource_status(resource.status),
                "node": resource.node,
                "observedInstances": resource.observed_instances,
                "bindingState": resource.twin.binding_state,
                "endpointReady": resource.twin.endpoint_ready,
            }
        )
    return selected


def device_augmentation_conditions(
    refs: tuple[str, ...],
    bound: tuple[str, ...],
    missing: tuple[str, ...],
    unavailable: tuple[str, ...],
    phase: str,
    reason: str,
    timestamp: datetime,
) -> list[JsonMap]:
    bindings_resolved = bool(refs) and len(bound) == len(refs)
    capabilities_satisfied = not missing
    resources_available = bindings_resolved and not unavailable
    return [
        condition(
            "BindingsResolved",
            bindings_resolved,
            "AllBindingsResolved" if bindings_resolved else "BindingsMissing",
            "all declared augmentation resource bindings are resolved" if bindings_resolved else reason,
            timestamp,
        ),
        condition(
            "CapabilitiesSatisfied",
            capabilities_satisfied,
            "CapabilitiesSatisfied" if capabilities_satisfied else "CapabilitiesMissing",
            "required capabilities are provided" if capabilities_satisfied else reason,
            timestamp,
        ),
        condition(
            "ResourcesAvailable",
            resources_available,
            "ResourcesAvailable" if resources_available else "ResourcesUnavailable",
            "bound resources are available" if resources_available else reason,
            timestamp,
        ),
        condition(
            "Ready",
            phase == "Ready",
            "DeviceAugmentationReady" if phase == "Ready" else "DeviceAugmentationNotReady",
            reason,
            timestamp,
        ),
    ]


def device_augmentation_phase(
    *,
    refs: tuple[str, ...],
    bound: tuple[str, ...],
    missing: tuple[str, ...],
    unavailable: tuple[str, ...],
) -> str:
    if not refs:
        return "Blocked"
    if len(bound) != len(refs) or missing:
        return "Blocked"
    if len(unavailable) == len(bound):
        return "Degraded"
    if unavailable:
        return "PartiallyReady"
    return "Ready"


def reason_for_device_augmentation(
    *,
    refs: tuple[str, ...],
    bound: tuple[str, ...],
    missing: tuple[str, ...],
    unavailable: tuple[str, ...],
) -> str:
    if not refs:
        return "no augmentation resource binding is declared"
    if len(bound) != len(refs):
        return "one or more bound augmentation resources are missing"
    if missing:
        return f"missing capabilities: {', '.join(missing)}"
    if unavailable:
        return f"bound resources are not fully available: {', '.join(unavailable)}"
    return "bound augmentation resources are available"
