#!/usr/bin/env python3
"""Small read-only Modbus TCP simulator for the EdgeX development overlay."""

from __future__ import annotations

import os
import signal
import socketserver
import struct
import threading
import time
from collections.abc import Callable


class RegisterBank:
    def __init__(
        self,
        *,
        temperature_provider: Callable[[], int] | None = None,
    ) -> None:
        self._temperature_provider = temperature_provider or self._temperature

    @staticmethod
    def _temperature() -> int:
        # Signed tenths of a degree Celsius. The deterministic 20-second wave
        # makes consecutive EdgeX Events visibly change without random input.
        return 230 + int(time.monotonic()) % 20

    def read_holding_registers(self, start: int, count: int) -> list[int]:
        if start != 0 or count != 1:
            raise IndexError("unsupported holding-register range")
        return [self._temperature_provider() & 0xFFFF]

    def read_input_registers(self, start: int, count: int) -> list[int]:
        return self.read_holding_registers(start, count)


class ModbusTCPHandler(socketserver.BaseRequestHandler):
    server: "ModbusTCPServer"

    def handle(self) -> None:
        while True:
            header = self._receive_exact(7)
            if header is None:
                return
            transaction_id, protocol_id, length, unit_id = struct.unpack(
                ">HHHB",
                header,
            )
            if protocol_id != 0 or length < 2 or length > 254:
                return
            pdu = self._receive_exact(length - 1)
            if pdu is None:
                return
            response_pdu = self._dispatch(unit_id, pdu)
            response = struct.pack(
                ">HHHB",
                transaction_id,
                0,
                len(response_pdu) + 1,
                unit_id,
            ) + response_pdu
            self.request.sendall(response)

    def _dispatch(self, unit_id: int, pdu: bytes) -> bytes:
        function = pdu[0]
        if unit_id not in self.server.unit_ids:
            return bytes((function | 0x80, 0x0B))
        if function not in (0x03, 0x04):
            return bytes((function | 0x80, 0x01))
        if len(pdu) != 5:
            return bytes((function | 0x80, 0x03))
        start, count = struct.unpack(">HH", pdu[1:])
        if count < 1 or count > 125:
            return bytes((function | 0x80, 0x03))
        try:
            if function == 0x03:
                registers = self.server.registers.read_holding_registers(
                    start,
                    count,
                )
            else:
                registers = self.server.registers.read_input_registers(
                    start,
                    count,
                )
        except IndexError:
            return bytes((function | 0x80, 0x02))
        payload = b"".join(struct.pack(">H", value) for value in registers)
        return bytes((function, len(payload))) + payload

    def _receive_exact(self, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.request.recv(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class ModbusTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        unit_id: int = 1,
        unit_ids: set[int] | None = None,
        registers: RegisterBank | None = None,
    ) -> None:
        configured_unit_ids = set(unit_ids or {unit_id})
        if not configured_unit_ids:
            raise ValueError("at least one unit ID is required")
        if any(item < 0 or item > 247 for item in configured_unit_ids):
            raise ValueError("unit IDs must be between 0 and 247")
        self.unit_ids = frozenset(configured_unit_ids)
        self.registers = registers or RegisterBank()
        super().__init__(address, ModbusTCPHandler)


def parse_unit_ids(value: str) -> set[int]:
    try:
        unit_ids = {
            int(item.strip())
            for item in value.split(",")
            if item.strip()
        }
    except ValueError as exc:
        raise ValueError(
            "MODBUS_UNIT_IDS must be a comma-separated integer list"
        ) from exc
    if not unit_ids:
        raise ValueError("MODBUS_UNIT_IDS must contain at least one unit ID")
    if any(item < 0 or item > 247 for item in unit_ids):
        raise ValueError("MODBUS_UNIT_IDS values must be between 0 and 247")
    return unit_ids


def main() -> None:
    host = os.getenv("MODBUS_LISTEN_HOST", "0.0.0.0")
    port = int(os.getenv("MODBUS_LISTEN_PORT", "1502"))
    configured_unit_ids = os.getenv("MODBUS_UNIT_IDS", "").strip()
    unit_ids = (
        parse_unit_ids(configured_unit_ids)
        if configured_unit_ids
        else {int(os.getenv("MODBUS_UNIT_ID", "1"))}
    )
    server = ModbusTCPServer((host, port), unit_ids=unit_ids)
    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        if stopped.is_set():
            return
        stopped.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
