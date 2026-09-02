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
    "source",
    "profile_name",
    "device_service_name",
    "protocol_names",
    "admin_state",
    "operating_state",
    "connection_state",
    "device_service_available",
    "latest_event_timestamp",
    "latest_readings",
    "telemetry_freshness",
    "overall_status",
    "reason",
]

KPI_FIELDS = [
    "registered_device_count",
    "available_device_count",
    "degraded_device_count",
    "unavailable_device_count",
    "edgex_connected_device_count",
    "edgex_connection_ratio",
    "edgex_operating_up_count",
    "edgex_operating_down_count",
    "edgex_operating_unknown_count",
    "edgex_admin_unlocked_count",
    "edgex_admin_locked_count",
    "device_service_available_count",
    "device_service_availability_ratio",
    "core_data_event_device_count",
    "fresh_core_data_event_device_count",
    "stale_core_data_event_device_count",
    "core_data_freshness_ratio",
    "active_node_count",
    "sla_risk_workflow_count",
    "operator_focus_count",
]

EXPECTED_NODES = {
    "env-sensehat-": "etri-dev0003-raspi5",
    "imu-sensehat-": "etri-dev0003-raspi5",
    "rpi-": "etri-dev0002-raspi5",
    "env-": "etri-dev0001-jetorn",
    "vib-": "etri-dev0001-jetorn",
    "act-": "etri-dev0001-jetorn",
    "temp-": "etri-dev0001-jetorn",
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


def status_label(device: dict[str, Any]) -> str:
    return str(device.get("overall_status") or device.get("status") or "unknown")


def check_payload(payload: dict[str, Any], device_filter: str | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    kpis = payload.get("kpis") or {}
    devices = payload.get("devices") or []

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

        if device.get("source") != "edgex":
            errors.append(f"{name}: source={device.get('source')!r}, expected 'edgex'")
        if device.get("connection_state") not in {"connected", "disconnected", "unknown"}:
            errors.append(f"{name}: invalid connection_state={device.get('connection_state')!r}")
        freshness = device.get("telemetry_freshness")
        if freshness not in {"fresh", "stale", "no_events"}:
            errors.append(f"{name}: invalid telemetry_freshness={freshness!r}")
        if freshness == "fresh" and not device.get("latest_event_timestamp"):
            errors.append(f"{name}: telemetry_freshness='fresh' but latest_event_timestamp is empty")

        status = status_label(device)
        reason = str(device.get("reason") or device.get("status_reason") or "")
        if status not in {"available", "degraded", "unavailable"}:
            errors.append(f"{name}: invalid overall_status={status!r}")
        if status in {"degraded", "unavailable"} and not reason:
            errors.append(f"{name}: {status} but reason is empty")
        if status == "available" and freshness != "fresh":
            errors.append(f"{name}: available but telemetry_freshness={freshness!r}")
        if status == "available" and not device.get("device_service_available"):
            errors.append(f"{name}: available but device_service_available=false")

    focus_devices = [d for d in payload.get("devices") or [] if status_label(d) in {"degraded", "unavailable"}]
    expected_focus = len(focus_devices)
    actual_focus = kpis.get("operator_focus_count")
    if actual_focus is not None and actual_focus != expected_focus:
        errors.append(f"operator_focus_count={actual_focus}, expected degraded/unavailable devices = {expected_focus}")

    all_devices = payload.get("devices") or []
    observed_counts = {
        "registered_device_count": len(all_devices),
        "available_device_count": sum(status_label(d) == "available" for d in all_devices),
        "degraded_device_count": sum(status_label(d) == "degraded" for d in all_devices),
        "unavailable_device_count": sum(status_label(d) == "unavailable" for d in all_devices),
        "edgex_connected_device_count": sum(d.get("connection_state") == "connected" for d in all_devices),
        "device_service_available_count": sum(bool(d.get("device_service_available")) for d in all_devices),
        "core_data_event_device_count": sum(d.get("telemetry_freshness") != "no_events" for d in all_devices),
        "fresh_core_data_event_device_count": sum(d.get("telemetry_freshness") == "fresh" for d in all_devices),
        "stale_core_data_event_device_count": sum(d.get("telemetry_freshness") == "stale" for d in all_devices),
    }
    for field, observed in observed_counts.items():
        if kpis.get(field) != observed:
            warnings.append(f"{field}={kpis.get(field)}, observed={observed}")

    return errors, warnings


def print_summary(payload: dict[str, Any], device_filter: str | None) -> None:
    kpis = payload.get("kpis") or {}
    devices = payload.get("devices") or []
    if device_filter:
        devices = [d for d in devices if d.get("name") == device_filter]

    print("Dashboard API summary")
    print(f"  generated_at: {payload.get('generated_at')}")
    print(f"  registered_device_count: {kpis.get('registered_device_count')}")
    print(f"  available/degraded/unavailable: {kpis.get('available_device_count')}/{kpis.get('degraded_device_count')}/{kpis.get('unavailable_device_count')}")
    print(f"  edgex_connection_ratio: {kpis.get('edgex_connection_ratio')}")
    print(f"  device_service_availability_ratio: {kpis.get('device_service_availability_ratio')}")
    print(f"  core_data_freshness_ratio: {kpis.get('core_data_freshness_ratio')}")
    print(f"  operator_focus_count: {kpis.get('operator_focus_count')}")
    print("\nDevices")
    for device in devices[:30]:
        print(
            "  {name} node={node} status={status} profile={profile} service={service} protocols={protocols} "
            "admin={admin} operating={operating} connection={connection} freshness={freshness} reason={reason}".format(
                name=device.get("name"),
                node=device.get("node_name"),
                status=status_label(device),
                profile=device.get("profile_name"),
                service=device.get("device_service_name"),
                protocols=device.get("protocol_names"),
                admin=device.get("admin_state"),
                operating=device.get("operating_state"),
                connection=device.get("connection_state"),
                freshness=device.get("telemetry_freshness"),
                reason=device.get("reason") or device.get("status_reason"),
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000", help="state-aggregator base URL")
    parser.add_argument("--device", help="check and print one device only")
    parser.add_argument("--json", action="store_true", help="print raw /state/dashboard JSON")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    url = base_url + "/state/dashboard"
    try:
        payload = fetch_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to fetch {url}: {exc}", file=sys.stderr)
        print("If the service is in Kubernetes, run:", file=sys.stderr)
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

    print("\nPASS: required dashboard API fields are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
