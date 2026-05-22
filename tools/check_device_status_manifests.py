#!/usr/bin/env python3
"""Validate live KubeEdge Device/DeviceModel manifests for status-plane heartbeat fields."""
from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "edge-device" / "live"

STATUS_FIELDS = {
    "health",
    "severity",
    "online",
    "mapperLastSeen",
    "statusLastSeen",
    "statusSource",
    "last_error_code",
    "last_error_message",
}
RAW_FIELDS = {"raw", "value", "x", "y", "z", "temperature", "humidity", "vibration", "acceleration"}


def iter_docs(path: Path):
    with path.open() as f:
        for doc in yaml.safe_load_all(f):
            if doc:
                yield doc


def main() -> int:
    docs = []
    for path in sorted(LIVE_DIR.glob("*.yaml")):
        for doc in iter_docs(path):
            doc["__path"] = str(path.relative_to(ROOT))
            docs.append(doc)

    models = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "DeviceModel"}
    devices = [d for d in docs if d.get("kind") == "Device"]
    errors: list[str] = []

    for device in devices:
        name = device["metadata"]["name"]
        model_name = device["spec"]["deviceModelRef"]["name"]
        model = models.get(model_name)
        if model is None:
            errors.append(f"{name}: missing local DeviceModel manifest {model_name}")
            continue

        model_props = {p["name"] for p in model.get("spec", {}).get("properties", [])}
        missing_model = sorted(STATUS_FIELDS - model_props)
        if missing_model:
            errors.append(f"{model_name}: missing status properties {missing_model}")

        props = {p["name"]: p for p in device.get("spec", {}).get("properties", [])}
        missing_device = sorted(STATUS_FIELDS - set(props))
        if missing_device:
            errors.append(f"{name}: missing status properties {missing_device}")

        if "received_at" in props:
            errors.append(f"{name}: received_at must not be reported as DeviceStatus")

        for field in STATUS_FIELDS:
            prop = props.get(field)
            if not prop:
                continue
            if prop.get("reportToCloud") is not True:
                errors.append(f"{name}.{field}: reportToCloud must be true")
            if "pushMethod" in prop:
                errors.append(f"{name}.{field}: status heartbeat field must not have pushMethod")

        for field, prop in props.items():
            if field in RAW_FIELDS and prop.get("reportToCloud") is not False:
                errors.append(f"{name}.{field}: raw telemetry must keep reportToCloud=false")

    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"OK: {len(devices)} Device manifests and {len(models)} DeviceModel manifests use status heartbeat fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
