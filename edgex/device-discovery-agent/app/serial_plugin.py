from __future__ import annotations

import json
import os
import select
import termios
import time
import tty
from pathlib import Path
from typing import Any


class SerialManifestError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


BAUD_CONSTANTS = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: getattr(termios, "B230400", termios.B115200),
}


def probe_serial_manifest(
    path: Path,
    *,
    command: str = "WHOAMI",
    baud_rate: int = 115200,
    timeout_seconds: float = 1.5,
    max_line_bytes: int = 16_384,
) -> dict[str, Any]:
    speed = BAUD_CONSTANTS.get(baud_rate)
    if speed is None:
        raise SerialManifestError(
            "SERIAL_BAUD_UNSUPPORTED",
            f"manifest probe does not support baud rate {baud_rate}",
        )
    try:
        fd = os.open(
            path,
            os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK,
        )
    except OSError as exc:
        raise SerialManifestError(
            "SERIAL_OPEN_FAILED",
            f"Serial endpoint could not be opened: {exc.__class__.__name__}",
        ) from exc
    try:
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[4] = speed
        attrs[5] = speed
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
        os.write(fd, f"{command}\n".encode("utf-8"))
        deadline = time.monotonic() + timeout_seconds
        buffer = bytearray()
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                break
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                continue
            buffer.extend(chunk)
            if len(buffer) > max_line_bytes:
                raise SerialManifestError(
                    "SERIAL_FRAME_TOO_LARGE",
                    "Manifest response exceeded the frame limit",
                )
            while b"\n" in buffer:
                raw_line, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except (UnicodeDecodeError, ValueError) as exc:
                    raise SerialManifestError(
                        "SERIAL_MANIFEST_INVALID_JSON",
                        "Manifest response was not valid JSON",
                    ) from exc
                if not isinstance(payload, dict):
                    raise SerialManifestError(
                        "SERIAL_MANIFEST_INVALID_SCHEMA",
                        "Manifest response must be a JSON object",
                    )
                if payload.get("type") != "manifest":
                    continue
                return validate_manifest(payload)
        raise SerialManifestError(
            "SERIAL_MANIFEST_TIMEOUT",
            "Manifest response timed out",
        )
    finally:
        os.close(fd)


def validate_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    device_id = payload.get("deviceId")
    model = payload.get("model")
    resources = payload.get("resources")
    firmware = payload.get("firmwareVersion")
    if not isinstance(device_id, str) or not device_id.strip():
        raise SerialManifestError(
            "SERIAL_MANIFEST_INVALID_SCHEMA",
            "Manifest deviceId is required",
        )
    if not isinstance(model, str) or not model.strip():
        raise SerialManifestError(
            "SERIAL_MANIFEST_INVALID_SCHEMA",
            "Manifest model is required",
        )
    if (
        not isinstance(resources, list)
        or not resources
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 128
            for item in resources
        )
        or len(resources) != len(set(resources))
    ):
        raise SerialManifestError(
            "SERIAL_MANIFEST_INVALID_SCHEMA",
            "Manifest resources must be a non-empty unique string array",
        )
    if firmware is not None and not isinstance(firmware, str):
        raise SerialManifestError(
            "SERIAL_MANIFEST_INVALID_SCHEMA",
            "Manifest firmwareVersion must be a string",
        )
    return {
        "type": "manifest",
        "deviceId": device_id.strip(),
        "model": model.strip(),
        "firmwareVersion": firmware.strip() if firmware else None,
        "resources": [item.strip() for item in resources],
    }
