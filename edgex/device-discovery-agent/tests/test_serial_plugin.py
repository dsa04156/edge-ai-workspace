from pathlib import Path
import time

import pytest

from app.scanner import scan_serial
from app.serial_plugin import SerialManifestError, probe_serial_manifest
from simulators.serial_arduino import ArduinoPTYSimulator


def plan():
    return {
        "enabled": True,
        "allowedVidPid": [],
        "baudRates": [115200],
        "manifestProbeEnabled": True,
        "manifestCommand": "WHOAMI",
        "manifestTimeoutSeconds": 0.8,
    }


def stable_link(tmp_path: Path, target: Path) -> tuple[Path, Path]:
    dev_root = tmp_path / "dev"
    link = dev_root / "serial" / "by-id" / "usb-Arduino-sim-001"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    return dev_root, link


def test_pty_manifest_and_telemetry_are_available(tmp_path):
    with ArduinoPTYSimulator(telemetry_interval=0.02) as simulator:
        manifest = probe_serial_manifest(
            simulator.slave_path,
            timeout_seconds=0.8,
        )
        time.sleep(0.05)

        assert manifest["deviceId"] == "arduino-sim-001"
        assert manifest["model"] == "arduino-multisensor-v1"
        assert "acceleration_x_raw" in manifest["resources"]
        assert simulator.telemetry_count > 0


def test_scanner_keeps_stable_identity_across_pty_reconnect(tmp_path):
    with ArduinoPTYSimulator(device_id="stable-arduino-001") as first:
        dev_root, link = stable_link(tmp_path, first.slave_path)
        first_result, first_errors = scan_serial(
            dev_root,
            tmp_path / "sys",
            plan(),
        )
    link.unlink()
    with ArduinoPTYSimulator(device_id="stable-arduino-001") as second:
        link.symlink_to(second.slave_path)
        second_result, second_errors = scan_serial(
            dev_root,
            tmp_path / "sys",
            plan(),
        )

    assert first_errors == second_errors == []
    assert first_result[0]["hardwareId"] == second_result[0]["hardwareId"]
    assert first_result[0]["hardwareId"] == "usb-Arduino-sim-001"
    assert first_result[0]["properties"]["ManifestDeviceID"] == (
        "stable-arduino-001"
    )
    assert first_result[0]["devicePath"] == second_result[0]["devicePath"]


@pytest.mark.parametrize(
    ("behavior", "code"),
    [
        ("invalid", "SERIAL_MANIFEST_INVALID_JSON"),
        ("silent", "SERIAL_MANIFEST_TIMEOUT"),
    ],
)
def test_manifest_invalid_and_timeout_are_explicit(behavior, code):
    with ArduinoPTYSimulator(behavior=behavior) as simulator:
        with pytest.raises(SerialManifestError) as error:
            probe_serial_manifest(
                simulator.slave_path,
                timeout_seconds=0.15,
            )

    assert error.value.code == code
