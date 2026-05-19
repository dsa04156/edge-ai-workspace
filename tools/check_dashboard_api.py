#!/usr/bin/env python3
"""Read-only state-aggregator dashboard API checker.

This helper validates the fields needed by the E2E telemetry/dashboard runbook.
It does not call any mutating Kubernetes, MQTT, or actuator command.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

DEVICE_FIELDS = [
    "name",
    "node_name",
    "device_type",
    "telemetry_enabled",
    "telemetry_fresh",
    "telemetry_last_seen_at",
    "telemetry_property",
    "device_status_fresh",
    "mapper_running",
    "node_ready",
    "overall_status",
    "reason",
    "service_demo_group",
    "service_connected",
]

KPI_FIELDS = [
    "registered_device_count",
    "live_device_count",
    "telemetry_device_count",
    "device_telemetry_ratio",
    "fresh_telemetry_device_count",
    "telemetry_freshness_ratio",
    "fresh_device_status_count",
    "device_status_freshness_ratio",
    "operator_focus_count",
    "service_bound_device_count",
    "device_service_binding_ratio",
]

EXPECTED_NODES = {
    "rpi-": "etri-dev0002-raspi5",
    "env-": "etri-dev0001-jetorn",
    "vib-": "etri-dev0001-jetorn",
    "act-": "etri-dev0001-jetorn",
    "temp-": "etri-dev0001-jetorn",
}

SERVICE_GROUP_HINTS = {
    "env": ["환경 상태 모니터링"],
    "temp": ["환경 상태 모니터링"],
    "vib": ["설비 상태 모니터링", "설비/진동 상태 모니터링"],
    "act": ["command 상태 확인"],
}


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def expected_node(name: str) -> str | None:
    if name.startswith("rpi-"):
        return "etri-dev0002-raspi5"
    for prefix, node in EXPECTED_NODES.items():
        if name.startswith(prefix):
            return node
    return None


def expected_service_hints(name: str) -> list[str]:
    low = name.lower()
    for key, values in SERVICE_GROUP_HINTS.items():
        if key in low:
            return values
    return []


def status_label(device: dict[str, Any]) -> str:
    return str(device.get("overall_status") or device.get("status") or "unknown")


def check_payload(payload: dict[str, Any], device_filter: str | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    kpis = payload.get("kpis") or {}
    devices = payload.get("devices") or []
    nodes = payload.get("nodes") or []

    for field in KPI_FIELDS:
        if field not in kpis:
            errors.append(f"missing KPI field: kpis.{field}")

    if device_filter:
        devices = [d for d in devices if d.get("name") == device_filter]
        if not devices:
            errors.append(f"device not found: {device_filter}")
            return errors, warnings

    for device in devices:
        name = str(device.get("name") or "<unknown>")
        for field in DEVICE_FIELDS:
            if field not in device:
                errors.append(f"{name}: missing device field devices[].{field}")

        node = device.get("node_name")
        want_node = expected_node(name)
        if want_node and node != want_node:
            warnings.append(f"{name}: node_name={node!r}, expected={want_node!r}")

        if not device.get("service_connected"):
            warnings.append(f"{name}: service_connected=false")
        elif not device.get("service_demo_group"):
            warnings.append(f"{name}: service_connected=true but service_demo_group is empty")

        hints = expected_service_hints(name)
        group = str(device.get("service_demo_group") or "")
        if hints and group and not any(hint in group for hint in hints):
            warnings.append(f"{name}: service_demo_group={group!r}, expected one of={hints!r}")

        if device.get("telemetry_enabled"):
            if not device.get("telemetry_fresh"):
                warnings.append(f"{name}: telemetry_enabled=true but telemetry_fresh=false; reason={device.get('reason') or device.get('status_reason')}")
            if not device.get("telemetry_property"):
                warnings.append(f"{name}: telemetry_property is empty")

        if "act" in name and device.get("telemetry_enabled") and device.get("telemetry_property") not in (None, "health"):
            warnings.append(f"{name}: act/rpi-act telemetry_property={device.get('telemetry_property')!r}; current liveness property should be health")

        status = status_label(device)
        reason = str(device.get("reason") or device.get("status_reason") or "")
        if status in {"degraded", "unavailable"} and not reason:
            errors.append(f"{name}: {status} but reason is empty")
        if device.get("mapper_running") is False and "mapper" not in reason.lower():
            warnings.append(f"{name}: mapper_running=false but reason does not mention mapper: {reason!r}")
        if device.get("node_ready") is False and "node" not in reason.lower():
            warnings.append(f"{name}: node_ready=false but reason does not mention node: {reason!r}")

    focus_devices = [d for d in payload.get("devices") or [] if status_label(d) in {"degraded", "unavailable"}]
    focus_nodes = [n for n in nodes if n.get("node_health") != "healthy"]
    expected_focus = len(focus_devices) + len(focus_nodes)
    actual_focus = kpis.get("operator_focus_count")
    if actual_focus is not None and actual_focus != expected_focus:
        errors.append(f"operator_focus_count={actual_focus}, expected degraded/unavailable devices + non-healthy nodes = {expected_focus}")

    telemetry_devices = [d for d in payload.get("devices") or [] if d.get("telemetry_enabled")]
    fresh_telemetry = [d for d in telemetry_devices if d.get("telemetry_fresh")]
    if kpis.get("telemetry_device_count") != len(telemetry_devices):
        warnings.append(f"telemetry_device_count={kpis.get('telemetry_device_count')}, observed={len(telemetry_devices)}")
    if kpis.get("fresh_telemetry_device_count") != len(fresh_telemetry):
        warnings.append(f"fresh_telemetry_device_count={kpis.get('fresh_telemetry_device_count')}, observed={len(fresh_telemetry)}")

    return errors, warnings


def print_summary(payload: dict[str, Any], device_filter: str | None) -> None:
    kpis = payload.get("kpis") or {}
    devices = payload.get("devices") or []
    if device_filter:
        devices = [d for d in devices if d.get("name") == device_filter]

    print("Dashboard API summary")
    print(f"  generated_at: {payload.get('generated_at')}")
    print(f"  registered_device_count: {kpis.get('registered_device_count')}")
    print(f"  live_device_count: {kpis.get('live_device_count')}")
    print(f"  telemetry configured ratio(device_telemetry_ratio): {kpis.get('device_telemetry_ratio')}")
    print(f"  telemetry_freshness_ratio: {kpis.get('telemetry_freshness_ratio')}")
    print(f"  device_status_freshness_ratio: {kpis.get('device_status_freshness_ratio')}")
    print(f"  operator_focus_count: {kpis.get('operator_focus_count')}")
    print(f"  service_bound_device_count: {kpis.get('service_bound_device_count')}")
    print(f"  device_service_binding_ratio: {kpis.get('device_service_binding_ratio')}")
    print("\nDevices")
    for device in devices[:30]:
        print(
            "  {name} node={node} status={status} telemetry_enabled={ten} telemetry_fresh={tf} "
            "property={prop} DeviceStatus={ds} mapper={mapper} node_ready={nr} service={svc} reason={reason}".format(
                name=device.get("name"),
                node=device.get("node_name"),
                status=status_label(device),
                ten=device.get("telemetry_enabled"),
                tf=device.get("telemetry_fresh"),
                prop=device.get("telemetry_property"),
                ds="fresh" if device.get("device_status_fresh") else "stale",
                mapper=device.get("mapper_running"),
                nr=device.get("node_ready"),
                svc=device.get("service_demo_group"),
                reason=device.get("reason") or device.get("status_reason"),
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000", help="state-aggregator base URL")
    parser.add_argument("--device", help="check and print one device only")
    parser.add_argument("--json", action="store_true", help="print raw /state/dashboard JSON")
    args = parser.parse_args()

    url = args.base_url.rstrip("/") + "/state/dashboard"
    try:
        payload = fetch_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to fetch {url}: {exc}", file=sys.stderr)
        print("If the service is in Kubernetes, run one of:", file=sys.stderr)
        print("  kubectl -n edge-orch port-forward svc/state-aggregator 8000:80", file=sys.stderr)
        print("  kubectl -n default port-forward svc/state-aggregator 8000:8000", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    print_summary(payload, args.device)
    errors, warnings = check_payload(payload, args.device)

    if warnings:
        print("\nWARN")
        for item in warnings:
            print(f"  - {item}")
    if errors:
        print("\nFAIL")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("\nPASS: required dashboard API fields and KPI semantics are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
