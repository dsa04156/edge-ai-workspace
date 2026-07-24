from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .i2c_plugin import (
    I2CBusAdapter,
    LinuxI2CBusAdapter,
    identify_i2c_devices,
)
from .serial_plugin import SerialManifestError, probe_serial_manifest
from .plugins import EXTENSION_PLUGINS

I2C_DEVICE_PATTERN = re.compile(r"^i2c-([0-9]+)$")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def _usb_metadata(sys_root: Path, tty_name: str) -> dict[str, str]:
    current = sys_root / "class" / "tty" / tty_name / "device"
    try:
        current = current.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return {}
    metadata: dict[str, str] = {}
    file_map = {
        "VendorID": "idVendor",
        "ProductID": "idProduct",
        "SerialNumber": "serial",
        "Manufacturer": "manufacturer",
        "Product": "product",
    }
    for parent in [current, *current.parents]:
        if sys_root not in parent.parents and parent != sys_root:
            break
        for output_key, file_name in file_map.items():
            if output_key in metadata:
                continue
            value = _read_text(parent / file_name)
            if value:
                metadata[output_key] = value[:255]
        if "VendorID" in metadata and "ProductID" in metadata:
            break
    return metadata


def scan_serial(
    dev_root: Path,
    sys_root: Path,
    plan: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    if plan is not None and not bool(plan.get("enabled")):
        return candidates, errors
    allowed_vid_pid = {
        str(item).casefold() for item in (plan or {}).get("allowedVidPid", [])
    }
    by_id = dev_root / "serial" / "by-id"
    if not by_id.exists():
        return candidates, errors
    try:
        entries = sorted(by_id.iterdir(), key=lambda item: item.name)
    except (PermissionError, OSError) as exc:
        return [], [f"USB Serial by-id 조회 실패: {exc.__class__.__name__}"]
    for path in entries:
        if not path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        tty_name = resolved.name
        properties = _usb_metadata(sys_root, tty_name)
        properties["KernelDevice"] = tty_name
        observed_vid_pid = (
            f"{properties.get('VendorID', '')}:"
            f"{properties.get('ProductID', '')}"
        ).casefold()
        if allowed_vid_pid and observed_vid_pid not in allowed_vid_pid:
            continue
        stable_path = f"/dev/serial/by-id/{path.name}"
        hardware_id = properties.get("SerialNumber") or path.name
        candidate: dict[str, Any] = {
            "hardwareKey": path.name,
            "hardwareId": hardware_id,
            "protocol": "serial",
            "transport": "usb-serial",
            "displayName": properties.get("Product") or path.name,
            "devicePath": stable_path,
            "vendor": properties.get("Manufacturer"),
            "properties": properties,
            "evidence": {
                "scope": "usb-device",
                "stablePath": "udev-by-id",
                "kernelDevice": tty_name,
            },
        }
        if plan is not None and bool(plan.get("manifestProbeEnabled")):
            baud_rates = plan.get("baudRates") or [115200]
            try:
                manifest = probe_serial_manifest(
                    path,
                    command=str(plan.get("manifestCommand") or "WHOAMI"),
                    baud_rate=int(baud_rates[0]),
                    timeout_seconds=float(
                        plan.get("manifestTimeoutSeconds") or 1.5
                    ),
                )
                candidate.update(
                    {
                        "model": manifest["model"],
                        "firmwareVersion": manifest.get("firmwareVersion"),
                        "capabilities": manifest["resources"],
                        "recommendedProfile": manifest["model"],
                        "matchConfidence": "exact",
                    }
                )
                candidate["properties"]["ManifestDeviceID"] = manifest[
                    "deviceId"
                ]
                candidate["evidence"]["manifest"] = "validated-json"
            except SerialManifestError as exc:
                candidate["evidence"]["manifest"] = exc.code
                errors.append(f"{stable_path}: {exc.code}")
        candidates.append(candidate)
    return candidates, errors


def scan_i2c(
    dev_root: Path,
    plan: dict[str, Any] | None = None,
    *,
    adapter: I2CBusAdapter | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    if plan is not None and not bool(plan.get("enabled")):
        return candidates, errors
    allowed_buses = {
        int(item) for item in (plan or {}).get("buses", [])
    }
    try:
        entries = sorted(dev_root.glob("i2c-*"), key=lambda item: item.name)
    except (PermissionError, OSError) as exc:
        return [], [f"I2C 버스 조회 실패: {exc.__class__.__name__}"]
    for path in entries:
        match = I2C_DEVICE_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        bus = match.group(1)
        if allowed_buses and int(bus) not in allowed_buses:
            continue
        if plan is not None and bool(plan.get("activeProbeEnabled")):
            allowed_addresses = {
                int(str(item), 16)
                for item in plan.get("allowedAddresses", [])
            }
            identified, probe_errors = identify_i2c_devices(
                path,
                list(plan.get("identificationRules") or []),
                adapter=adapter or LinuxI2CBusAdapter(),
                allowed_addresses=allowed_addresses,
            )
            candidates.extend(identified)
            errors.extend(probe_errors)
            continue
        if plan is not None:
            # A bus file proves only that the controller exists. It is not a
            # physical sensor candidate. Production plans therefore emit I2C
            # candidates only after an allowlisted, read-only identity probe.
            continue
        candidates.append(
            {
                "hardwareKey": f"i2c-bus-{bus}",
                "protocol": "i2c",
                "transport": "i2c-bus",
                "displayName": f"I²C 버스 {bus}",
                "devicePath": f"/dev/i2c-{bus}",
                "properties": {"BusNumber": int(bus)},
                "evidence": {
                    "scope": "bus",
                    "probeMode": "passive",
                    "warning": "버스 존재는 센서 주소 응답을 의미하지 않음",
                },
            }
        )
    return candidates, errors


def scan_node(
    *,
    dev_root: Path | None = None,
    sys_root: Path | None = None,
    plan: dict[str, Any] | None = None,
    i2c_adapter: I2CBusAdapter | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    active_dev_root = dev_root or Path(
        os.getenv("DISCOVERY_HOST_DEV_ROOT", "/host-dev")
    )
    active_sys_root = sys_root or Path(
        os.getenv("DISCOVERY_HOST_SYS_ROOT", "/host-sys")
    )
    serial_plan = None if plan is None else dict(plan.get("serial") or {})
    i2c_plan = None if plan is None else dict(plan.get("i2c") or {})
    serial, serial_errors = scan_serial(
        active_dev_root,
        active_sys_root,
        serial_plan,
    )
    i2c, i2c_errors = scan_i2c(
        active_dev_root,
        i2c_plan,
        adapter=i2c_adapter,
    )
    extension_errors: list[str] = []
    if plan is not None:
        modbus_plan = {
            "enabled": bool(
                (plan.get("modbusRtu") or {}).get("enabled")
                or (plan.get("modbusTcp") or {}).get("enabled")
            )
        }
        extension_plans = {
            "modbus": modbus_plan,
            "opcua": dict(plan.get("opcua") or {}),
            "onvif": dict(plan.get("onvif") or {}),
        }
        for protocol, plugin in EXTENSION_PLUGINS.items():
            extension_errors.extend(
                plugin.discover(extension_plans[protocol]).errors
            )
        if bool((plan.get("mqtt") or {}).get("enabled")):
            extension_errors.append(
                "MQTT self-registration schema is implemented but no "
                "verified broker subscription is configured"
            )
    candidates = [*serial, *i2c]
    candidates.sort(
        key=lambda item: (
            str(item["protocol"]),
            str(item["devicePath"]),
        )
    )
    return candidates, [*serial_errors, *i2c_errors, *extension_errors]
