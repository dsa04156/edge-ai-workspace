"""Paho MQTT v5 QoS 1 telemetry subscriber for an edge-local broker."""

from __future__ import annotations

import json
import sqlite3
import ssl
import threading
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .config import TLSSettings
from .outbox import EventConflict, EventValidationError, OutboxCapacityExceeded


def _configure_tls(client: mqtt.Client, tls: TLSSettings) -> None:
    client.tls_set(ca_certs=tls.ca_file, certfile=tls.cert_file, keyfile=tls.key_file,
                   tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.tls_insecure_set(False)


def _strict_payload(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload, parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(f"invalid JSON constant {constant}")))
    if not isinstance(value, dict):
        raise EventValidationError("MQTT telemetry payload must be an Event object")
    return value
def _normalize_suback_codes(reason_codes: Any) -> tuple[int, ...] | None:
    """Return integer SUBACK grants, rejecting invalid callback values."""
    if reason_codes is None:
        return ()
    try:
        raw_codes = tuple(reason_codes)
    except Exception:
        return None

    codes = []
    for code in raw_codes:
        if isinstance(code, int) and not isinstance(code, bool):
            codes.append(code)
            continue
        try:
            value = code.value
        except Exception:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        codes.append(value)
    return tuple(codes)


class EdgeMQTTConsumer:
    """Durable MQTT v5 subscriber that ACKs QoS 1 only after handler success."""

    def __init__(self, host: str, port: int, tls: TLSSettings | None, telemetry_topic: str,
                 telemetry_handler: Callable[[dict[str, Any]], None], *, client_id: str,
                 session_expiry_seconds: int) -> None:
        if not isinstance(client_id, str) or not client_id.strip():
            raise ValueError("MQTT client_id must be a stable non-empty edge identity")
        if isinstance(session_expiry_seconds, bool) or not isinstance(session_expiry_seconds, int) or session_expiry_seconds <= 0:
            raise ValueError("MQTT session_expiry_seconds must be a nonzero integer")
        self.telemetry_topic = telemetry_topic
        self.telemetry_handler = telemetry_handler
        self.client_id = client_id
        self.session_expiry_seconds = session_expiry_seconds
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        if tls is not None:
            _configure_tls(self.client, tls)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.manual_ack_set(True)
        self._connected = threading.Event()
        self._ready = threading.Event()
        self._telemetry_subscribe_mid: int | None = None
        self.last_callback_error: str | None = None
        self.last_failure_kind: str | None = None
        self.failure_count = 0
        self.last_failure_at: float | None = None
        properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
        properties.SessionExpiryInterval = session_expiry_seconds
        self.connect_properties = properties
        self.client.connect(host, port, keepalive=30, clean_start=False, properties=properties)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def start(self) -> None:
        self.client.loop_start()
        if not self._ready.wait(10):
            self.close()
            raise RuntimeError(f"local MQTT subscription was not acknowledged: {self.last_callback_error or 'timed out'}")

    def _record_failure(self, kind: str, error: BaseException | str, *, reconnect: bool,
                        clear_ready: bool = True) -> None:
        self.failure_count += 1
        self.last_failure_at = time.monotonic()
        self.last_failure_kind = kind
        self.last_callback_error = str(error)
        if clear_ready:
            self._ready.clear()
        if reconnect:
            try:
                self.client.reconnect()
            except Exception as reconnect_error:  # callback failures must remain observable, not escape Paho
                self.last_callback_error = f"{self.last_callback_error}; reconnect failed: {reconnect_error}"
    def _ack_message(self, client: mqtt.Client, message: mqtt.MQTTMessage) -> bool:
        try:
            result = client.ack(message.mid, message.qos)
        except Exception as error:
            self._record_failure("ack", f"MQTT ACK failed: {error}", reconnect=True)
            return False
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._record_failure("ack", f"MQTT ACK failed: {result}", reconnect=True)
            return False
        return True



    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if reason_code != 0:
            self._connected.clear()
            self._telemetry_subscribe_mid = None
            self._record_failure("connect", f"MQTT connection rejected: {reason_code}", reconnect=False)
            return
        self._connected.set()
        self._ready.clear()
        result, mid = client.subscribe(self.telemetry_topic, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            self._telemetry_subscribe_mid = None
            self._record_failure("subscribe", f"MQTT subscribe failed: {result}", reconnect=True)
            return
        self._telemetry_subscribe_mid = mid

    def _on_subscribe(self, client: mqtt.Client, userdata: Any, mid: int, reason_codes: Any, properties: Any) -> None:
        if not self._connected.is_set():
            return
        if mid != self._telemetry_subscribe_mid:
            self._record_failure(
                "subscribe", f"MQTT SUBACK MID mismatch: expected {self._telemetry_subscribe_mid!r}, got {mid!r}",
                reconnect=False,
            )
            return
        codes = _normalize_suback_codes(reason_codes)
        if codes is None:
            self._telemetry_subscribe_mid = None
            self._record_failure("subscribe", "MQTT SUBACK contained invalid reason codes", reconnect=True)
            return
        if codes != (1,):
            self._telemetry_subscribe_mid = None
            self._record_failure("subscribe", f"MQTT SUBACK did not grant QoS 1: {codes!r}", reconnect=True)
            return
        self._telemetry_subscribe_mid = None
        self.last_callback_error = None
        self.last_failure_kind = None
        self._ready.set()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any,
                       reason_code: Any, properties: Any) -> None:
        self._connected.clear()
        self._ready.clear()
        self._telemetry_subscribe_mid = None
        self._record_failure("disconnect", f"MQTT disconnected: {reason_code}", reconnect=False,
                             clear_ready=False)

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        try:
            payload = _strict_payload(message.payload)
        except (EventValidationError, ValueError, TypeError, json.JSONDecodeError) as error:
            self._record_failure("invalid-payload", error, reconnect=True)
            return
        try:
            self.telemetry_handler(payload)
        except (EventValidationError, EventConflict) as error:
            # The durable handler contract represents terminal validation/conflict outcomes before raising.
            self._record_failure("terminal-handler", error, reconnect=False, clear_ready=False)
            self._ack_message(client, message)
        except (OutboxCapacityExceeded, sqlite3.Error, RuntimeError, ValueError, TypeError) as error:
            self._record_failure("transient-handler", error, reconnect=True)
        except Exception as error:  # Paho callbacks must not leak application failures.
            self._record_failure("handler", error, reconnect=True)
        else:
            if self._ack_message(client, message):
                self.last_callback_error = None
                self.last_failure_kind = None

    def close(self) -> None:
        self._ready.clear()
        self._connected.clear()
        self._telemetry_subscribe_mid = None
        self.client.loop_stop()
        self.client.disconnect()
