#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Sequence


DEFAULT_DEVICE_ID = "sensehat-001"
DEFAULT_INTERVAL = 1.0
DEFAULT_SETTINGS = "/etc/RTIMULib.ini"
DEFAULT_RUNTIME_SETTINGS = "/tmp/RTIMULib"
IMU_WARMUP_SECONDS = 2.0


def positive_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("interval must be a positive finite number")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read Sense HAT v1 sensors as JSON lines")
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--interval", type=positive_float, default=DEFAULT_INTERVAL)
    parser.add_argument("--settings", default=DEFAULT_SETTINGS)
    parser.add_argument("--runtime-settings", default=DEFAULT_RUNTIME_SETTINGS)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def degrees(radians: float) -> float:
    return math.degrees(float(radians)) % 360.0


def _valid_pair(values: Sequence[Any], name: str) -> tuple[float, float]:
    if len(values) < 4 or not bool(values[0]) or not bool(values[2]):
        raise ValueError(f"{name} reading is invalid")
    return float(values[1]), float(values[3])


def _vector(values: Any, name: str) -> tuple[float, float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError(f"{name} vector is invalid")
    return float(values[0]), float(values[1]), float(values[2])


def build_sample(
    device_id: str,
    origin: int,
    pressure: Sequence[Any],
    humidity: Sequence[Any],
    imu: dict[str, Any],
) -> dict[str, Any]:
    pressure_hpa, temp_pressure = _valid_pair(pressure, "pressure")
    humidity_percent, temp_humidity = _valid_pair(humidity, "humidity")
    if not bool(imu.get("fusionPoseValid")) or not bool(imu.get("gyroValid")):
        raise ValueError("IMU reading is invalid")

    roll_raw, pitch_raw, yaw_raw = _vector(imu.get("fusionPose"), "fusionPose")
    gyro_x, gyro_y, gyro_z = _vector(imu.get("gyro"), "gyro")
    roll = degrees(roll_raw)
    pitch = degrees(pitch_raw)
    yaw = degrees(yaw_raw)

    sample: dict[str, Any] = {
        "device_id": str(device_id),
        "origin": int(origin),
        "temp_humidity": temp_humidity,
        "temp_pressure": temp_pressure,
        "humidity": humidity_percent,
        "pressure": pressure_hpa,
        "compass": yaw,
        "pitch": pitch,
        "roll": roll,
        "yaw": yaw,
        "gyro_x": gyro_x,
        "gyro_y": gyro_y,
        "gyro_z": gyro_z,
    }
    numeric_values = [value for key, value in sample.items() if key not in {"device_id"}]
    if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in numeric_values):
        raise ValueError("sample values must be finite")
    if sample["origin"] <= 0:
        raise ValueError("sample origin must be positive")
    return sample


def prepare_settings(source: str, runtime_base: str) -> str:
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"RTIMULib settings file is unavailable: {source}")
    runtime_path = Path(f"{runtime_base}.ini")
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, runtime_path)
    return runtime_base


class RTIMUSource:
    def __init__(self, rtimu: Any, settings_base: str) -> None:
        self._settings = rtimu.Settings(settings_base)
        self._imu = rtimu.RTIMU(self._settings)
        if not self._imu.IMUInit():
            raise OSError("Sense HAT IMU initialization failed")
        self._imu.setCompassEnable(True)
        self._imu.setGyroEnable(True)
        self._imu.setAccelEnable(True)
        self._poll_interval = max(float(self._imu.IMUGetPollInterval()) / 1000.0, 0.001)
        if not self._wait_for_imu():
            raise OSError("Sense HAT IMU priming failed")
        self._pressure = rtimu.RTPressure(self._settings)
        if not self._pressure.pressureInit():
            raise OSError("Sense HAT pressure initialization failed")
        self._humidity = rtimu.RTHumidity(self._settings)
        if not self._humidity.humidityInit():
            raise OSError("Sense HAT humidity initialization failed")

    def _wait_for_imu(self) -> bool:
        imu_valid = False
        attempts = max(3, math.ceil(IMU_WARMUP_SECONDS / self._poll_interval))
        for _ in range(attempts):
            imu_valid = bool(self._imu.IMURead())
            if imu_valid:
                break
            time.sleep(self._poll_interval)
        return imu_valid

    def read(self, device_id: str) -> dict[str, Any]:
        if not self._wait_for_imu():
            raise OSError("Sense HAT IMU read failed")
        return build_sample(
            device_id=device_id,
            origin=time.time_ns(),
            pressure=self._pressure.pressureRead(),
            humidity=self._humidity.humidityRead(),
            imu=self._imu.getIMUData(),
        )


def run(args: argparse.Namespace) -> int:
    if not str(args.device_id).strip():
        raise ValueError("device-id must not be empty")
    settings_base = prepare_settings(args.settings, args.runtime_settings)
    import RTIMU  # type: ignore[import-not-found]

    source = RTIMUSource(RTIMU, settings_base)
    while True:
        started = time.monotonic()
        print(
            json.dumps(source.read(args.device_id), separators=(",", ":"), allow_nan=False),
            flush=True,
        )
        if args.once:
            return 0
        remaining = args.interval - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"sensehat reader error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
