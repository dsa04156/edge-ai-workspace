from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Sample:
    device_id: str
    sensor: str
    value: Any
    edge_node: str
    topic: str
    timestamp_ms: int
    received_at_ms: int
    schema_version: str = "1"


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_mqtt_message(topic: str, payload_bytes: bytes, received_at_ms: int | None = None) -> list[Sample]:
    received_at = received_at_ms if received_at_ms is not None else now_ms()
    payload = json.loads(payload_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        return []

    timestamp_ms = _coerce_timestamp_ms(payload.get("timestamp") or payload.get("source_ts"), received_at)
    device_id, default_sensor, edge_node = _device_sensor_from_topic(topic, payload)

    samples: list[Sample] = []
    axis_fields = [axis for axis in ("x", "y", "z") if axis in payload]
    if axis_fields:
        for axis in axis_fields:
            samples.append(Sample(device_id, axis, payload[axis], edge_node, topic, timestamp_ms, received_at))
        return samples

    sensor = str(payload.get("sensor") or default_sensor or "value")
    value = payload.get("value", payload.get(sensor, payload.get("raw")))
    if value is None:
        return []
    return [Sample(device_id, sensor, value, edge_node, topic, timestamp_ms, received_at)]


def _device_sensor_from_topic(topic: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    factory_match = re.match(r"^factory/devices/([^/]+)/telemetry$", topic)
    if factory_match:
        return (
            str(payload.get("device_id") or factory_match.group(1)),
            str(payload.get("sensor") or "value"),
            str(payload.get("edge_node") or "unknown"),
        )

    parts = topic.split("/")
    if len(parts) >= 4 and parts[0] == "etri":
        edge_node = str(payload.get("edge_node") or parts[1])
        sensor_unit = parts[2]
        sensor = parts[3]
        device_id = str(payload.get("device_id") or f"{sensor_unit}-{sensor}")
        return device_id, sensor, edge_node

    return (
        str(payload.get("device_id") or "unknown-device"),
        str(payload.get("sensor") or "value"),
        str(payload.get("edge_node") or "unknown"),
    )


def _coerce_timestamp_ms(value: Any, fallback_ms: int) -> int:
    if value is None or value == "":
        return fallback_ms
    numeric = float(value)
    # Treat 10-digit values as epoch seconds; 13-digit values as epoch ms.
    if numeric < 10_000_000_000:
        numeric *= 1000
    return int(numeric)


def to_redis_stream_fields(sample: Sample) -> dict[str, str]:
    return {
        "device_id": sample.device_id,
        "sensor": sample.sensor,
        "value": str(sample.value),
        "edge_node": sample.edge_node,
        "topic": sample.topic,
        "timestamp": str(sample.timestamp_ms),
        "received_at": str(sample.received_at_ms),
        "schema_version": sample.schema_version,
    }


def to_redis_latest_record(sample: Sample, prefix: str = "telemetry:latest") -> tuple[str, dict[str, str]]:
    return f"{prefix}:{sample.device_id}:{sample.sensor}", to_redis_stream_fields(sample)


def to_line_protocol(sample: Sample, measurement: str = "raw_sensor_telemetry") -> str:
    tags = {
        "device_id": sample.device_id,
        "sensor": sample.sensor,
        "edge_node": sample.edge_node,
        "source": "mqtt",
        "schema_version": sample.schema_version,
    }
    tag_text = ",".join(f"{_escape_tag(k)}={_escape_tag(v)}" for k, v in tags.items())
    value = _field_value(sample.value)
    timestamp_ns = sample.timestamp_ms * 1_000_000
    return f"{_escape_measurement(measurement)},{tag_text} value={value} {timestamp_ns}"


def _field_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    try:
        float(text)
        return text
    except ValueError:
        return '"' + text.replace('"', '\\"') + '"'


def _escape_measurement(value: str) -> str:
    return value.replace(" ", r"\ ").replace(",", r"\,")


def _escape_tag(value: Any) -> str:
    return str(value).replace(" ", r"\ ").replace(",", r"\,").replace("=", r"\=")
