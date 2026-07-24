from pathlib import Path

from app.scanner import scan_node


def test_scanner_reports_only_stable_serial_paths_and_i2c_buses(tmp_path: Path):
    dev_root = tmp_path / "dev"
    sys_root = tmp_path / "sys"
    by_id = dev_root / "serial" / "by-id"
    tty_root = sys_root / "class" / "tty" / "ttyACM0"
    usb_root = sys_root / "devices" / "usb1" / "1-1"
    by_id.mkdir(parents=True)
    (dev_root / "ttyACM0").touch()
    (dev_root / "ttyUSB9").touch()
    (dev_root / "i2c-1").touch()
    (dev_root / "i2c-not-a-bus").touch()
    tty_root.mkdir(parents=True)
    usb_root.mkdir(parents=True)
    (usb_root / "idVendor").write_text("2341", encoding="utf-8")
    (usb_root / "idProduct").write_text("0043", encoding="utf-8")
    (usb_root / "serial").write_text("SERIAL-001", encoding="utf-8")
    (tty_root / "device").symlink_to(usb_root, target_is_directory=True)
    (by_id / "usb-Arduino_SERIAL-001").symlink_to(
        Path("../../ttyACM0")
    )

    candidates, errors = scan_node(dev_root=dev_root, sys_root=sys_root)

    assert errors == []
    assert [item["protocol"] for item in candidates] == ["i2c", "serial"]
    serial = candidates[1]
    assert serial["devicePath"] == "/dev/serial/by-id/usb-Arduino_SERIAL-001"
    assert serial["properties"]["VendorID"] == "2341"
    assert serial["properties"]["SerialNumber"] == "SERIAL-001"
    assert not any("ttyUSB9" in str(item) for item in candidates)
    i2c = candidates[0]
    assert i2c["devicePath"] == "/dev/i2c-1"
    assert i2c["evidence"]["probeMode"] == "passive"
