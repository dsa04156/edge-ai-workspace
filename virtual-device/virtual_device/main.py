from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Sequence
from types import FrameType

from .adapters.base import Adapter
from .adapters.fake import FakeAdapter
from .adapters.serial_json import SerialJsonAdapter
from .config import DeviceProfile, ProfileValidationError, load_profile
from .publisher import MqttPublisher
from .runtime import VirtualDeviceRuntime

LOGGER = logging.getLogger("virtual-device")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a profile-driven Serial JSON Virtual Device Runtime.",
    )
    parser.add_argument("--profile", required=True, help="Path to the Device Profile YAML")
    parser.add_argument("--mqtt-host", help="Override output.mqtt.host")
    parser.add_argument("--mqtt-port", type=int, help="Override output.mqtt.port")
    parser.add_argument("--serial-port", help="Override adapter.connection.port")
    parser.add_argument(
        "--serial-baud-rate",
        type=int,
        help="Override adapter.connection.baudRate",
    )
    parser.add_argument(
        "--serial-timeout-seconds",
        type=float,
        help="Override adapter.connection.timeoutSeconds",
    )
    return parser


def overrides_from_args(args: argparse.Namespace) -> dict[str, object]:
    values = {
        "mqtt_host": args.mqtt_host,
        "mqtt_port": args.mqtt_port,
        "serial_port": args.serial_port,
        "serial_baud_rate": args.serial_baud_rate,
        "serial_timeout_seconds": args.serial_timeout_seconds,
    }
    return {name: value for name, value in values.items() if value is not None}


def create_adapter(profile: DeviceProfile) -> Adapter:
    if profile.adapter.type == "serial-json":
        return SerialJsonAdapter(profile.adapter.connection)
    if profile.adapter.type == "fake":
        return FakeAdapter([])
    raise ProfileValidationError(f"unsupported adapter type: {profile.adapter.type}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = load_profile(args.profile, overrides=overrides_from_args(args))
        adapter = create_adapter(profile)
    except ProfileValidationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    publisher = MqttPublisher(profile.output.mqtt)
    runtime = VirtualDeviceRuntime(profile, adapter=adapter, publisher=publisher)

    previous_handlers: dict[signal.Signals, signal.Handlers] = {}

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        LOGGER.info("shutdown requested by signal %s", signum)
        runtime.request_stop()

    for runtime_signal in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[runtime_signal] = signal.getsignal(runtime_signal)
        signal.signal(runtime_signal, request_shutdown)

    LOGGER.info(
        "starting virtual_device_id=%s physical_device_id=%s serial=%s mqtt=%s:%s",
        profile.virtual_device_id,
        profile.physical_device_id,
        profile.adapter.connection.port,
        profile.output.mqtt.host,
        profile.output.mqtt.port,
    )
    try:
        runtime.run()
    except KeyboardInterrupt:
        runtime.request_stop()
        return 130
    except Exception as exc:
        LOGGER.error("runtime failed: %s", exc)
        return 1
    finally:
        for runtime_signal, previous_handler in previous_handlers.items():
            signal.signal(runtime_signal, previous_handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
