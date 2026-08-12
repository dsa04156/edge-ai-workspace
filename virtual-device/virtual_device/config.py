from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


class ProfileValidationError(ValueError):
    """Raised when a Device Profile cannot configure a safe runtime."""


@dataclass(frozen=True)
class SerialConnectionConfig:
    port: str
    baud_rate: int
    timeout_seconds: float


@dataclass(frozen=True)
class AdapterConfig:
    type: str
    connection: SerialConnectionConfig


@dataclass(frozen=True)
class PropertyMapping:
    target: str
    value_type: str
    unit: str | None = None
    required: bool = True


@dataclass(frozen=True)
class MappingConfig:
    sensor_field: str
    device_id_field: str
    timestamp_fields: tuple[str, ...]
    properties: dict[str, PropertyMapping]


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    qos: int
    telemetry_topic: str
    status_topic: str
    keepalive_seconds: int = 60


@dataclass(frozen=True)
class OutputConfig:
    mqtt: MqttConfig


@dataclass(frozen=True)
class RuntimeConfig:
    heartbeat_seconds: float
    offline_after_seconds: float
    reconnect_backoff_seconds: float = 1.0
    reconnect_backoff_max_seconds: float = 30.0
    idle_sleep_seconds: float = 0.05


@dataclass(frozen=True)
class DeviceProfile:
    virtual_device_id: str
    physical_device_id: str
    node_id: str
    capability: str
    adapter: AdapterConfig
    mapping: MappingConfig
    output: OutputConfig
    runtime: RuntimeConfig


def load_profile(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> DeviceProfile:
    """Load a profile using CLI overrides > environment > YAML precedence."""

    profile_path = Path(path)
    try:
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileValidationError(f"profile not found: {profile_path}") from exc
    except yaml.YAMLError as exc:
        raise ProfileValidationError(f"invalid profile YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProfileValidationError("profile root must be a mapping")

    merged = copy.deepcopy(raw)
    _apply_environment(merged, os.environ if env is None else env)
    _apply_overrides(merged, overrides or {})
    return _parse_profile(merged)


def _apply_environment(raw: dict[str, Any], env: Mapping[str, str]) -> None:
    values: dict[str, str | None] = {
        "mqtt_host": _environment_value(env, "VD_MQTT_HOST", "MQTT_HOST"),
        "mqtt_port": _environment_value(env, "VD_MQTT_PORT", "MQTT_PORT"),
        "serial_port": _environment_value(env, "VD_SERIAL_PORT", "SERIAL_PORT"),
        "serial_baud_rate": _environment_value(env, "VD_SERIAL_BAUD_RATE", "BAUDRATE"),
        "serial_timeout_seconds": _environment_value(
            env,
            "VD_SERIAL_TIMEOUT_SECONDS",
            "SERIAL_TIMEOUT_SECONDS",
        ),
    }
    _apply_overrides(raw, {key: value for key, value in values.items() if value is not None})


def _environment_value(env: Mapping[str, str], primary: str, legacy: str) -> str | None:
    value = env.get(primary)
    if value not in (None, ""):
        return value
    legacy_value = env.get(legacy)
    return legacy_value if legacy_value not in (None, "") else None


def _apply_overrides(raw: dict[str, Any], overrides: Mapping[str, Any]) -> None:
    supported = {
        "mqtt_host": ("output", "mqtt", "host"),
        "mqtt_port": ("output", "mqtt", "port"),
        "serial_port": ("adapter", "connection", "port"),
        "serial_baud_rate": ("adapter", "connection", "baudRate"),
        "serial_timeout_seconds": ("adapter", "connection", "timeoutSeconds"),
    }
    unknown = sorted(set(overrides) - set(supported))
    if unknown:
        raise ProfileValidationError(f"unsupported configuration override: {', '.join(unknown)}")

    for name, value in overrides.items():
        if value is None:
            continue
        target = raw
        path = supported[name]
        for key in path[:-1]:
            child = target.get(key)
            if not isinstance(child, dict):
                child = {}
                target[key] = child
            target = child
        target[path[-1]] = value


def _parse_profile(raw: dict[str, Any]) -> DeviceProfile:
    adapter_raw = _mapping(raw.get("adapter"), "adapter")
    connection_raw = _mapping(adapter_raw.get("connection"), "adapter.connection")
    adapter_type = _text(adapter_raw.get("type"), "adapter.type")
    if adapter_type not in {"serial-json", "fake"}:
        raise ProfileValidationError("adapter.type must be serial-json or fake")

    mapping_raw = _mapping(raw.get("mapping"), "mapping")
    properties_raw = _mapping(mapping_raw.get("properties"), "mapping.properties")
    if not properties_raw:
        raise ProfileValidationError("mapping.properties must not be empty")

    properties: dict[str, PropertyMapping] = {}
    targets: set[str] = set()
    for source_name, property_value in properties_raw.items():
        source = _text(source_name, "mapping property name")
        property_raw = _mapping(property_value, f"mapping.properties.{source}")
        target = _text(property_raw.get("target"), f"mapping.properties.{source}.target")
        if target in targets:
            raise ProfileValidationError(f"duplicate mapping target: {target}")
        targets.add(target)
        value_type = _text(property_raw.get("type"), f"mapping.properties.{source}.type")
        if value_type not in {"float", "int", "string", "bool"}:
            raise ProfileValidationError(
                f"mapping.properties.{source}.type must be float, int, string, or bool"
            )
        required = property_raw.get("required", True)
        if not isinstance(required, bool):
            raise ProfileValidationError(f"mapping.properties.{source}.required must be boolean")
        unit_value = property_raw.get("unit")
        unit = None if unit_value is None else _text(unit_value, f"mapping.properties.{source}.unit")
        properties[source] = PropertyMapping(
            target=target,
            value_type=value_type,
            unit=unit,
            required=required,
        )

    timestamp_values = mapping_raw.get("timestampFields")
    if not isinstance(timestamp_values, list) or not timestamp_values:
        raise ProfileValidationError("mapping.timestampFields must be a non-empty list")
    timestamp_fields = tuple(
        _text(value, "mapping.timestampFields item") for value in timestamp_values
    )

    output_raw = _mapping(raw.get("output"), "output")
    mqtt_raw = _mapping(output_raw.get("mqtt"), "output.mqtt")
    runtime_raw = _mapping(raw.get("runtime"), "runtime")

    connection = SerialConnectionConfig(
        port=_text(connection_raw.get("port"), "adapter.connection.port"),
        baud_rate=_positive_int(connection_raw.get("baudRate"), "adapter.connection.baudRate"),
        timeout_seconds=_positive_number(
            connection_raw.get("timeoutSeconds"),
            "adapter.connection.timeoutSeconds",
        ),
    )
    mqtt = MqttConfig(
        host=_text(mqtt_raw.get("host"), "output.mqtt.host"),
        port=_port(mqtt_raw.get("port"), "output.mqtt.port"),
        qos=_qos(mqtt_raw.get("qos", 0)),
        telemetry_topic=_text(mqtt_raw.get("telemetryTopic"), "output.mqtt.telemetryTopic"),
        status_topic=_text(mqtt_raw.get("statusTopic"), "output.mqtt.statusTopic"),
        keepalive_seconds=_positive_int(
            mqtt_raw.get("keepaliveSeconds", 60),
            "output.mqtt.keepaliveSeconds",
        ),
    )
    heartbeat = _positive_number(runtime_raw.get("heartbeatSeconds"), "runtime.heartbeatSeconds")
    offline_after = _positive_number(
        runtime_raw.get("offlineAfterSeconds"),
        "runtime.offlineAfterSeconds",
    )
    if offline_after < heartbeat:
        raise ProfileValidationError("runtime.offlineAfterSeconds must be >= heartbeatSeconds")
    reconnect_backoff = _positive_number(
        runtime_raw.get("reconnectBackoffSeconds", 1),
        "runtime.reconnectBackoffSeconds",
    )
    reconnect_backoff_max = _positive_number(
        runtime_raw.get("reconnectBackoffMaxSeconds", 30),
        "runtime.reconnectBackoffMaxSeconds",
    )
    if reconnect_backoff_max < reconnect_backoff:
        raise ProfileValidationError(
            "runtime.reconnectBackoffMaxSeconds must be >= reconnectBackoffSeconds"
        )

    return DeviceProfile(
        virtual_device_id=_text(raw.get("virtualDeviceId"), "virtualDeviceId"),
        physical_device_id=_text(raw.get("physicalDeviceId"), "physicalDeviceId"),
        node_id=_text(raw.get("nodeId"), "nodeId"),
        capability=_text(raw.get("capability"), "capability"),
        adapter=AdapterConfig(type=adapter_type, connection=connection),
        mapping=MappingConfig(
            sensor_field=_text(mapping_raw.get("sensorField"), "mapping.sensorField"),
            device_id_field=_text(mapping_raw.get("deviceIdField"), "mapping.deviceIdField"),
            timestamp_fields=timestamp_fields,
            properties=properties,
        ),
        output=OutputConfig(mqtt=mqtt),
        runtime=RuntimeConfig(
            heartbeat_seconds=heartbeat,
            offline_after_seconds=offline_after,
            reconnect_backoff_seconds=reconnect_backoff,
            reconnect_backoff_max_seconds=reconnect_backoff_max,
        ),
    )


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileValidationError(f"{field_name} must be a mapping")
    return value


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ProfileValidationError(f"{field_name} must be a positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ProfileValidationError(f"{field_name} must be a positive number") from exc
    if parsed <= 0:
        raise ProfileValidationError(f"{field_name} must be a positive number")
    return parsed


def _positive_int(value: Any, field_name: str) -> int:
    number = _positive_number(value, field_name)
    if not number.is_integer():
        raise ProfileValidationError(f"{field_name} must be an integer")
    return int(number)


def _port(value: Any, field_name: str) -> int:
    port = _positive_int(value, field_name)
    if port > 65535:
        raise ProfileValidationError(f"{field_name} must be between 1 and 65535")
    return port


def _qos(value: Any) -> int:
    if isinstance(value, bool):
        raise ProfileValidationError("output.mqtt.qos must be 0, 1, or 2")
    try:
        qos = int(value)
    except (TypeError, ValueError) as exc:
        raise ProfileValidationError("output.mqtt.qos must be 0, 1, or 2") from exc
    if qos not in {0, 1, 2}:
        raise ProfileValidationError("output.mqtt.qos must be 0, 1, or 2")
    return qos
