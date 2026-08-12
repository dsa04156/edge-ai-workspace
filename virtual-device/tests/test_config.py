from __future__ import annotations

from pathlib import Path

import pytest

from virtual_device.config import ProfileValidationError, load_profile


VALID_PROFILE = """
virtualDeviceId: etri-vd0001-vibration
physicalDeviceId: etri-pd0001-arduino
nodeId: etri-dev0001-jetorn
capability: vibration

adapter:
  type: serial-json
  connection:
    port: /dev/ttyACM0
    baudRate: 115200
    timeoutSeconds: 2

mapping:
  sensorField: sensor
  deviceIdField: device_id
  timestampFields: [source_ts, ts, timestamp]
  properties:
    x: {target: acceleration_x, type: float, unit: g}
    y: {target: acceleration_y, type: float, unit: g}
    z: {target: acceleration_z, type: float, unit: g}

output:
  mqtt:
    host: 127.0.0.1
    port: 1883
    qos: 0
    telemetryTopic: edge/virtual-devices/etri-vd0001-vibration/telemetry
    statusTopic: edge/virtual-devices/etri-vd0001-vibration/status

runtime:
  heartbeatSeconds: 10
  offlineAfterSeconds: 30
"""


def write_profile(tmp_path: Path, text: str = VALID_PROFILE) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_profile_yaml_is_loaded_and_validated(tmp_path: Path) -> None:
    profile = load_profile(write_profile(tmp_path))

    assert profile.virtual_device_id == "etri-vd0001-vibration"
    assert profile.capability == "vibration"
    assert profile.adapter.connection.baud_rate == 115200
    assert profile.mapping.properties["x"].target == "acceleration_x"
    assert profile.output.mqtt.telemetry_topic.endswith("/telemetry")
    assert profile.runtime.heartbeat_seconds == 10


def test_profile_rejects_missing_required_identity(tmp_path: Path) -> None:
    invalid = VALID_PROFILE.replace("virtualDeviceId: etri-vd0001-vibration\n", "")

    with pytest.raises(ProfileValidationError, match="virtualDeviceId"):
        load_profile(write_profile(tmp_path, invalid))


def test_profile_rejects_duplicate_mapping_targets(tmp_path: Path) -> None:
    invalid = VALID_PROFILE.replace("target: acceleration_y", "target: acceleration_x")

    with pytest.raises(ProfileValidationError, match="mapping target"):
        load_profile(write_profile(tmp_path, invalid))


def test_cli_overrides_environment_and_environment_overrides_yaml(tmp_path: Path) -> None:
    profile = load_profile(
        write_profile(tmp_path),
        env={
            "VD_MQTT_HOST": "env-broker",
            "VD_SERIAL_PORT": "/dev/env-serial",
        },
        overrides={
            "mqtt_host": "cli-broker",
            "serial_port": "/dev/cli-serial",
        },
    )

    assert profile.output.mqtt.host == "cli-broker"
    assert profile.adapter.connection.port == "/dev/cli-serial"


def test_environment_overrides_yaml_when_cli_value_is_absent(tmp_path: Path) -> None:
    profile = load_profile(
        write_profile(tmp_path),
        env={
            "VD_MQTT_PORT": "2883",
            "VD_SERIAL_BAUD_RATE": "57600",
            "VD_SERIAL_TIMEOUT_SECONDS": "1.5",
        },
    )

    assert profile.output.mqtt.port == 2883
    assert profile.adapter.connection.baud_rate == 57600
    assert profile.adapter.connection.timeout_seconds == 1.5
