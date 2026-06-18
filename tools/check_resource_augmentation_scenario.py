#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
# ─── How to run ───
# python3 tools/check_resource_augmentation_scenario.py --base-url http://127.0.0.1:8000

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Final

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonMap = dict[str, JsonValue]

DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    target_device: str
    device_augmentation: str
    inference_resource: str
    storage_resource: str


SCENARIO: Final[Scenario] = Scenario(
    name="jetson-vision-inspection",
    target_device="etri-dev0001-jetorn",
    device_augmentation="jetson-gpu-storage-augmentation",
    inference_resource="vd-x86-gpu-inference",
    storage_resource="vd-storage-cache",
)


@dataclass(frozen=True, slots=True)
class CliOptions:
    base_url: str


def parse_args(argv: list[str]) -> CliOptions:
    if not argv:
        return CliOptions(base_url=DEFAULT_BASE_URL)
    match argv:
        case ["--base-url", value]:
            return CliOptions(base_url=value.rstrip("/"))
        case ["-h"] | ["--help"]:
            print("usage: check_resource_augmentation_scenario.py [--base-url URL]")
            raise SystemExit(0)
        case _:
            print("usage: check_resource_augmentation_scenario.py [--base-url URL]", file=sys.stderr)
            raise SystemExit(2)


def fetch_json(base_url: str, path: str) -> JsonMap:
    url = f"{base_url.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        msg = f"{path} did not return a JSON object"
        raise TypeError(msg)
    return payload


def check_scenario_payloads(
    *,
    virtual_resources: JsonMap,
    augmentation_resources: JsonMap,
    device_augmentations: JsonMap,
    scenario: Scenario = SCENARIO,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for label, payload in (
        ("virtual resources", virtual_resources),
        ("augmentation resources", augmentation_resources),
        ("device augmentations", device_augmentations),
    ):
        observation_error = payload.get("observation_error")
        if isinstance(observation_error, str) and observation_error:
            warnings.append(f"{label} observation_error={observation_error}")

    virtual_resource_map = keyed_items(virtual_resources, "resources", "id")
    augmentation_resource_map = keyed_items(augmentation_resources, "resources", "name")
    device_augmentation_map = keyed_items(device_augmentations, "device_augmentations", "name")

    require_virtual_resource(virtual_resource_map, scenario.inference_resource, errors)
    require_virtual_resource(virtual_resource_map, scenario.storage_resource, errors)
    require_augmentation_resource(augmentation_resource_map, scenario.inference_resource, errors)
    require_augmentation_resource(augmentation_resource_map, scenario.storage_resource, errors)
    require_device_augmentation(device_augmentation_map, scenario, errors)

    return errors, warnings


def keyed_items(payload: JsonMap, list_key: str, name_key: str) -> dict[str, JsonMap]:
    items = payload.get(list_key)
    if not isinstance(items, list):
        return {}
    keyed: dict[str, JsonMap] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get(name_key)
        if isinstance(name, str):
            keyed[name] = item
    return keyed


def require_virtual_resource(resources: dict[str, JsonMap], resource_id: str, errors: list[str]) -> None:
    resource = resources.get(resource_id)
    if resource is None:
        errors.append(f"missing virtual resource {resource_id}")
        return
    observed = resource.get("observed_instances")
    twin = nested_map(resource.get("twin"))
    if not isinstance(observed, int) or observed <= 0:
        errors.append(f"{resource_id}: expected observed_instances > 0, got {observed!r}")
    if twin.get("endpoint_ready") is not True:
        errors.append(f"{resource_id}: expected twin.endpoint_ready=true")
    if twin.get("binding_state") not in {"available", "partial", "allocated"}:
        errors.append(f"{resource_id}: unexpected twin.binding_state={twin.get('binding_state')!r}")


def require_augmentation_resource(resources: dict[str, JsonMap], resource_id: str, errors: list[str]) -> None:
    resource = resources.get(resource_id)
    if resource is None:
        errors.append(f"missing AugmentationResource {resource_id}")
        return
    if resource.get("phase") != "Available":
        errors.append(f"{resource_id}: expected AugmentationResource phase=Available, got {resource.get('phase')!r}")
    if resource.get("endpoint_ready") is not True:
        errors.append(f"{resource_id}: expected AugmentationResource endpoint_ready=true")


def require_device_augmentation(bindings: dict[str, JsonMap], scenario: Scenario, errors: list[str]) -> None:
    binding = bindings.get(scenario.device_augmentation)
    if binding is None:
        errors.append(f"missing DeviceAugmentation {scenario.device_augmentation}")
        return
    if binding.get("target_device_name") != scenario.target_device:
        errors.append(
            f"{scenario.device_augmentation}: expected target_device_name={scenario.target_device}, "
            f"got {binding.get('target_device_name')!r}"
        )
    if binding.get("phase") != "Ready":
        errors.append(f"{scenario.device_augmentation}: expected phase=Ready, got {binding.get('phase')!r}")
    selected = selected_resources(binding)
    if selected.get("inference") != scenario.inference_resource:
        errors.append(
            f"{scenario.device_augmentation}: expected inference={scenario.inference_resource}, "
            f"got {selected.get('inference')!r}"
        )
    if selected.get("storage") != scenario.storage_resource:
        errors.append(
            f"{scenario.device_augmentation}: expected storage={scenario.storage_resource}, "
            f"got {selected.get('storage')!r}"
        )
    ready = condition_status(binding, "Ready")
    if ready != "True":
        errors.append(f"{scenario.device_augmentation}: expected Ready condition=True, got {ready!r}")


def selected_resources(binding: JsonMap) -> dict[str, str]:
    selected = binding.get("selected_resources")
    if not isinstance(selected, list):
        return {}
    role_to_name: dict[str, str] = {}
    for item in selected:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        name = item.get("name")
        if isinstance(role, str) and isinstance(name, str):
            role_to_name[role] = name
    return role_to_name


def condition_status(binding: JsonMap, condition_type: str) -> str | None:
    conditions = binding.get("conditions")
    if not isinstance(conditions, list):
        return None
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if condition.get("type") == condition_type:
            status = condition.get("status")
            return status if isinstance(status, str) else None
    return None


def nested_map(value: JsonValue) -> JsonMap:
    return value if isinstance(value, dict) else {}


def print_summary(errors: list[str], warnings: list[str]) -> None:
    print(f"Scenario: {SCENARIO.name}")
    print(f"  target device: {SCENARIO.target_device}")
    print(f"  DeviceAugmentation: {SCENARIO.device_augmentation}")
    print(f"  inference resource: {SCENARIO.inference_resource}")
    print(f"  storage resource: {SCENARIO.storage_resource}")
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        print("FAIL")
        for error in errors:
            print(f"  - {error}")
        return
    print("PASS: resource augmentation virtual device scenario is Ready")


def main() -> int:
    options = parse_args(sys.argv[1:])
    try:
        virtual_resources = fetch_json(options.base_url, "/state/virtual-resources")
        augmentation_resources = fetch_json(options.base_url, "/state/augmentation-resources")
        device_augmentations = fetch_json(options.base_url, "/state/device-augmentations")
    except (TypeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to read scenario API state: {exc}", file=sys.stderr)
        return 2
    errors, warnings = check_scenario_payloads(
        virtual_resources=virtual_resources,
        augmentation_resources=augmentation_resources,
        device_augmentations=device_augmentations,
    )
    print_summary(errors, warnings)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
