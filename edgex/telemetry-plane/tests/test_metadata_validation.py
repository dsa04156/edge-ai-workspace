from __future__ import annotations

import json
from types import SimpleNamespace

from telemetry_plane.metadata_validation import MetadataValidationResponder


DEVICE = {
    "name": "sensehat-001",
    "description": "Sense HAT attached to etri-dev0003-raspi5",
    "adminState": "UNLOCKED",
    "operatingState": "UP",
    "serviceName": "edge-telemetry-agent",
    "profileName": "etri-sensehat",
    "labels": ["i2c", "sensehat", "etri-poc"],
    "protocols": {"i2c": {"Bus": "1", "Adapter": "edge-telemetry-agent"}},
    "tags": {
        "edge_node_id": "etri-dev0003-raspi5",
        "source_adapter": "i2c",
    },
    "properties": {},
}


def envelope(device: dict | None = None) -> dict:
    return {
        "apiVersion": "v3",
        "receivedTopic": "",
        "correlationID": "11111111-1111-4111-8111-111111111111",
        "requestID": "22222222-2222-4222-8222-222222222222",
        "errorCode": 0,
        "payload": {
            "apiVersion": "v3",
            "requestId": "33333333-3333-4333-8333-333333333333",
            "device": DEVICE if device is None else device,
        },
        "contentType": "application/json",
    }


class FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, int]] = []

    def publish(self, topic: str, payload: bytes, qos: int):
        self.published.append((topic, payload, qos))
        return SimpleNamespace(rc=0)


def responder() -> tuple[MetadataValidationResponder, FakeClient]:
    client = FakeClient()
    return MetadataValidationResponder(
        "messagebus",
        1883,
        "edge-telemetry-agent",
        [DEVICE],
        client=client,
    ), client


def test_validation_responder_accepts_only_the_exact_contract_device() -> None:
    service, client = responder()
    message = SimpleNamespace(
        topic="edgex/edge-telemetry-agent/validate/device",
        payload=json.dumps(envelope()).encode(),
    )

    service.on_message(client, None, message)

    assert len(client.published) == 1
    topic, payload, qos = client.published[0]
    assert topic == (
        "edgex/response/edge-telemetry-agent/"
        "22222222-2222-4222-8222-222222222222"
    )
    assert qos == 0
    assert json.loads(payload) == {
        "apiVersion": "v3",
        "receivedTopic": "",
        "correlationID": "11111111-1111-4111-8111-111111111111",
        "requestID": "22222222-2222-4222-8222-222222222222",
        "errorCode": 0,
        "payload": None,
        "contentType": "application/json",
    }


def test_validation_responder_rejects_contract_drift() -> None:
    service, client = responder()
    changed = {**DEVICE, "operatingState": "DOWN"}
    message = SimpleNamespace(
        topic="edgex/edge-telemetry-agent/validate/device",
        payload=json.dumps(envelope(changed)).encode(),
    )

    service.on_message(client, None, message)

    response = json.loads(client.published[0][1])
    assert response["requestID"] == "22222222-2222-4222-8222-222222222222"
    assert response["errorCode"] == 1
    assert response["contentType"] == "text/plain"
    assert "approved Metadata contract" in response["payload"]


def test_validation_responder_drops_unaddressable_malformed_envelopes() -> None:
    service, client = responder()
    malformed = envelope()
    malformed["requestID"] = "not-a-uuid"
    message = SimpleNamespace(
        topic="edgex/edge-telemetry-agent/validate/device",
        payload=json.dumps(malformed).encode(),
    )

    service.on_message(client, None, message)

    assert client.published == []
    assert service.last_error == "validation envelope requestID must be a UUID"
