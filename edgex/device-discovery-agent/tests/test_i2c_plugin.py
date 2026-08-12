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


def test_i2c_composite_probe_emits_one_stable_sense_hat_candidate():
    path = Path("/dev/i2c-1")
    adapter = MockI2CBusAdapter(
        {
            (str(path), 0x1C, 0x0F): 0x3D,
            (str(path), 0x5C, 0x0F): 0xBD,
            (str(path), 0x5F, 0x0F): 0xBC,
            (str(path), 0x6A, 0x0F): 0x68,
        }
    )
    rule = {
        "identities": [
            {"address": "0x1c", "register": "0x0f", "expected": "0x3d"},
            {"address": "0x5c", "register": "0x0f", "expected": "0xbd"},
            {"address": "0x5f", "register": "0x0f", "expected": "0xbc"},
            {"address": "0x6a", "register": "0x0f", "expected": "0x68"},
        ],
        "model": "raspberry-pi-sense-hat-v1",
        "profile": "etri-sensehat-gyroscope",
        "capabilities": ["temperature", "gyroscope"],
    }

    candidates, errors = identify_i2c_devices(
        path,
        [rule],
        adapter=adapter,
        allowed_addresses={0x1C, 0x5C, 0x5F, 0x6A},
    )

    assert errors == []
    assert len(candidates) == 1
    assert candidates[0]["hardwareId"] == (
        "bus-1-raspberry-pi-sense-hat-v1-1c3d-5cbd-5fbc-6a68"
    )
    assert candidates[0]["properties"] == {
        "BusNumber": 1,
        "IdentityFingerprint": "1c3d-5cbd-5fbc-6a68",
        "IdentityCount": 4,
    }
    assert candidates[0]["evidence"]["identityRegisters"] == (
        "0x1c/0x0f=0x3d,0x5c/0x0f=0xbd,"
        "0x5f/0x0f=0xbc,0x6a/0x0f=0x68"
    )


def test_i2c_composite_probe_blocks_partial_or_mismatched_board():
    path = Path("/dev/i2c-1")
    adapter = MockI2CBusAdapter(
        {
            (str(path), 0x1C, 0x0F): 0x3D,
            (str(path), 0x5C, 0x0F): 0x00,
        }
    )

    candidates, errors = identify_i2c_devices(
        path,
        [
            {
                "identities": [
                    {
                        "address": "0x1c",
                        "register": "0x0f",
                        "expected": "0x3d",
                    },
                    {
                        "address": "0x5c",
                        "register": "0x0f",
                        "expected": "0xbd",
                    },
                ],
                "model": "raspberry-pi-sense-hat-v1",
                "profile": "etri-sensehat-gyroscope",
            }
        ],
        adapter=adapter,
        allowed_addresses={0x1C, 0x5C},
    )

    assert candidates == []
    assert errors == [
        "I2C raspberry-pi-sense-hat-v1 0x5c identity mismatch: "
        "expected 0xbd, observed 0x00"
    ]


def test_active_i2c_plan_scans_only_the_allowlisted_bus_and_board(tmp_path):
    bus = tmp_path / "i2c-1"
    bus.touch()
    (tmp_path / "i2c-2").touch()
    adapter = MockI2CBusAdapter(
        {
            (str(bus), 0x1C, 0x0F): 0x3D,
            (str(bus), 0x6A, 0x0F): 0x68,
        }
    )

    candidates, errors = scan_i2c(
        tmp_path,
        {
            "enabled": True,
            "buses": [1],
            "allowedAddresses": ["0x1c", "0x6a"],
            "activeProbeEnabled": True,
            "identificationRules": [
                {
                    "identities": [
                        {
                            "address": "0x1c",
                            "register": "0x0f",
                            "expected": "0x3d",
                        },
                        {
                            "address": "0x6a",
                            "register": "0x0f",
                            "expected": "0x68",
                        },
                    ],
                    "model": "raspberry-pi-sense-hat-v1",
                    "profile": "etri-sensehat-gyroscope",
                }
            ],
        },
        adapter=adapter,
    )

    assert errors == []
    assert [item["model"] for item in candidates] == [
        "raspberry-pi-sense-hat-v1"
    ]
    assert all(call[0] == str(bus) for call in adapter.calls)


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
