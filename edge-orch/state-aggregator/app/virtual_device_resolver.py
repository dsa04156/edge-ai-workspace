from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import (
    AiInputFieldMap,
    AiServiceReference,
    EdgeXDevice,
    EdgeXDeviceProfile,
    EventHistoryPage,
    OriginalEventRef,
    PhysicalDeviceReference,
    TelemetryPoint,
    VirtualDeviceCapability,
    VirtualDeviceInput,
    VirtualDeviceView,
    WorkloadReference,
)
from .virtual_device_bindings import VirtualDeviceInstance

_REASON_ORDER = (
    "device_missing", "profile_mismatch", "profile_not_found",
    "edgex_admin_locked", "edgex_admin_unknown", "edgex_operating_down",
    "edgex_operating_unknown", "profile_resource_missing", "ambiguous_binding",
    "history_truncated", "no_event", "stale", "required_input_missing",
    "type_mismatch", "unit_mismatch", "provenance_incomplete",
    "upstream_profile_error", "upstream_event_error",
)


def resolve_virtual_device(
    instance: VirtualDeviceInstance,
    *,
    config_revision: str,
    observation_time: datetime,
    device: EdgeXDevice | None,
    profile: EdgeXDeviceProfile | None,
    history: EventHistoryPage | None,
) -> VirtualDeviceView:
    """Resolve a single immutable EdgeX observation without authority reads."""
    reasons: set[str] = set()
    warnings: set[str] = set()
    unresolved = False
    if device is None:
        unresolved, reasons = True, {"device_missing"}
    elif device.profile_name != instance.physical_device_ref.expected_profile_name:
        unresolved, reasons = True, {"profile_mismatch"}
    elif profile is None:
        unresolved, reasons = True, {"profile_not_found"}
    else:
        if device.admin_state == "LOCKED":
            reasons.add("edgex_admin_locked")
        elif device.admin_state != "UNLOCKED":
            reasons.add("edgex_admin_unknown")
        if device.operating_state == "DOWN":
            reasons.add("edgex_operating_down")
        elif device.operating_state != "UP":
            reasons.add("edgex_operating_unknown")

    resources = {resource.name for resource in profile.device_resources} if profile else set()
    fresh_points = history.events if history else []
    prior_points = history.prior_probe_events if history else []
    uncertain_pairs = set(history.uncertain_source_resources) if history else set()
    capabilities: list[VirtualDeviceCapability] = []
    for capability in instance.capabilities:
        inputs: list[VirtualDeviceInput] = []
        for configured in capability.inputs:
            input_reasons: set[str] = set()
            aliases = [(item.source_name, item.resource_name) for item in configured.bindings]
            alias_resources = {resource for _, resource in aliases}
            if len(aliases) != len(set(aliases)):
                input_reasons.add("ambiguous_binding")
            if not unresolved and profile is not None and not any(
                resource in resources for resource in alias_resources
            ):
                input_reasons.add("profile_resource_missing")
            eligible_aliases = (
                [
                    alias
                    for alias in aliases
                    if profile is None or alias[1] in resources
                ]
            )

            alias_order = {
                alias: index for index, alias in enumerate(eligible_aliases)
            }

            def alias_rank(point: TelemetryPoint) -> int | None:
                exact = alias_order.get((point.source_name, point.resource_name))
                if exact is not None:
                    return exact
                possible = [
                    index
                    for (source_name, resource_name), index in alias_order.items()
                    if (not point.source_name or source_name == point.source_name)
                    and (not point.resource_name or resource_name == point.resource_name)
                ]
                return possible[0] if len(possible) == 1 else None

            candidates = [
                point
                for point in fresh_points
                if alias_rank(point) is not None
                and (not point.resource_name or point.resource_name in resources)
            ]
            candidates.sort(
                key=lambda point: (
                    alias_rank(point),
                    -(point.reading_origin or point.origin),
                    -(point.event_origin or point.origin),
                    point.event_id or "",
                )
            )
            selected = candidates[0] if candidates else None
            if selected:
                rank = (
                    alias_rank(selected),
                    selected.reading_origin or selected.origin,
                    selected.event_origin or selected.origin,
                    selected.event_id or "",
                )
                tied = [
                    point
                    for point in candidates
                    if (
                        alias_rank(point),
                        point.reading_origin or point.origin,
                        point.event_origin or point.origin,
                        point.event_id or "",
                    )
                    == rank
                ]
                if any(point != tied[0] for point in tied[1:]):
                    input_reasons.add("ambiguous_binding")
                    selected = None
            uncertain = bool(
                history
                and any(
                    alias in uncertain_pairs
                    for alias in aliases
                )
            )
            if uncertain:
                input_reasons.add("history_truncated")

            if selected:
                if selected.value_type not in configured.accepted_value_types:
                    input_reasons.add("type_mismatch")
                if selected.units not in configured.accepted_units:
                    input_reasons.add("unit_mismatch")
                if selected.timestamp < observation_time - timedelta(seconds=capability.freshness_seconds):
                    input_reasons.add("stale")
                if selected.timestamp > observation_time:
                    input_reasons.add("provenance_incomplete")
                if (
                    not selected.event_id
                    or not selected.event_id.strip()
                    or selected.event_origin is None
                    or selected.reading_origin is None or selected.device_name != device.name
                    or selected.profile_name != profile.name
                    or not selected.source_name
                    or not selected.resource_name
                    or alias_rank(selected) is None
                ):
                    input_reasons.add("provenance_incomplete")
            elif not unresolved and "ambiguous_binding" not in input_reasons:
                older_match = any((point.source_name, point.resource_name) in aliases for point in prior_points)
                if uncertain:
                    input_reasons.add("history_truncated")
                elif history is not None and not history.events and not prior_points:
                    input_reasons.add("no_event")
                elif older_match:
                    input_reasons.add("stale")
                else:
                    input_reasons.add("required_input_missing")

            if configured.required:
                reasons.update(input_reasons)
            else:
                warnings.update(input_reasons)
            original = None
            if selected and "provenance_incomplete" not in input_reasons:
                original = OriginalEventRef(
                    event_id=selected.event_id, event_origin=selected.event_origin,
                    reading_origin=selected.reading_origin, device_name=selected.device_name,
                    profile_name=selected.profile_name, source_name=selected.source_name,
                    resource_name=selected.resource_name,
                )
            inputs.append(VirtualDeviceInput(
                input_id=configured.input_id, capability_field=configured.capability_field,
                required=configured.required, selected_source_name=selected.source_name if selected else None,
                selected_resource_name=selected.resource_name if selected else None,
                value_type=selected.value_type if selected else None, value=selected.value if selected else None,
                units=selected.units if selected else None, observed_at=selected.timestamp if selected else None,
                original_event_ref=original,
                ready=bool(
                    not unresolved
                    and profile is not None
                    and selected is not None
                    and not input_reasons
                ),
            ))
        capabilities.append(VirtualDeviceCapability(id=capability.id, inputs=inputs))

    status = "unresolved" if unresolved else "degraded" if reasons else "ready"
    visible_reasons = reasons if not unresolved else {
        reason for reason in reasons
        if reason in {"device_missing", "profile_mismatch", "profile_not_found"}
    }
    ai = instance.ai_service_ref
    return VirtualDeviceView(
        id=instance.id, binding_status=status, reason_codes=sorted(visible_reasons, key=_reason_index),
        warnings=sorted(warnings, key=_reason_index), config_revision=config_revision,
        history_truncated=bool(history and history.history_truncated),
        physical_device_ref=PhysicalDeviceReference(
            name=instance.physical_device_ref.name,
            expected_profile_name=instance.physical_device_ref.expected_profile_name,
            actual_profile_name=device.profile_name if device else None,
            device_service_name=device.device_service_name if device else None,
            admin_state=device.admin_state if device else None,
            operating_state=device.operating_state if device else None,
            node_name=device.node_name if device else None,
            profile_resolved=bool(
                profile
                and device
                and profile.name == device.profile_name
                and device.profile_name
                == instance.physical_device_ref.expected_profile_name
            ),
        ),
        capabilities=capabilities,
        ai_service_ref=AiServiceReference(
            service_id=ai.service_id, input_contract=ai.input_contract, binding_mode=ai.binding_mode,
            input_field_map=[AiInputFieldMap(input_id=item.input_id, ai_field=item.ai_field) for item in ai.input_field_map],
            workload_ref=WorkloadReference(
                namespace=ai.workload_ref.namespace, kind=ai.workload_ref.kind, name=ai.workload_ref.name,
            ) if ai.workload_ref else None,
        ),
    )


def _reason_index(reason: str) -> int:
    try:
        return _REASON_ORDER.index(reason)
    except ValueError:
        return len(_REASON_ORDER)
