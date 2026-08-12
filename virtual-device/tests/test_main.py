from __future__ import annotations

from pathlib import Path

from virtual_device.adapters.fake import FakeAdapter
from virtual_device.adapters.serial_json import SerialJsonAdapter
from virtual_device.config import load_profile
from virtual_device.main import build_parser, create_adapter, main, overrides_from_args

from test_config import VALID_PROFILE, write_profile


def test_cli_options_are_converted_to_highest_priority_overrides() -> None:
    args = build_parser().parse_args(
        [
            "--profile",
            "profile.yaml",
            "--mqtt-host",
            "cli-broker",
            "--mqtt-port",
            "2883",
            "--serial-port",
            "/dev/ttyUSB9",
            "--serial-baud-rate",
            "57600",
            "--serial-timeout-seconds",
            "1.5",
        ]
    )

    assert overrides_from_args(args) == {
        "mqtt_host": "cli-broker",
        "mqtt_port": 2883,
        "serial_port": "/dev/ttyUSB9",
        "serial_baud_rate": 57600,
        "serial_timeout_seconds": 1.5,
    }


def test_adapter_factory_uses_profile_type(tmp_path: Path) -> None:
    serial_profile = load_profile(write_profile(tmp_path, VALID_PROFILE))
    fake_profile_path = write_profile(
        tmp_path,
        VALID_PROFILE.replace("type: serial-json", "type: fake"),
    )
    fake_profile = load_profile(fake_profile_path)

    assert isinstance(create_adapter(serial_profile), SerialJsonAdapter)
    assert isinstance(create_adapter(fake_profile), FakeAdapter)


def test_main_returns_configuration_error_without_starting_runtime(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.yaml"

    exit_code = main(["--profile", str(missing)])

    assert exit_code == 2
    assert "profile not found" in capsys.readouterr().err
