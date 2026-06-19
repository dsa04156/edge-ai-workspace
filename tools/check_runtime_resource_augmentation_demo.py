#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request
from typing import Any


JsonMap = dict[str, Any]
EXPECTED_SCOPE = "runtime_resource_augmentation_demo_v1"
EXPECTED_TOTAL = 15


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

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("missing summary object")
        summary = {}
    total = summary.get("total")
    if total != EXPECTED_TOTAL:
        errors.append(f"summary.total={total!r}, expected {EXPECTED_TOTAL}")

    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        errors.append("missing recommendations list")
        recommendations = []
    if len(recommendations) != EXPECTED_TOTAL:
        errors.append(f"recommendations count={len(recommendations)}, expected {EXPECTED_TOTAL}")

    states = {item.get("recommendation") for item in recommendations if isinstance(item, dict)}
    for required in ("none", "candidate", "selected", "blocked"):
        if required not in states:
            errors.append(f"missing recommendation state {required!r}")

    selected = [item for item in recommendations if isinstance(item, dict) and item.get("recommendation") == "selected"]
    if not selected:
        errors.append("expected at least one selected recommendation")
    for item in selected:
        resources = item.get("selected_resources")
        if not isinstance(resources, list):
            errors.append(f"{item.get('virtual_device')}: selected_resources is not a list")
            continue
        names = {resource.get("name") for resource in resources if isinstance(resource, dict)}
        if "vd-x86-gpu-inference" not in names:
            errors.append(f"{item.get('virtual_device')}: missing vd-x86-gpu-inference")
        if "vd-storage-cache" not in names:
            errors.append(f"{item.get('virtual_device')}: missing vd-storage-cache")

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
        "  total={total} selected={selected} candidate={candidate} blocked={blocked} none={none}".format(
            total=summary.get("total"),
            selected=summary.get("selected"),
            candidate=summary.get("candidate"),
            blocked=summary.get("blocked"),
            none=summary.get("none"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
