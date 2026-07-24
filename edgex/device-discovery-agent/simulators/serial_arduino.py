from __future__ import annotations

import argparse
import json
import os
import select
import signal
import threading
import time
from pathlib import Path
from typing import Literal


class ArduinoPTYSimulator:
    def __init__(
        self,
        *,
        device_id: str = "arduino-sim-001",
        model: str = "arduino-multisensor-v1",
        behavior: Literal["valid", "invalid", "silent", "unsupported"] = "valid",
        telemetry_interval: float = 0.2,
    ) -> None:
        self.device_id = device_id
        self.model = model
        self.behavior = behavior
        self.telemetry_interval = telemetry_interval
        self.master_fd, self.slave_fd = os.openpty()
        self.slave_path = Path(os.ttyname(self.slave_fd))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.telemetry_count = 0

    def start(self) -> "ArduinoPTYSimulator":
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        for fd in (self.master_fd, self.slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def __enter__(self) -> "ArduinoPTYSimulator":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()

    def _run(self) -> None:
        command_buffer = bytearray()
        next_telemetry = time.monotonic() + self.telemetry_interval
        while not self._stop.is_set():
            timeout = max(0.0, next_telemetry - time.monotonic())
            readable, _, _ = select.select(
                [self.master_fd],
                [],
                [],
                min(timeout, 0.1),
            )
            if readable:
                try:
                    command_buffer.extend(os.read(self.master_fd, 4096))
                except OSError:
                    return
                while b"\n" in command_buffer:
                    raw, _, rest = command_buffer.partition(b"\n")
                    command_buffer = bytearray(rest)
                    if raw.strip() == b"WHOAMI":
                        self._send_manifest()
            if time.monotonic() >= next_telemetry:
                self._send_telemetry()
                next_telemetry = time.monotonic() + self.telemetry_interval

    def _send_manifest(self) -> None:
        if self.behavior == "silent":
            return
        if self.behavior == "invalid":
            os.write(self.master_fd, b'{"type":"manifest","deviceId":\n')
            return
        model = (
            "unsupported-board-v9"
            if self.behavior == "unsupported"
            else self.model
        )
        payload = {
            "type": "manifest",
            "deviceId": self.device_id,
            "model": model,
            "firmwareVersion": "1.0.0-sim",
            "resources": [
                "temperature_raw",
                "light_raw",
                "magnetic_raw",
                "acceleration_x_raw",
                "acceleration_y_raw",
                "acceleration_z_raw",
            ],
        }
        self._write_json(payload)

    def _send_telemetry(self) -> None:
        self.telemetry_count += 1
        offset = self.telemetry_count % 20
        samples = [
            {
                "device_id": self.device_id,
                "sensor": "temperature",
                "raw": 300 + offset,
            },
            {
                "device_id": self.device_id,
                "sensor": "light",
                "value": 500 + offset,
            },
            {
                "device_id": self.device_id,
                "sensor": "magnetic",
                "value": offset % 2,
            },
            {
                "device_id": self.device_id,
                "sensor": "acceleration",
                "x": 280 + offset,
                "y": 282 + offset,
                "z": 284 + offset,
            },
        ]
        for sample in samples:
            self._write_json(sample)

    def _write_json(self, payload: dict[str, object]) -> None:
        try:
            os.write(
                self.master_fd,
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
                + b"\n",
            )
        except OSError:
            self._stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pseudo-terminal Arduino discovery simulator"
    )
    parser.add_argument("--device-id", default="arduino-sim-001")
    parser.add_argument("--model", default="arduino-multisensor-v1")
    parser.add_argument(
        "--behavior",
        choices=["valid", "invalid", "silent", "unsupported"],
        default="valid",
    )
    parser.add_argument("--link", type=Path)
    args = parser.parse_args()
    simulator = ArduinoPTYSimulator(
        device_id=args.device_id,
        model=args.model,
        behavior=args.behavior,
    ).start()
    if args.link:
        args.link.parent.mkdir(parents=True, exist_ok=True)
        args.link.unlink(missing_ok=True)
        args.link.symlink_to(simulator.slave_path)
    print(simulator.slave_path, flush=True)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.wait(1):
            pass
    finally:
        simulator.close()
        if args.link:
            args.link.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
