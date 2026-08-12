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
        model = str(rule["model"])
        raw_identities = list(rule.get("identities") or [])
        identities = raw_identities or [
            {
                "address": rule["address"],
                "register": rule["register"],
                "expected": rule["expected"],
            }
        ]
        checks = [
            (
                int(str(identity["address"]), 16),
                int(str(identity["register"]), 16),
                int(str(identity["expected"]), 16),
            )
            for identity in identities
        ]
        if any(
            address not in allowed_addresses
            for address, _, _ in checks
        ):
            continue
        observed_identities: list[tuple[int, int, int]] = []
        matched = True
        for address, register, expected in checks:
            try:
                observed = adapter.read_identity_register(
                    bus_path,
                    address=address,
                    register=register,
                )
            except I2CProbeError as exc:
                errors.append(
                    f"I2C {model} 0x{address:02x} identification failed: "
                    f"{exc}"
                )
                matched = False
                break
            if observed != expected:
                errors.append(
                    f"I2C {model} 0x{address:02x} identity mismatch: "
                    f"expected 0x{expected:02x}, observed 0x{observed:02x}"
                )
                matched = False
                break
            observed_identities.append((address, register, observed))
        if not matched:
            continue
        bus = bus_path.name.removeprefix("i2c-")
        profile = str(rule["profile"])
        capabilities = list(rule.get("capabilities") or [])
        fingerprint = "-".join(
            f"{address:02x}{observed:02x}"
            for address, _, observed in observed_identities
        )
        identity_registers = ",".join(
            f"0x{address:02x}/0x{register:02x}=0x{observed:02x}"
            for address, register, observed in observed_identities
        )
        candidates.append(
            {
                "hardwareKey": (
                    f"i2c:{bus}:{model}:{fingerprint}"
                ),
                "hardwareId": (
                    f"bus-{bus}-{model}-{fingerprint}"
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
                    "IdentityFingerprint": fingerprint,
                    "IdentityCount": len(observed_identities),
                },
                "evidence": {
                    "scope": "i2c-device",
                    "probeMode": "allowlist-read-only-register",
                    "identityRegisters": identity_registers,
                },
            }
        )
    return candidates, errors
