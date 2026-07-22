import json

import pytest
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from telemetry_plane.mqtt import EdgeMQTTConsumer
from telemetry_plane.outbox import EventValidationError, OutboxCapacityExceeded


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.acks = []
        self.reconnects = 0
        self.connect_call = None

    def manual_ack_set(self, value):
        self.manual_ack = value

    def connect(self, *args, **kwargs):
        self.connect_call = (args, kwargs)

    def subscribe(self, topic, qos):
        self.subscription = (topic, qos)
        return (0, 7)

    def ack(self, mid, qos):
        self.acks.append((mid, qos))
        return 0

    def reconnect(self):
        self.reconnects += 1

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


class Message:
    mid = 3
    qos = 1

    def __init__(self, payload):
        self.payload = payload

class ReasonCodeLike:
    def __init__(self, value):
        self.value = value


@pytest.fixture
def fake_mqtt(monkeypatch):
    import telemetry_plane.mqtt as module

    monkeypatch.setattr(module.mqtt, "Client", FakeClient)
    return module


def test_mqtt_uses_durable_v5_session_and_suback_readiness(fake_mqtt):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    assert consumer.client.kwargs["client_id"] == "edge-a"
    assert consumer.client.manual_ack is True
    assert consumer.client.connect_call[1]["clean_start"] is False
    assert consumer.connect_properties.SessionExpiryInterval == 60
    consumer._on_connect(consumer.client, None, None, 0, None)
    assert consumer.connected and not consumer.ready
    consumer._on_subscribe(consumer.client, None, 7, [1], None)
    assert consumer.ready


def test_mqtt_real_paho_qos_one_suback_marks_ready(fake_mqtt):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)

    reason_code = ReasonCode(PacketTypes.SUBACK, identifier=1)
    consumer._on_subscribe(consumer.client, None, 7, [reason_code], None)

    assert consumer.ready
    assert consumer.last_callback_error is None
    assert consumer.client.reconnects == 0


@pytest.mark.parametrize("reason_codes", [
    [object()],
    [ReasonCodeLike("1")],
    [ReasonCodeLike(True)],
    [True],
    object(),
])
def test_mqtt_invalid_suback_reason_codes_are_observable_failures(fake_mqtt, reason_codes):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)

    consumer._on_subscribe(consumer.client, None, 7, reason_codes, None)

    assert not consumer.ready
    assert consumer.last_failure_kind == "subscribe"
    assert consumer.last_callback_error == "MQTT SUBACK contained invalid reason codes"
    assert consumer.client.reconnects == 1



def test_mqtt_callback_acks_invalid_only_after_terminal_handler_outcome(fake_mqtt):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: (_ for _ in ()).throw(EventValidationError("bad schema")),
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)
    consumer._on_subscribe(consumer.client, None, 7, [1], None)
    consumer._on_message(consumer.client, None, Message(json.dumps({"bad": True}).encode()))
    assert consumer.client.acks == [(3, 1)]
    assert consumer.last_failure_kind == "terminal-handler"
    assert consumer.ready


def test_mqtt_callback_leaves_transient_failure_unacknowledged_and_reconnects(fake_mqtt):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: (_ for _ in ()).throw(OutboxCapacityExceeded("full")),
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_message(consumer.client, None, Message(b"{}"))
    assert consumer.client.acks == []
    assert consumer.client.reconnects == 1
    assert consumer.last_failure_kind == "transient-handler"


def test_mqtt_requires_stable_identity_and_nonzero_expiry(fake_mqtt):
    with pytest.raises(ValueError):
        EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None, client_id="", session_expiry_seconds=60)
    with pytest.raises(ValueError):
        EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None, client_id="edge-a", session_expiry_seconds=0)
def test_independent_consumers_each_receive_their_broker_fanout(fake_mqtt):
    received_a = []
    received_b = []
    first = EdgeMQTTConsumer("broker", 1883, None, "telemetry", received_a.append,
                             client_id="edge-a", session_expiry_seconds=60)
    second = EdgeMQTTConsumer("broker", 1883, None, "telemetry", received_b.append,
                              client_id="edge-b", session_expiry_seconds=60)
    message = Message(b'{"apiVersion":"v3"}')
    first._on_message(first.client, None, message)
    second._on_message(second.client, None, message)
    assert received_a == [{"apiVersion": "v3"}]
    assert received_b == [{"apiVersion": "v3"}]
    assert first.client.acks == [(3, 1)]
    assert second.client.acks == [(3, 1)]
def test_mqtt_recreated_consumer_resumes_stable_broker_session(fake_mqtt):
    first = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                             client_id="edge-a", session_expiry_seconds=60)
    restarted = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                 client_id="edge-a", session_expiry_seconds=60)
    assert first.client.connect_call[1]["clean_start"] is False
    assert restarted.client.connect_call[1]["clean_start"] is False
    assert restarted.connect_properties.SessionExpiryInterval == 60


def test_mqtt_readiness_requires_matching_suback_and_clears_on_disconnect(fake_mqtt):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)
    consumer._on_subscribe(consumer.client, None, 8, [0], None)
    assert consumer.connected and not consumer.ready
    consumer._on_subscribe(consumer.client, None, 7, [1], None)
    assert consumer.ready
    consumer._on_disconnect(consumer.client, None, None, 0, None)
    assert not consumer.connected and not consumer.ready
@pytest.mark.parametrize(("mid", "codes"), [(7, [0]), (7, [128]), (8, [1])])
def test_mqtt_readiness_requires_correlated_qos_one_suback(fake_mqtt, mid, codes):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)
    consumer._on_subscribe(consumer.client, None, mid, codes, None)
    assert not consumer.ready
    assert consumer.last_failure_kind == "subscribe"
    assert consumer.last_callback_error is not None


@pytest.mark.parametrize("ack_failure", [RuntimeError("socket closed"), 4])
def test_mqtt_unsuccessful_manual_ack_is_unacknowledged_and_reconnects(fake_mqtt, ack_failure):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)
    consumer._on_subscribe(consumer.client, None, 7, [1], None)
    calls = []

    def failed_ack(mid, qos):
        calls.append((mid, qos))
        if isinstance(ack_failure, BaseException):
            raise ack_failure
        return ack_failure

    consumer.client.ack = failed_ack
    consumer._on_message(consumer.client, None, Message(b"{}"))
    first_failure_at = consumer.last_failure_at
    consumer._on_message(consumer.client, None, Message(b"{}"))
    assert calls == [(3, 1), (3, 1)]
    assert consumer.client.acks == []
    assert consumer.last_failure_kind == "ack"
    assert consumer.last_failure_at is not None and consumer.last_failure_at >= first_failure_at
    assert consumer.failure_count == 2
    assert consumer.client.reconnects == 2
    assert not consumer.ready


def test_mqtt_clears_success_payload_diagnostics_only_after_confirmed_ack(fake_mqtt):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry", lambda event: None,
                                client_id="edge-a", session_expiry_seconds=60)
    consumer.last_callback_error = "stale payload diagnostic"
    consumer.last_failure_kind = "handler"
    consumer._on_message(consumer.client, None, Message(b"{}"))
    assert consumer.client.acks == [(3, 1)]
    assert consumer.last_callback_error is None
    assert consumer.last_failure_kind is None



@pytest.mark.parametrize("failure", [ValueError("bad"), TypeError("bad")])
def test_mqtt_generic_handler_errors_are_unacknowledged_and_diagnostic_monotonic(fake_mqtt, failure):
    consumer = EdgeMQTTConsumer("broker", 1883, None, "telemetry",
                                lambda event: (_ for _ in ()).throw(failure),
                                client_id="edge-a", session_expiry_seconds=60)
    consumer._on_connect(consumer.client, None, None, 0, None)
    consumer._on_subscribe(consumer.client, None, 7, [1], None)
    first_failure_at = consumer.last_failure_at
    consumer._on_message(consumer.client, None, Message(b"{}"))
    assert consumer.client.acks == []
    assert consumer.client.reconnects == 1
    assert consumer.last_failure_kind == "transient-handler"
    assert consumer.failure_count == 1
    assert consumer.last_failure_at is not None and (
        first_failure_at is None or consumer.last_failure_at >= first_failure_at
    )
    assert consumer.ready is False
