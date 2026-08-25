from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import (
    NodeSchedulingResource,
    PlacementCandidate,
    PlacementRequirements,
    PlacementScoreBreakdown,
    PlacementSelectionRequest,
    PlacementSelectionResult,
    PlacementServiceProfileRef,
    SchedulingResourceAmounts,
)


CPU_HEADROOM_WEIGHT = 30.0
MEMORY_HEADROOM_WEIGHT = 30.0
CPU_IDLE_WEIGHT = 20.0
MEMORY_IDLE_WEIGHT = 20.0


def select_placement(
    profile: dict[str, Any],
    resources: list[NodeSchedulingResource],
    request: PlacementSelectionRequest,
    *,
    excluded_nodes: set[str] | None = None,
    now: datetime | None = None,
) -> PlacementSelectionResult:
    generated_at = _utc(now)
    profile_ref = _profile_ref(profile)
    requirements, requirement_errors = _requirements(profile, request)
    if requirements is None:
        return PlacementSelectionResult(
            generated_at=generated_at,
            status="blocked",
            service_profile=profile_ref,
            requirements=None,
            reason_codes=requirement_errors,
        )

    candidates = [
        (
            _excluded_candidate(resource)
            if resource.node in (excluded_nodes or set())
            else _evaluate_candidate(resource, requirements)
        )
        for resource in sorted(resources, key=lambda item: item.node)
    ]
    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return PlacementSelectionResult(
            generated_at=generated_at,
            status="no_fit",
            service_profile=profile_ref,
            requirements=requirements,
            reason_codes=["no_eligible_nodes"],
            candidates=candidates,
        )

    selected = sorted(
        eligible,
        key=lambda candidate: (
            -(candidate.score or 0),
            -(candidate.available_after.cpu_cores if candidate.available_after else 0),
            -(
                candidate.available_after.memory_bytes
                if candidate.available_after
                else 0
            ),
            candidate.node,
        ),
    )[0]
    classified_candidates = [
        candidate.model_copy(
            update={
                "reason_codes": [
                    *candidate.reason_codes,
                    (
                        "selected_highest_score"
                        if candidate.node == selected.node
                        else "eligible_lower_score"
                    ),
                ]
            }
        )
        if candidate.eligible
        else candidate
        for candidate in candidates
    ]
    return PlacementSelectionResult(
        generated_at=generated_at,
        status="selected",
        service_profile=profile_ref,
        requirements=requirements,
        selected_node=selected.node,
        selected_score=selected.score,
        reason_codes=["eligible_node_selected"],
        candidates=classified_candidates,
    )


def _requirements(
    profile: dict[str, Any],
    request: PlacementSelectionRequest,
) -> tuple[PlacementRequirements | None, list[str]]:
    resource_requirements = _mapping(profile.get("resource_requirements"))
    requests = _mapping(resource_requirements.get("requests"))
    limits = _mapping(resource_requirements.get("limits"))
    missing = _mapping(resource_requirements.get("missing"))
    cpu_cores = _optional_number(requests.get("cpu_cores"))
    memory_mib = _optional_number(requests.get("memory_mib"))
    coverage = _optional_number(profile.get("request_coverage_ratio"))
    incomplete = bool(
        cpu_cores is None
        or memory_mib is None
        or coverage is None
        or coverage < 1
        or int(missing.get("cpu_request_containers") or 0) > 0
        or int(missing.get("memory_request_containers") or 0) > 0
    )
    if incomplete:
        return None, ["service_profile_requests_incomplete"]

    accelerator_units = dict(request.accelerator_units)
    gpu_units = _optional_number(limits.get("gpu_units")) or 0.0
    if gpu_units > 0 and not accelerator_units:
        accelerator_units["nvidia.com/gpu"] = gpu_units
    accelerator = request.accelerator
    if accelerator is None and gpu_units > 0:
        accelerator = "nvidia-gpu"
    memory_bytes = max(0, int(memory_mib * 1024 * 1024))
    return (
        PlacementRequirements(
            cpu_cores=max(0, cpu_cores),
            memory_bytes=memory_bytes,
            memory_gb=round(memory_bytes / 1_000_000_000, 3),
            architecture=request.architecture,
            accelerator=accelerator,
            accelerator_units={
                name: round(amount, 6)
                for name, amount in sorted(accelerator_units.items())
            },
        ),
        [],
    )


def _evaluate_candidate(
    resource: NodeSchedulingResource,
    requirements: PlacementRequirements,
) -> PlacementCandidate:
    reasons: list[str] = []
    if not resource.schedulable:
        reasons.append("node_not_schedulable")
        reasons.extend(
            reason for reason in resource.reason_codes if reason != "ready"
        )
    if resource.available.cpu_cores < requirements.cpu_cores:
        reasons.append("insufficient_cpu")
    if resource.available.memory_bytes < requirements.memory_bytes:
        reasons.append("insufficient_memory")
    if resource.architecture is None:
        reasons.append("architecture_unreported")
    elif resource.architecture.casefold() != requirements.architecture.casefold():
        reasons.append("architecture_mismatch")
    if requirements.accelerator and not _accelerator_matches(
        requirements.accelerator,
        resource,
    ):
        reasons.append(
            "accelerator_unavailable"
            if resource.accelerator is None
            else "accelerator_mismatch"
        )
    for name, amount in requirements.accelerator_units.items():
        if name not in resource.available.accelerator_units:
            reasons.append("accelerator_capacity_unreported")
        elif resource.available.accelerator_units[name] < amount:
            reasons.append("insufficient_accelerator")
    if (
        resource.utilization is None
        or resource.utilization.cpu_ratio is None
        or resource.utilization.memory_ratio is None
    ):
        reasons.append("utilization_unavailable")
    reasons = _unique(reasons)
    if reasons:
        return PlacementCandidate(
            node=resource.node,
            eligible=False,
            reason_codes=reasons,
            health=resource.health,
            architecture=resource.architecture,
            accelerator=resource.accelerator,
            available_before=resource.available,
            utilization=resource.utilization,
        )

    available_after = _available_after(resource.available, requirements)
    score_breakdown = _score(resource, available_after)
    return PlacementCandidate(
        node=resource.node,
        eligible=True,
        score=score_breakdown.total,
        reason_codes=["filter_passed"],
        health=resource.health,
        architecture=resource.architecture,
        accelerator=resource.accelerator,
        available_before=resource.available,
        available_after=available_after,
        utilization=resource.utilization,
        score_breakdown=score_breakdown,
    )


def _excluded_candidate(resource: NodeSchedulingResource) -> PlacementCandidate:
    return PlacementCandidate(
        node=resource.node,
        eligible=False,
        reason_codes=["current_node_excluded"],
        health=resource.health,
        architecture=resource.architecture,
        accelerator=resource.accelerator,
        available_before=resource.available,
        utilization=resource.utilization,
    )


def _available_after(
    available: SchedulingResourceAmounts,
    requirements: PlacementRequirements,
) -> SchedulingResourceAmounts:
    return SchedulingResourceAmounts(
        cpu_cores=round(max(0, available.cpu_cores - requirements.cpu_cores), 6),
        memory_bytes=max(0, available.memory_bytes - requirements.memory_bytes),
        accelerator_units={
            name: round(
                max(0, amount - requirements.accelerator_units.get(name, 0)),
                6,
            )
            for name, amount in available.accelerator_units.items()
        },
    )


def _score(
    resource: NodeSchedulingResource,
    available_after: SchedulingResourceAmounts,
) -> PlacementScoreBreakdown:
    utilization = resource.utilization
    assert utilization is not None
    assert utilization.cpu_ratio is not None
    assert utilization.memory_ratio is not None
    cpu_headroom_ratio = _ratio(
        available_after.cpu_cores,
        resource.allocatable.cpu_cores,
    )
    memory_headroom_ratio = _ratio(
        available_after.memory_bytes,
        resource.allocatable.memory_bytes,
    )
    cpu_idle_ratio = _clamp(1 - utilization.cpu_ratio)
    memory_idle_ratio = _clamp(1 - utilization.memory_ratio)
    points = {
        "cpu_headroom_points": cpu_headroom_ratio * CPU_HEADROOM_WEIGHT,
        "memory_headroom_points": memory_headroom_ratio * MEMORY_HEADROOM_WEIGHT,
        "cpu_idle_points": cpu_idle_ratio * CPU_IDLE_WEIGHT,
        "memory_idle_points": memory_idle_ratio * MEMORY_IDLE_WEIGHT,
    }
    return PlacementScoreBreakdown(
        cpu_headroom_ratio=round(cpu_headroom_ratio, 6),
        memory_headroom_ratio=round(memory_headroom_ratio, 6),
        cpu_idle_ratio=round(cpu_idle_ratio, 6),
        memory_idle_ratio=round(memory_idle_ratio, 6),
        **{name: round(value, 3) for name, value in points.items()},
        total=round(sum(points.values()), 3),
    )


def _accelerator_matches(
    required: str,
    resource: NodeSchedulingResource,
) -> bool:
    if resource.accelerator is None:
        return False
    required_key = _normalize_accelerator(required)
    actual_key = _normalize_accelerator(resource.accelerator)
    if required_key == actual_key:
        return True
    if required_key in {"gpu", "anygpu"}:
        return True
    if required_key in {"nvidia", "nvidiagpu"}:
        if any(
            name.lower().startswith("nvidia.com/")
            for name in resource.allocatable.accelerator_units
        ):
            return True
        return any(
            token in actual_key
            for token in ("nvidia", "rtx", "geforce", "tesla", "quadro", "cuda", "jetson")
        )
    return False


def _profile_ref(profile: dict[str, Any]) -> PlacementServiceProfileRef:
    return PlacementServiceProfileRef(
        namespace=str(profile.get("namespace") or ""),
        service=str(profile.get("service") or ""),
        generated_at=_datetime_or_none(profile.get("generated_at")),
        pod_count=max(0, int(profile.get("pod_count") or 0)),
        request_coverage_ratio=_clamp(
            _optional_number(profile.get("request_coverage_ratio")) or 0
        ),
    )


def _normalize_accelerator(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float | int, denominator: float | int) -> float:
    if denominator <= 0:
        return 0.0
    return _clamp(float(numerator) / float(denominator))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _utc(value: datetime | None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        return selected.replace(tzinfo=timezone.utc)
    return selected.astimezone(timezone.utc)
