from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import MqttConfig


class PublishError(RuntimeError):
    """Raised when an output publisher cannot connect or publish."""


@dataclass(frozen=True)
class PublishRecord:
    topic: str
    payload: str
    qos: int


class Publisher(ABC):
    @abstractmethod
    def start(self) -> None:
        """Open the output connection."""

    @abstractmethod
    def publish(self, topic: str, payload: str, *, qos: int) -> None:
        """Publish one serialized payload."""

    @abstractmethod
    def stop(self) -> None:
        """Close the output connection."""


class InMemoryPublisher(Publisher):
    def __init__(self) -> None:
        self.records: list[PublishRecord] = []
        self.started = False

    def start(self) -> None:
        self.started = True

    def publish(self, topic: str, payload: str, *, qos: int) -> None:
        if not self.started:
            raise PublishError("publisher is not started")
        self.records.append(PublishRecord(topic=topic, payload=payload, qos=qos))

    def stop(self) -> None:
        self.started = False


class MqttPublisher(Publisher):
    def __init__(
        self,
        config: MqttConfig,
        *,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self._client: Any | None = None

    def start(self) -> None:
        if self._client is not None:
            return
        client = (self._client_factory or _paho_client_factory)()
        try:
            result = client.connect(
                self.config.host,
                self.config.port,
                self.config.keepalive_seconds,
            )
            if isinstance(result, int) and result != 0:
                raise PublishError(f"MQTT connect failed with rc={result}")
            client.loop_start()
        except PublishError:
            raise
        except Exception as exc:
            raise PublishError(f"MQTT connect failed: {exc}") from exc
        self._client = client

    def publish(self, topic: str, payload: str, *, qos: int) -> None:
        if self._client is None:
            raise PublishError("publisher is not started")
        try:
            result = self._client.publish(topic, payload, qos=qos)
        except Exception as exc:
            raise PublishError(f"MQTT publish failed: {exc}") from exc
        return_code = getattr(result, "rc", 0)
        if return_code != 0:
            raise PublishError(f"MQTT publish failed with rc={return_code} topic={topic}")

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.loop_stop()
        finally:
            client.disconnect()


def _paho_client_factory() -> Any:
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise PublishError(
            "paho-mqtt is required for MQTT output; install the project dependencies"
        ) from exc
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
