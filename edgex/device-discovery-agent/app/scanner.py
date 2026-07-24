from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


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


def scan_serial(dev_root: Path, sys_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
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
        stable_path = f"/dev/serial/by-id/{path.name}"
        candidates.append(
            {
                "hardwareKey": path.name,
                "protocol": "serial",
                "transport": "usb-serial",
                "displayName": properties.get("Product") or path.name,
                "devicePath": stable_path,
                "properties": properties,
                "evidence": {
                    "scope": "usb-device",
                    "stablePath": "udev-by-id",
                    "kernelDevice": tty_name,
                },
            }
        )
    return candidates, errors


def scan_i2c(dev_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        entries = sorted(dev_root.glob("i2c-*"), key=lambda item: item.name)
    except (PermissionError, OSError) as exc:
        return [], [f"I2C 버스 조회 실패: {exc.__class__.__name__}"]
    for path in entries:
        match = I2C_DEVICE_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        bus = match.group(1)
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
) -> tuple[list[dict[str, Any]], list[str]]:
    active_dev_root = dev_root or Path(
        os.getenv("DISCOVERY_HOST_DEV_ROOT", "/host-dev")
    )
    active_sys_root = sys_root or Path(
        os.getenv("DISCOVERY_HOST_SYS_ROOT", "/host-sys")
    )
    serial, serial_errors = scan_serial(active_dev_root, active_sys_root)
    i2c, i2c_errors = scan_i2c(active_dev_root)
    candidates = [*serial, *i2c]
    candidates.sort(
        key=lambda item: (
            str(item["protocol"]),
            str(item["devicePath"]),
        )
    )
    return candidates, [*serial_errors, *i2c_errors]
