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
    total = summary.get("candidate_resource_total")
    if total != EXPECTED_TOTAL:
        errors.append(f"summary.candidate_resource_total={total!r}, expected {EXPECTED_TOTAL}")
    if summary.get("available", 0) < 1:
        errors.append("summary.available must be greater than 0")

    if "recommendations" in payload:
        errors.append("legacy recommendations list must not be present")
    if "virtual_devices" in payload:
        errors.append("legacy virtual_devices waiting pool must not be present")

    candidate_items = payload.get("candidate_resources")
    if not isinstance(candidate_items, list):
        errors.append("missing candidate_resources list")
        candidate_items = []
    if len(candidate_items) != EXPECTED_TOTAL:
        errors.append(f"candidate_resources count={len(candidate_items)}, expected {EXPECTED_TOTAL}")

    candidates = [item.get("name") for item in candidate_items if isinstance(item, dict)]
    if len(set(candidates)) != EXPECTED_TOTAL:
        errors.append("candidate_resources must reference 15 unique names")
    kinds = {item.get("kind") for item in candidate_items if isinstance(item, dict)}
    for required in ("gpu-inference", "storage-cache", "model-cache"):
        if required not in kinds:
            errors.append(f"missing candidate resource kind {required!r}")

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
    candidate_names = decision.get("candidate_resource_names")
    if not isinstance(candidate_names, list) or not candidate_names:
        errors.append("decision.candidate_resource_names must be a non-empty list")
    resources = decision.get("selected_resources")
    if not isinstance(resources, list):
        errors.append("decision.selected_resources is not a list")
        resources = []
    names = {resource.get("name") for resource in resources if isinstance(resource, dict)}
    if "vd-x86-gpu-inference" not in names:
        errors.append("decision missing vd-x86-gpu-inference")
    if "vd-storage-cache" not in names:
        errors.append("decision missing vd-storage-cache")
    candidate_name_set = set(candidates)
    for name in names:
        if name not in candidate_name_set:
            errors.append(f"selected resource {name!r} is not present in candidate_resources")
    augmented_device = decision.get("resulting_augmented_device")
    if not isinstance(augmented_device, dict):
        errors.append("missing decision.resulting_augmented_device object")
        augmented_device = {}
    if augmented_device.get("name") != "ad-jetorn-inspection-001":
        errors.append(f"resulting_augmented_device.name={augmented_device.get('name')!r}, expected 'ad-jetorn-inspection-001'")
    if augmented_device.get("target_device") != "etri-dev0001-jetorn":
        errors.append(f"resulting_augmented_device.target_device={augmented_device.get('target_device')!r}, expected 'etri-dev0001-jetorn'")

    workflow = payload.get("workflow_demo")
    if not isinstance(workflow, dict):
        errors.append("missing workflow_demo object")
        workflow = {}
    if workflow.get("status") != "offload_planned":
        errors.append(f"workflow_demo.status={workflow.get('status')!r}, expected 'offload_planned'")
    steps = workflow.get("steps")
    if not isinstance(steps, list):
        errors.append("workflow_demo.steps is not a list")
        steps = []
    step_ids = [step.get("id") for step in steps if isinstance(step, dict)]
    for required in ("service-request", "pressure-detected", "candidate-scan", "offload-plan", "augmented-device-bind"):
        if required not in step_ids:
            errors.append(f"missing workflow step {required!r}")
    offload_path = workflow.get("offload_path")
    if not isinstance(offload_path, dict):
        errors.append("missing workflow_demo.offload_path object")
        offload_path = {}
    expected_path = {
        "source": "etri-dev0001-jetorn",
        "inference": "vd-x86-gpu-inference",
        "cache": "vd-storage-cache",
        "result": "ad-jetorn-inspection-001",
    }
    for key, expected in expected_path.items():
        if offload_path.get(key) != expected:
            errors.append(f"workflow_demo.offload_path.{key}={offload_path.get(key)!r}, expected {expected!r}")

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
        "  candidates={total} available={available} decision={decision} resources={resources} augmented_device={augmented_device} workflow={workflow}".format(
            total=summary.get("candidate_resource_total"),
            available=summary.get("available"),
            decision=(payload.get("decision") or {}).get("state"),
            resources=len((payload.get("decision") or {}).get("selected_resources") or []),
            augmented_device=((payload.get("decision") or {}).get("resulting_augmented_device") or {}).get("name"),
            workflow=(payload.get("workflow_demo") or {}).get("status"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
