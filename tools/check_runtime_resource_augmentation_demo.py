#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request
from typing import Any


JsonMap = dict[str, Any]
EXPECTED_SCOPE = "runtime_resource_augmentation_demo_v1"
EXPECTED_TOTAL = 15
EXPECTED_AI_SERVICE = "factory-vision-inspection-ai"


class Options:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


def parse_args(argv: list[str]) -> Options:
    base_url = "http://127.0.0.1:8000"
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--base-url" and index + 1 < len(argv):
            base_url = argv[index + 1].rstrip("/")
            index += 2
            continue
        print("usage: check_runtime_resource_augmentation_demo.py [--base-url URL]", file=sys.stderr)
        raise SystemExit(2)
    return Options(base_url=base_url)


def fetch_json(base_url: str) -> JsonMap:
    with urllib.request.urlopen(f"{base_url}/state/runtime-resource-augmentation", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def validate_runtime_augmentation(payload: JsonMap) -> list[str]:
    errors: list[str] = []
    if payload.get("scope") != EXPECTED_SCOPE:
        errors.append(f"scope={payload.get('scope')!r}, expected {EXPECTED_SCOPE!r}")
    if payload.get("ai_service") != EXPECTED_AI_SERVICE:
        errors.append(f"ai_service={payload.get('ai_service')!r}, expected {EXPECTED_AI_SERVICE!r}")

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("missing summary object")
        summary = {}
    total = summary.get("virtual_device_total")
    if total != EXPECTED_TOTAL:
        errors.append(f"summary.virtual_device_total={total!r}, expected {EXPECTED_TOTAL}")
    if summary.get("waiting") != EXPECTED_TOTAL:
        errors.append(f"summary.waiting={summary.get('waiting')!r}, expected {EXPECTED_TOTAL}")

    if "recommendations" in payload:
        errors.append("legacy recommendations list must not be present")

    virtual_device_items = payload.get("virtual_devices")
    if not isinstance(virtual_device_items, list):
        errors.append("missing virtual_devices list")
        virtual_device_items = []
    if len(virtual_device_items) != EXPECTED_TOTAL:
        errors.append(f"virtual_devices count={len(virtual_device_items)}, expected {EXPECTED_TOTAL}")

    virtual_devices = [item.get("name") for item in virtual_device_items if isinstance(item, dict)]
    if len(set(virtual_devices)) != EXPECTED_TOTAL:
        errors.append("virtual_devices must reference 15 unique names")
    states = {item.get("state") for item in virtual_device_items if isinstance(item, dict)}
    if states != {"waiting"}:
        errors.append(f"virtual_devices states={sorted(states)!r}, expected ['waiting']")

    decision = payload.get("decision")
    if not isinstance(decision, dict):
        errors.append("missing decision object")
        decision = {}
    if decision.get("ai_service") != EXPECTED_AI_SERVICE:
        errors.append(f"decision.ai_service={decision.get('ai_service')!r}, expected {EXPECTED_AI_SERVICE!r}")
    if decision.get("trigger") != "service_resource_request":
        errors.append(f"decision.trigger={decision.get('trigger')!r}, expected 'service_resource_request'")
    if decision.get("state") != "selected":
        errors.append(f"decision.state={decision.get('state')!r}, expected 'selected'")
    resources = decision.get("selected_resources")
    if not isinstance(resources, list):
        errors.append("decision.selected_resources is not a list")
        resources = []
    names = {resource.get("name") for resource in resources if isinstance(resource, dict)}
    if "vd-x86-gpu-inference" not in names:
        errors.append("decision missing vd-x86-gpu-inference")
    if "vd-storage-cache" not in names:
        errors.append("decision missing vd-storage-cache")

    return errors


def main(argv: list[str] | None = None) -> int:
    options = parse_args(list(sys.argv[1:] if argv is None else argv))
    payload = fetch_json(options.base_url)
    errors = validate_runtime_augmentation(payload)
    if errors:
        print("FAIL: runtime resource augmentation demo is not ready", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    summary = payload.get("summary", {})
    print("PASS: runtime resource augmentation demo is ready")
    print(
        "  virtual_devices={total} waiting={waiting} decision={decision} resources={resources}".format(
            total=summary.get("virtual_device_total"),
            waiting=summary.get("waiting"),
            decision=(payload.get("decision") or {}).get("state"),
            resources=len((payload.get("decision") or {}).get("selected_resources") or []),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
