from __future__ import annotations

import json
import sys
import uuid
from types import SimpleNamespace


sys.modules.setdefault("sense_hat", SimpleNamespace(SenseHat=object))

from sensehat_publisher import DirectAgentPublisher, build_edgex_events


READINGS = {
    "temp_humidity": 21.1,
    "temp_pressure": 21.2,
    "humidity": 45.3,
    "pressure": 1008.4,
    "compass": 91.5,
    "pitch": 1.6,
    "roll": 2.7,
    "yaw": 3.8,
    "gyro_x": 0.01,
    "gyro_y": 0.02,
    "gyro_z": 0.03,
}


def test_build_edgex_events_maps_sensehat_sources_without_mqtt() -> None:
    events = list(build_edgex_events(
        READINGS,
        node="etri-dev0003-raspi5",
        alias="sensehat-001",
        origin=123456789,
    ))

    assert [event["sourceName"] for event in events] == [
        "temperature",
        "humidity",
        "pressure",
        "compass",
        "orientation",
        "gyroscope",
    ]
    assert all(event["apiVersion"] == "v3" for event in events)
    assert all(event["deviceName"] == "sensehat-001" for event in events)
    assert all(event["profileName"] == "etri-sensehat" for event in events)
    assert all(event["origin"] == 123456789 for event in events)
    assert all(event["tags"] == {
        "edge_node_id": "etri-dev0003-raspi5",
        "source_adapter": "i2c",
    } for event in events)
    assert len({uuid.UUID(event["id"]) for event in events}) == 6
    assert [[reading["resourceName"] for reading in event["readings"]] for event in events] == [
        ["temp_humidity", "temp_pressure"],
        ["humidity"],
        ["pressure"],
        ["compass"],
        ["pitch", "roll", "yaw"],
        ["gyro_x", "gyro_y", "gyro_z"],
    ]
    assert all(
        reading["valueType"] == "Float64"
        and reading["deviceName"] == event["deviceName"]
        and reading["profileName"] == event["profileName"]
        and reading["origin"] == event["origin"]
        for event in events
        for reading in event["readings"]
    )


def test_direct_agent_publisher_requires_durable_queue_ack() -> None:
    event = next(iter(build_edgex_events(
        READINGS,
        node="etri-dev0003-raspi5",
        alias="sensehat-001",
        origin=123456789,
    )))
    captured = {}

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({
                "status": "queued",
                "edge_id": "etri-dev0003-raspi5",
                "event_id": event["id"],
                "deduplicated": False,
            }).encode()

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    publisher = DirectAgentPublisher(
        "http://127.0.0.1:18080/v1/events",
        edge_id="etri-dev0003-raspi5",
        timeout=2.5,
        opener=opener,
    )
    ack = publisher.publish(event)

    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:18080/v1/events"
    assert request.method == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == event
    assert captured["timeout"] == 2.5
    assert ack["event_id"] == event["id"]


def test_direct_agent_publisher_rejects_ambiguous_ack() -> None:
    event = next(iter(build_edgex_events(
        READINGS,
        node="etri-dev0003-raspi5",
        alias="sensehat-001",
        origin=123456789,
    )))

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({
                "status": "queued",
                "edge_id": "wrong-edge",
                "event_id": event["id"],
                "deduplicated": False,
            }).encode()

    publisher = DirectAgentPublisher(
        "http://127.0.0.1:18080/v1/events",
        edge_id="etri-dev0003-raspi5",
        opener=lambda request, timeout: Response(),
    )

    try:
        publisher.publish(event)
    except RuntimeError as error:
        assert "acknowledgement" in str(error)
    else:
        raise AssertionError("publisher accepted an acknowledgement for the wrong edge")
