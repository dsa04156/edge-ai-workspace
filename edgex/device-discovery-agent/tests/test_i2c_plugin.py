from pathlib import Path

from app.i2c_plugin import MockI2CBusAdapter, identify_i2c_devices
from app.scanner import scan_i2c


def test_i2c_probe_reads_only_allowlisted_identity_rule():
    path = Path("/dev/i2c-1")
    adapter = MockI2CBusAdapter(
        {
            (str(path), 0x68, 0x75): 0x71,
            (str(path), 0x76, 0xD0): 0x60,
        }
    )
    rules = [
        {
            "address": "0x68",
            "register": "0x75",
            "expected": "0x71",
            "model": "imu-v1",
            "profile": "imu-v1",
            "capabilities": ["acceleration"],
        },
        {
            "address": "0x76",
            "register": "0xd0",
            "expected": "0x60",
            "model": "pressure-v1",
            "profile": "pressure-v1",
            "capabilities": ["pressure"],
        },
    ]

    candidates, errors = identify_i2c_devices(
        path,
        rules,
        adapter=adapter,
        allowed_addresses={0x68},
    )

    assert errors == []
    assert len(candidates) == 1
    assert candidates[0]["model"] == "imu-v1"
    assert adapter.calls == [(str(path), 0x68, 0x75)]


def test_plan_never_reports_an_i2c_bus_as_a_sensor_candidate(tmp_path):
    (tmp_path / "i2c-1").touch()

    candidates, errors = scan_i2c(
        tmp_path,
        {
            "enabled": True,
            "buses": [1],
            "allowedAddresses": ["0x68"],
            "activeProbeEnabled": False,
        },
    )

    assert candidates == []
    assert errors == []
