"""Strict, bootstrap-scoped EdgeX Device validation responder."""

from __future__ import annotations

import json
import re
import threading
import uuid
from copy import deepcopy
from typing import Any

import paho.mqtt.client as mqtt


SERVICE_NAME = re.compile(r"[A-Za-z0-9._-]+")


def _strict_json(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value!r}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    return json.loads(
        raw,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def _uuid(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"validation envelope {field} must be a UUID")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"validation envelope {field} must be a UUID") from error
    return value


def _reason_codes(reason_codes: Any) -> tuple[int, ...] | None:
    try:
        values = tuple(reason_codes)
    except (TypeError, ValueError):
        return None
    result: list[int] = []
    for item in values:
        value = item if isinstance(item, int) and not isinstance(item, bool) else getattr(item, "value", None)
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        result.append(value)
    return tuple(result)


class MetadataValidationResponder:
    """Answers only exact contract Device validation during Metadata bootstrap."""

    def __init__(
        self,
        host: str,
        port: int,
        service_name: str,
        devices: list[dict[str, Any]],
        *,
        client: Any | None = None,
        ready_timeout: float = 10.0,
    ) -> None:
        if not isinstance(host, str) or not host.strip():
            raise ValueError("MessageBus host must be non-empty")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("MessageBus port must be between 1 and 65535")
        if not isinstance(service_name, str) or SERVICE_NAME.fullmatch(service_name) is None:
            raise ValueError("Metadata service name contains unsafe topic characters")
        if not isinstance(ready_timeout, (int, float)) or ready_timeout <= 0:
            raise ValueError("validation responder ready timeout must be positive")
        if not isinstance(devices, list) or not devices:
            raise ValueError("validation responder requires approved Devices")

        approved: dict[str, dict[str, Any]] = {}
        for device in devices:
            if not isinstance(device, dict):
                raise ValueError("approved Device must be an object")
            name = device.get("name")
            if not isinstance(name, str) or not name.strip() or name in approved:
                raise ValueError("approved Device names must be non-empty and unique")
            if device.get("serviceName") != service_name:
                raise ValueError(f"approved Device {name!r} references another service")
            approved[name] = deepcopy(device)

        self.host = host
        self.port = port
        self.service_name = service_name
        self.approved = approved
        self.ready_timeout = float(ready_timeout)
        self.request_topic = f"edgex/{service_name}/validate/device"
        self.response_prefix = f"edgex/response/{service_name}"
        self.ready = threading.Event()
        self.last_error: str | None = None
        self._subscribe_mid: int | None = None
        self._started = False
        self._closed = False
        self.client = client or mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"metadata-bootstrap-{uuid.uuid4()}",
            protocol=mqtt.MQTTv5,
        )
        self.client.on_connect = self.on_connect
        self.client.on_subscribe = self.on_subscribe
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("validation responder is closed")
        if self._started:
            return
        self._started = True
        result = self.client.connect(self.host, self.port, keepalive=30)
        if result != mqtt.MQTT_ERR_SUCCESS:
            self.close()
            raise RuntimeError(f"MessageBus connect failed: {result}")
        self.client.loop_start()
        if not self.ready.wait(self.ready_timeout):
            error = self.last_error or "subscription acknowledgement timed out"
            self.close()
            raise RuntimeError(f"Metadata validation responder is not ready: {error}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.ready.clear()
        if self._started:
            self.client.loop_stop()
            self.client.disconnect()

    def on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code != 0:
            self.last_error = f"MessageBus connection rejected: {reason_code}"
            return
        result, mid = client.subscribe(self.request_topic, qos=0)
        if result != mqtt.MQTT_ERR_SUCCESS:
            self.last_error = f"validation topic subscription failed: {result}"
            return
        self._subscribe_mid = mid

    def on_subscribe(self, client: Any, userdata: Any, mid: int, reason_codes: Any, properties: Any) -> None:
        codes = _reason_codes(reason_codes)
        if mid != self._subscribe_mid or codes != (0,):
            self.last_error = "validation topic SUBACK was not the expected QoS 0 grant"
            return
        self.last_error = None
        self.ready.set()

    def on_disconnect(
        self,
        client: Any,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        self.ready.clear()
        if not self._closed:
            self.last_error = f"MessageBus disconnected: {reason_code}"

    @staticmethod
    def _success(request_id: str, correlation_id: str) -> dict[str, Any]:
        return {
            "apiVersion": "v3",
            "receivedTopic": "",
            "correlationID": correlation_id,
            "requestID": request_id,
            "errorCode": 0,
            "payload": None,
            "contentType": "application/json",
        }

    @staticmethod
    def _failure(request_id: str, message: str) -> dict[str, Any]:
        return {
            "apiVersion": "v3",
            "receivedTopic": "",
            "correlationID": str(uuid.uuid4()),
            "requestID": request_id,
            "errorCode": 1,
            "payload": message,
            "contentType": "text/plain",
        }

    def _validate(self, envelope: dict[str, Any]) -> tuple[str, str]:
        if envelope.get("apiVersion") != "v3":
            raise ValueError("validation envelope must use apiVersion v3")
        request_id = _uuid(envelope.get("requestID"), "requestID")
        correlation_id = _uuid(envelope.get("correlationID"), "correlationID")
        if envelope.get("errorCode") != 0 or envelope.get("contentType") != "application/json":
            raise ValueError("validation envelope has an invalid request contract")
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or payload.get("apiVersion") != "v3":
            raise ValueError("validation payload must be an EdgeX v3 AddDeviceRequest")
        _uuid(payload.get("requestId"), "payload requestId")
        device = payload.get("device")
        if not isinstance(device, dict):
            raise ValueError("validation payload requires a Device object")
        expected = self.approved.get(device.get("name"))
        if expected is None or device != expected:
            raise ValueError("Device is not in the approved Metadata contract")
        return request_id, correlation_id

    def on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            envelope = _strict_json(message.payload)
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            self.last_error = f"invalid validation message JSON: {error}"
            return
        if not isinstance(envelope, dict):
            self.last_error = "validation message must be an object"
            return
        try:
            request_id = _uuid(envelope.get("requestID"), "requestID")
        except ValueError as error:
            self.last_error = str(error)
            return
        try:
            validated_request_id, correlation_id = self._validate(envelope)
        except ValueError as error:
            self.last_error = str(error)
            response = self._failure(request_id, str(error))
        else:
            self.last_error = None
            response = self._success(validated_request_id, correlation_id)
        topic = f"{self.response_prefix}/{request_id}"
        payload = json.dumps(response, separators=(",", ":"), ensure_ascii=True).encode()
        result = client.publish(topic, payload, qos=0)
        result_code = getattr(result, "rc", result[0] if isinstance(result, tuple) else None)
        if result_code != mqtt.MQTT_ERR_SUCCESS:
            self.last_error = f"validation response publish failed: {result_code}"
