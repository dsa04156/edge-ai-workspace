from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from virtual_device.adapters.base import AdapterConnectionError, InvalidSampleError
from virtual_device.adapters.fake import FakeAdapter
from virtual_device.adapters.serial_json import SerialJsonAdapter
from virtual_device.config import MqttConfig, SerialConnectionConfig
from virtual_device.publisher import InMemoryPublisher, MqttPublisher, PublishError


class StubSerial:
    def __init__(self, items: list[bytes | Exception]) -> None:
        self.items = list(items)
        self.closed = False

    def readline(self) -> bytes:
        if not self.items:
            return b""
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


def connection() -> SerialConnectionConfig:
    return SerialConnectionConfig(port="/dev/ttyTEST0", baud_rate=115200, timeout_seconds=2)


def serial_factory(serial: StubSerial, calls: list[dict[str, Any]]) -> Callable[..., StubSerial]:
    def factory(**kwargs: Any) -> StubSerial:
        calls.append(kwargs)
        return serial

    return factory


def test_serial_adapter_reads_one_json_object_and_reports_connected() -> None:
    serial = StubSerial([b'{"sensor":"vibration","x":0.1}\n'])
    calls: list[dict[str, Any]] = []
    adapter = SerialJsonAdapter(connection(), serial_factory=serial_factory(serial, calls))

    adapter.start()

    assert adapter.read() == {"sensor": "vibration", "x": 0.1}
    assert adapter.health().connection == "connected"
    assert calls == [{"port": "/dev/ttyTEST0", "baudrate": 115200, "timeout": 2}]


def test_invalid_json_is_a_sample_error_and_next_line_can_be_read() -> None:
    serial = StubSerial([b"not-json\n", b'{"x":1}\n'])
    adapter = SerialJsonAdapter(connection(), serial_factory=lambda **_: serial)
    adapter.start()

    with pytest.raises(InvalidSampleError, match="invalid JSON"):
        adapter.read()

    assert adapter.health().connection == "connected"
    assert adapter.read() == {"x": 1}


def test_serial_transport_error_marks_adapter_disconnected() -> None:
    serial = StubSerial([OSError("device removed")])
    adapter = SerialJsonAdapter(connection(), serial_factory=lambda **_: serial)
    adapter.start()

    with pytest.raises(AdapterConnectionError, match="device removed"):
        adapter.read()

    assert adapter.health().connection == "disconnected"
    assert adapter.health().last_error == "device removed"


def test_serial_adapter_stop_closes_device() -> None:
    serial = StubSerial([])
    adapter = SerialJsonAdapter(connection(), serial_factory=lambda **_: serial)
    adapter.start()

    adapter.stop()

    assert serial.closed is True
    assert adapter.health().connection == "disconnected"


def test_fake_adapter_provides_serial_shaped_samples_without_hardware() -> None:
    adapter = FakeAdapter([{"x": 1}, '{"x":2}'])

    adapter.start()

    assert adapter.read() == {"x": 1}
    assert adapter.read() == {"x": 2}
    assert adapter.read() is None
    assert adapter.health().connection == "connected"


def test_in_memory_publisher_records_topic_payload_and_qos() -> None:
    publisher = InMemoryPublisher()
    publisher.start()

    publisher.publish("topic/a", '{"value":1}', qos=1)

    assert publisher.records[0].topic == "topic/a"
    assert publisher.records[0].payload == '{"value":1}'
    assert publisher.records[0].qos == 1


@dataclass
class PublishResult:
    rc: int


class StubMqttClient:
    def __init__(self, publish_rc: int = 0) -> None:
        self.publish_rc = publish_rc
        self.connect_args: tuple[str, int, int] | None = None
        self.published: list[tuple[str, str, int]] = []
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def connect(self, host: str, port: int, keepalive: int) -> None:
        self.connect_args = (host, port, keepalive)

    def loop_start(self) -> None:
        self.loop_started = True

    def publish(self, topic: str, payload: str, qos: int) -> PublishResult:
        self.published.append((topic, payload, qos))
        return PublishResult(self.publish_rc)

    def loop_stop(self) -> None:
        self.loop_stopped = True

    def disconnect(self) -> None:
        self.disconnected = True


def mqtt_config() -> MqttConfig:
    return MqttConfig(
        host="127.0.0.1",
        port=1883,
        qos=0,
        telemetry_topic="edge/vd/telemetry",
        status_topic="edge/vd/status",
    )


def test_mqtt_publisher_uses_profile_broker_and_stops_cleanly() -> None:
    client = StubMqttClient()
    publisher = MqttPublisher(mqtt_config(), client_factory=lambda: client)

    publisher.start()
    publisher.publish("edge/vd/telemetry", "{}", qos=0)
    publisher.stop()

    assert client.connect_args == ("127.0.0.1", 1883, 60)
    assert client.loop_started is True
    assert client.published == [("edge/vd/telemetry", "{}", 0)]
    assert client.loop_stopped is True
    assert client.disconnected is True


def test_mqtt_publish_failure_is_explicit() -> None:
    client = StubMqttClient(publish_rc=4)
    publisher = MqttPublisher(mqtt_config(), client_factory=lambda: client)
    publisher.start()

    with pytest.raises(PublishError, match="rc=4"):
        publisher.publish("edge/vd/telemetry", "{}", qos=0)
