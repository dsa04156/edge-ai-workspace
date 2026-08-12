from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..config import SerialConnectionConfig
from .base import Adapter, AdapterConnectionError, AdapterHealth, InvalidSampleError


class SerialJsonAdapter(Adapter):
    def __init__(
        self,
        connection: SerialConnectionConfig,
        *,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.connection = connection
        self._serial_factory = serial_factory
        self._serial: Any | None = None
        self._health = AdapterHealth()

    def start(self) -> None:
        if self._serial is not None:
            return
        factory = self._serial_factory or _pyserial_factory()
        try:
            self._serial = factory(
                port=self.connection.port,
                baudrate=self.connection.baud_rate,
                timeout=self.connection.timeout_seconds,
            )
        except Exception as exc:
            self._health = AdapterHealth(connection="disconnected", last_error=str(exc))
            raise AdapterConnectionError(str(exc)) from exc
        self._health = AdapterHealth(connection="connected")

    def read(self) -> dict[str, Any] | None:
        if self._serial is None:
            raise AdapterConnectionError("serial adapter is not started")
        try:
            raw = self._serial.readline()
        except Exception as exc:
            self._health = AdapterHealth(connection="disconnected", last_error=str(exc))
            raise AdapterConnectionError(str(exc)) from exc

        if not raw:
            return None
        try:
            line = raw.decode("utf-8").strip() if isinstance(raw, bytes) else str(raw).strip()
            decoded = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            message = f"invalid JSON sample: {exc}"
            self._health = AdapterHealth(connection="connected", last_error=message)
            raise InvalidSampleError(message) from exc

        if not isinstance(decoded, dict):
            message = "invalid JSON sample: root must be an object"
            self._health = AdapterHealth(connection="connected", last_error=message)
            raise InvalidSampleError(message)

        self._health = AdapterHealth(connection="connected")
        return decoded

    def health(self) -> AdapterHealth:
        return self._health

    def stop(self) -> None:
        serial_connection = self._serial
        self._serial = None
        if serial_connection is not None:
            try:
                serial_connection.close()
            except Exception as exc:
                self._health = AdapterHealth(connection="disconnected", last_error=str(exc))
                return
        self._health = AdapterHealth(connection="disconnected")


def _pyserial_factory() -> Callable[..., Any]:
    try:
        import serial
    except ImportError as exc:
        raise AdapterConnectionError(
            "pyserial is required for the serial-json adapter; install the project dependencies"
        ) from exc
    return serial.Serial
