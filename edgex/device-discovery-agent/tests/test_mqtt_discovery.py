import json

import pytest

from app.mqtt_discovery import (
    MQTTDiscoveryError,
    parse_mqtt_self_registration,
)


def payload():
    return json.dumps(
        {
            "deviceId": "vibration-controller-001",
            "model": "vibration-sensor-v1",
            "profile": "vibration-sensor-v1",
            "resources": [
                "accelerationX",
                "accelerationY",
                "accelerationZ",
            ],
            "firmwareVersion": "1.1.0",
        }
    ).encode()


def test_mqtt_self_registration_validates_topic_and_schema():
    observation = parse_mqtt_self_registration(
        topic=(
            "edge/discovery/etri-dev0001-jetorn/"
            "vibration-controller-001"
        ),
        payload=payload(),
        expected_node_id="etri-dev0001-jetorn",
        retained=True,
    )

    assert observation["hardwareId"] == "vibration-controller-001"
    assert observation["recommendedProfile"] == "vibration-sensor-v1"
    assert observation["evidence"]["retained"] == "true"


def test_mqtt_self_registration_rejects_topic_node_mismatch():
    with pytest.raises(MQTTDiscoveryError, match="nodeId"):
        parse_mqtt_self_registration(
            topic="edge/discovery/other-node/vibration-controller-001",
            payload=payload(),
            expected_node_id="etri-dev0001-jetorn",
            retained=False,
        )
