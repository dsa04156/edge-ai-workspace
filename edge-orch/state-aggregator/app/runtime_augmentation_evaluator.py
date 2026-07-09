from __future__ import annotations

from datetime import datetime, timezone
from typing import TypeAlias

from .augmentation_crds import AugmentationResourceCrd, DeviceAugmentationCrd
from .runtime_augmentation_demo import build_demo_runtime_augmentation_state
from .runtime_augmentation_models import (
    AI_SERVICE,
    TARGET_DEVICE,
    CandidateResourceKind,
    CandidateResourcePhase,
    DecisionState,
    RuntimeAugmentationAugmentedDevice,
    RuntimeAugmentationCandidateResource,
    RuntimeAugmentationDecision,
    RuntimeAugmentationSelectedResource,
    RuntimeAugmentationState,
    RuntimeAugmentationSummary,
)
from .runtime_augmentation_workflow import build_runtime_workflow_demo

RuntimeJson: TypeAlias = str | int | float | bool | None | list["RuntimeJson"] | dict[str, "RuntimeJson"]
RuntimeMap: TypeAlias = dict[str, RuntimeJson]

CPU_PRESSURE_RATIO = 0.85
MEMORY_PRESSURE_RATIO = 0.85


def build_runtime_augmentation_state(
    service_resource_profiles: list[RuntimeMap] | None = None,
    augmentation_resources: list[AugmentationResourceCrd] | None = None,
    device_augmentations: list[DeviceAugmentationCrd] | None = None,
) -> RuntimeAugmentationState:
    if service_resource_profiles is None and augmentation_resources is None and device_augmentations is None:
        return build_demo_runtime_augmentation_state()
    profiles = service_resource_profiles or []
    resources = augmentation_resources or []
    bindings = device_augmentations or []
    candidates = [_candidate_resource(resource) for resource in resources]
    decision = _decision(profiles, resources, bindings)
    return RuntimeAugmentationState(
        generated_at=datetime.now(timezone.utc),
        summary=RuntimeAugmentationSummary(
            candidate_resource_total=len(candidates),
            available=sum(1 for item in candidates if item.phase == "Available"),
            bound=sum(1 for item in candidates if item.phase == "Bound"),
            blocked=sum(1 for item in candidates if item.phase == "Blocked"),
        ),
        candidate_resources=candidates,
        decision=decision,
        workflow_demo=build_runtime_workflow_demo(decision, len(candidates)),
    )


def _decision(
    profiles: list[RuntimeMap],
    resources: list[AugmentationResourceCrd],
    bindings: list[DeviceAugmentationCrd],
) -> RuntimeAugmentationDecision:
    profile = _target_profile(profiles)
    binding = _target_binding(bindings)
    reasons, score = _pressure(profile, binding)
    resource_map = {resource.name: resource for resource in resources}
    role_refs = _role_refs(binding, resource_map)
    unavailable = [name for _, name in role_refs if not _resource_ready(resource_map.get(name))]
    binding_block_reasons = _binding_block_reasons(binding)
    if not reasons:
        state: DecisionState = "none"
    elif binding_block_reasons or unavailable:
        state = "blocked"
        reasons = [
            *reasons,
            *binding_block_reasons,
            *[f"required_resource_not_ready:{name}" for name in unavailable],
        ]
    elif role_refs:
        state = "selected"
    else:
        state = "candidate"
    return RuntimeAugmentationDecision(
        state=state,
        pressure_score=score if state != "none" else 0,
        pressure_reason=reasons if state != "none" else [],
        candidate_resource_names=[name for _, name in role_refs],
        selected_resources=_selected_resources(state, role_refs, resource_map),
        resulting_augmented_device=RuntimeAugmentationAugmentedDevice(phase="Blocked" if state == "blocked" else "Planned"),
        apply_state="blocked" if state == "blocked" else "observed-only",
        explanation=_explanation(state),
    )


def _target_profile(profiles: list[RuntimeMap]) -> RuntimeMap | None:
    return next((profile for profile in profiles if profile.get("service") == AI_SERVICE), None)


def _target_binding(bindings: list[DeviceAugmentationCrd]) -> DeviceAugmentationCrd | None:
    return next(
        (
            binding
            for binding in bindings
            if binding.target_device_name == TARGET_DEVICE or binding.name == "jetson-gpu-storage-augmentation"
        ),
        None,
    )


def _pressure(profile: RuntimeMap | None, binding: DeviceAugmentationCrd | None) -> tuple[list[str], int]:
    if profile is None:
        return [], 0
    current = _map(profile.get("current_usage"))
    limits = _map(_map(profile.get("resource_requirements")).get("limits"))
    cpu_ratio = _ratio(_number(current.get("cpu_cores")), _number(limits.get("cpu_cores")))
    memory_ratio = _ratio(_number(current.get("memory_working_set_mib")), _number(limits.get("memory_mib")))
    gpu_units = _number(limits.get("gpu_units"))
    reasons: list[str] = []
    if cpu_ratio >= CPU_PRESSURE_RATIO:
        reasons.append("cpu_pressure")
    if memory_ratio >= MEMORY_PRESSURE_RATIO:
        reasons.append("memory_pressure")
    observed_pressure = bool(reasons)
    if observed_pressure and gpu_units > 0:
        reasons.append("gpu_inference_pressure")
    if observed_pressure and binding is not None and "result_cache" in binding.required_capabilities:
        reasons.append("cache_required")
    return reasons, min(100, round(max(cpu_ratio, memory_ratio) * 100)) if reasons else 0


def _role_refs(
    binding: DeviceAugmentationCrd | None,
    resources: dict[str, AugmentationResourceCrd],
) -> list[tuple[str, str]]:
    if binding is None:
        return []
    if binding.selected_resources:
        return [(item.role, item.name) for item in binding.selected_resources]
    return [(_role_for_resource(resources.get(name)), name) for name in binding.bound_resources]


def _binding_block_reasons(binding: DeviceAugmentationCrd | None) -> list[str]:
    if binding is None:
        return []
    reasons: list[str] = []
    if binding.phase != "Ready":
        reasons.append(f"device_augmentation_not_ready:{binding.phase}")
    reasons.extend(f"device_augmentation_missing_capability:{capability}" for capability in binding.missing_capabilities)
    ready_condition = next((condition for condition in binding.conditions if condition.type == "Ready"), None)
    if ready_condition is not None and ready_condition.status != "True":
        reason = ready_condition.reason or ready_condition.status
        reasons.append(f"device_augmentation_ready_condition:{reason}")
    for resource in binding.selected_resources:
        if resource.endpoint_ready is False:
            reasons.append(f"selected_resource_endpoint_not_ready:{resource.name}")
        if resource.phase in {"Pending", "Degraded", "Unavailable", "Unknown", "Blocked"}:
            reasons.append(f"selected_resource_not_ready:{resource.name}:{resource.phase}")
    return _unique(reasons)


def _selected_resources(
    state: DecisionState,
    role_refs: list[tuple[str, str]],
    resources: dict[str, AugmentationResourceCrd],
) -> list[RuntimeAugmentationSelectedResource]:
    if state not in {"selected", "candidate"}:
        return []
    return [
        RuntimeAugmentationSelectedResource(role=role, name=name, reason=_selection_reason(role, resources[name]))
        for role, name in role_refs
        if _resource_ready(resources.get(name))
    ]


def _candidate_resource(resource: AugmentationResourceCrd) -> RuntimeAugmentationCandidateResource:
    return RuntimeAugmentationCandidateResource(
        name=resource.name,
        kind=_kind(resource),
        phase=_candidate_phase(resource),
        node=resource.node,
        capability=", ".join(resource.capabilities) or resource.resource_type,
    )


def _kind(resource: AugmentationResourceCrd) -> CandidateResourceKind:
    capabilities = set(resource.capabilities)
    if "result_cache" in capabilities or "window_storage" in capabilities or "storage" in resource.resource_type:
        return "storage-cache"
    if "model_cache" in capabilities:
        return "model-cache"
    return "gpu-inference"


def _candidate_phase(resource: AugmentationResourceCrd) -> CandidateResourcePhase:
    if resource.phase == "Available" and resource.endpoint_ready:
        return "Available"
    if resource.phase in {"Allocated", "Bound"}:
        return "Bound"
    return "Blocked"


def _resource_ready(resource: AugmentationResourceCrd | None) -> bool:
    return resource is not None and resource.phase == "Available" and resource.endpoint_ready and resource.observed_instances > 0


def _role_for_resource(resource: AugmentationResourceCrd | None) -> str:
    if resource is None:
        return "resource"
    kind = _kind(resource)
    if kind == "storage-cache":
        return "storage"
    if kind == "model-cache":
        return "modelCache"
    return "inference"


def _selection_reason(role: str, resource: AugmentationResourceCrd) -> str:
    if role == "storage":
        return "cache resource is available"
    if role == "modelCache":
        return "model cache resource is available"
    return f"{resource.display_name} endpoint is available"


def _explanation(state: DecisionState) -> str:
    return {
        "none": "no observed service resource pressure requires augmentation",
        "candidate": "service resource pressure exists and augmentation candidates are being evaluated",
        "selected": "service resource pressure exists and selected augmentation resources are ready",
        "blocked": "service resource pressure exists but required augmentation resources are not ready",
    }[state]


def _map(value: RuntimeJson) -> RuntimeMap:
    return value if isinstance(value, dict) else {}


def _number(value: RuntimeJson) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
