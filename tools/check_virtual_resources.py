from __future__ import annotations

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonPayload = dict[str, JsonValue]

VIRTUAL_RESOURCE_FIELDS = [
    "id",
    "display_name",
    "node",
    "resource_type",
    "desired_instances",
    "observed_instances",
    "free_instances",
    "allocated_instances",
    "status",
    "twin",
]


def check_virtual_resources(payload: JsonPayload) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    mode = payload.get("mode")
    scope = payload.get("scope")
    resources = payload.get("resources")

    if mode != "read_only":
        errors.append(f"virtual resources mode={mode!r}, expected 'read_only'")
    if scope != "resource_augmentation_virtual_devices":
        errors.append(
            f"virtual resources scope={scope!r}, expected 'resource_augmentation_virtual_devices'"
        )
    if not isinstance(resources, list):
        errors.append("virtual resources payload missing resources[]")
        return errors, warnings
    if not resources:
        warnings.append("virtual resources resources[] is empty")

    for resource in resources:
        if not isinstance(resource, dict):
            errors.append("virtual resources resources[] item is not an object")
            continue
        _check_resource(resource, errors)

    return errors, warnings


def _check_resource(resource: JsonPayload, errors: list[str]) -> None:
    resource_id = str(resource.get("id") or "<unknown>")
    for field in VIRTUAL_RESOURCE_FIELDS:
        if field not in resource:
            errors.append(f"{resource_id}: missing virtual resource field resources[].{field}")

    status = resource.get("status")
    observed_instances = resource.get("observed_instances")
    twin = resource.get("twin")
    if observed_instances == 0 and status != "configured_not_running":
        errors.append(f"{resource_id}: observed_instances=0 but status={status!r}")
    if status == "configured_not_running" and observed_instances != 0:
        errors.append(f"{resource_id}: configured_not_running but observed_instances={observed_instances!r}")
    if not isinstance(twin, dict):
        errors.append(f"{resource_id}: twin is missing or not an object")
        return
    binding_state = twin.get("binding_state")
    if observed_instances == 0 and binding_state != "not_running":
        errors.append(f"{resource_id}: observed_instances=0 but twin.binding_state={binding_state!r}")


def print_virtual_resource_summary(payload: JsonPayload) -> None:
    resources = payload.get("resources")
    print("\nVirtual resources")
    print(f"  mode: {payload.get('mode')}")
    print(f"  scope: {payload.get('scope')}")
    print(f"  observation_error: {payload.get('observation_error')}")
    if not isinstance(resources, list):
        return
    for resource in resources[:20]:
        if isinstance(resource, dict):
            print(_format_resource(resource))


def _format_resource(resource: JsonPayload) -> str:
    twin = resource.get("twin")
    binding = twin.get("binding_state") if isinstance(twin, dict) else None
    return (
        "  {id} node={node} type={rtype} status={status} desired={desired} observed={observed} "
        "free={free} allocated={allocated} binding={binding}"
    ).format(
        id=resource.get("id"),
        node=resource.get("node"),
        rtype=resource.get("resource_type"),
        status=resource.get("status"),
        desired=resource.get("desired_instances"),
        observed=resource.get("observed_instances"),
        free=resource.get("free_instances"),
        allocated=resource.get("allocated_instances"),
        binding=binding,
    )
