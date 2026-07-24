from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Any, Protocol


I2C_SLAVE = 0x0703


class I2CProbeError(RuntimeError):
    pass


class I2CBusAdapter(Protocol):
    def read_identity_register(
        self,
        bus_path: Path,
        *,
        address: int,
        register: int,
    ) -> int: ...


class LinuxI2CBusAdapter:
    def read_identity_register(
        self,
        bus_path: Path,
        *,
        address: int,
        register: int,
    ) -> int:
        try:
            fd = os.open(bus_path, os.O_RDWR | os.O_CLOEXEC)
        except OSError as exc:
            raise I2CProbeError(
                f"I2C bus open failed: {exc.__class__.__name__}"
            ) from exc
        try:
            fcntl.ioctl(fd, I2C_SLAVE, address)
            os.write(fd, bytes([register]))
            value = os.read(fd, 1)
            if len(value) != 1:
                raise I2CProbeError("I2C identity read returned no byte")
            return value[0]
        except OSError as exc:
            raise I2CProbeError(
                f"I2C identity read failed: {exc.__class__.__name__}"
            ) from exc
        finally:
            os.close(fd)


class MockI2CBusAdapter:
    def __init__(self, values: dict[tuple[str, int, int], int]) -> None:
        self.values = values
        self.calls: list[tuple[str, int, int]] = []

    def read_identity_register(
        self,
        bus_path: Path,
        *,
        address: int,
        register: int,
    ) -> int:
        key = (str(bus_path), address, register)
        self.calls.append(key)
        if key not in self.values:
            raise I2CProbeError("mock I2C endpoint did not respond")
        return self.values[key]


def identify_i2c_devices(
    bus_path: Path,
    rules: list[dict[str, Any]],
    *,
    adapter: I2CBusAdapter,
    allowed_addresses: set[int],
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for rule in rules:
        address = int(str(rule["address"]), 16)
        if address not in allowed_addresses:
            continue
        register = int(str(rule["register"]), 16)
        expected = int(str(rule["expected"]), 16)
        try:
            observed = adapter.read_identity_register(
                bus_path,
                address=address,
                register=register,
            )
        except I2CProbeError as exc:
            errors.append(
                f"I2C 0x{address:02x} identification failed: {exc}"
            )
            continue
        if observed != expected:
            continue
        bus = bus_path.name.removeprefix("i2c-")
        model = str(rule["model"])
        profile = str(rule["profile"])
        capabilities = list(rule.get("capabilities") or [])
        candidates.append(
            {
                "hardwareKey": (
                    f"i2c:{bus}:0x{address:02x}:"
                    f"{model}:0x{observed:02x}"
                ),
                "hardwareId": (
                    f"bus-{bus}-address-0x{address:02x}-"
                    f"chip-0x{observed:02x}"
                ),
                "protocol": "i2c",
                "transport": "i2c",
                "displayName": model,
                "devicePath": f"/dev/i2c-{bus}",
                "model": model,
                "capabilities": capabilities,
                "recommendedProfile": profile,
                "matchConfidence": "exact",
                "properties": {
                    "BusNumber": int(bus),
                    "Address": f"0x{address:02x}",
                    "ChipID": f"0x{observed:02x}",
                },
                "evidence": {
                    "scope": "i2c-device",
                    "probeMode": "allowlist-read-only-register",
                    "identityRegister": f"0x{register:02x}",
                },
            }
        )
    return candidates, errors
