#!/usr/bin/env python3
"""Validate live KubeEdge Device/DeviceModel manifests for status-plane heartbeat fields."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import sys

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal CI/edge shells
    yaml = None

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
RAW_FIELDS = {"raw", "value", "x", "y", "z", "temperature", "humidity", "vibration", "current", "voltage", "acceleration"}


def iter_docs(path: Path):
    if yaml is not None:
        with path.open() as f:
            for doc in yaml.safe_load_all(f):
                if doc:
                    yield doc
        return
    yield from iter_docs_fallback(path)


def iter_docs_fallback(path: Path):
    """Small YAML fallback for the repository's simple Device/DeviceModel manifests."""
    for raw_doc in path.read_text().split("---"):
        lines = [line.rstrip("\n") for line in raw_doc.splitlines() if line.strip()]
        if not lines:
            continue
        doc: dict[str, Any] = {"metadata": {}, "spec": {}}
        section = None
        in_properties = False
        current_prop: dict[str, Any] | None = None
        for line in lines:
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))
            if indent == 0 and stripped.startswith("kind:"):
                doc["kind"] = stripped.split(":", 1)[1].strip()
            elif indent == 0 and stripped == "metadata:":
                section = "metadata"
                in_properties = False
            elif indent == 0 and stripped == "spec:":
                section = "spec"
                in_properties = False
            elif section == "metadata" and indent == 2 and stripped.startswith("name:"):
                doc["metadata"]["name"] = stripped.split(":", 1)[1].strip().strip('"')
            elif section == "metadata" and indent == 2 and stripped.startswith("namespace:"):
                doc["metadata"]["namespace"] = stripped.split(":", 1)[1].strip().strip('"')
            elif section == "spec" and indent == 2 and stripped == "deviceModelRef:":
                doc["spec"].setdefault("deviceModelRef", {})
                in_properties = False
            elif section == "spec" and indent == 4 and stripped.startswith("name:") and "deviceModelRef" in doc["spec"] and not in_properties:
                doc["spec"]["deviceModelRef"]["name"] = stripped.split(":", 1)[1].strip().strip('"')
            elif section == "spec" and indent == 2 and stripped == "properties:":
                doc["spec"]["properties"] = []
                in_properties = True
            elif in_properties and indent == 2 and stripped.startswith("-"):
                current_prop = {}
                doc["spec"]["properties"].append(current_prop)
                rest = stripped[1:].strip()
                if rest.startswith("name:"):
                    current_prop["name"] = rest.split(":", 1)[1].strip().strip('"')
                elif rest:
                    key, _, value = rest.partition(":")
                    current_prop[key] = parse_scalar(value.strip())
            elif in_properties and current_prop is not None and indent == 4 and stripped.startswith("name:"):
                current_prop["name"] = stripped.split(":", 1)[1].strip().strip('"')
            elif in_properties and current_prop is not None and indent == 4 and stripped.startswith("reportToCloud:"):
                current_prop["reportToCloud"] = parse_scalar(stripped.split(":", 1)[1].strip())
            elif in_properties and current_prop is not None and indent == 4 and stripped == "pushMethod:":
                current_prop["pushMethod"] = {}
            elif in_properties and current_prop is not None and indent == 6 and stripped == "dbMethod:":
                current_prop.setdefault("pushMethod", {})["dbMethod"] = {}
            elif in_properties and current_prop is not None and indent == 8 and stripped.endswith(":"):
                push_method = current_prop.setdefault("pushMethod", {})
                db_method = push_method.setdefault("dbMethod", {})
                db_method[stripped[:-1]] = {}
        if doc.get("kind"):
            yield doc


def parse_scalar(value: str) -> Any:
    value = value.strip().strip('"')
    if value == "true":
        return True
    if value == "false":
        return False
    return value


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
            if field in RAW_FIELDS:
                if prop.get("reportToCloud") is not False:
                    errors.append(f"{name}.{field}: raw telemetry must keep reportToCloud=false")
                db_method = (prop.get("pushMethod") or {}).get("dbMethod") or {}
                if not db_method:
                    errors.append(f"{name}.{field}: raw telemetry should define pushMethod.dbMethod for mapper DB storage")
                elif "influxdb2" not in db_method:
                    errors.append(f"{name}.{field}: raw telemetry dbMethod should include influxdb2")

    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"OK: {len(devices)} Device manifests and {len(models)} DeviceModel manifests use status heartbeat fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
