from __future__ import annotations

import json
import re
from typing import Any


TOPIC_PATTERN = re.compile(
    r"^edge/discovery/(?P<node>[^/]+)/(?P<device>[^/]+)$"
)


class MQTTDiscoveryError(ValueError):
    pass


def parse_mqtt_self_registration(
    *,
    topic: str,
    payload: bytes,
    expected_node_id: str,
    retained: bool,
) -> dict[str, Any]:
    match = TOPIC_PATTERN.fullmatch(topic)
    if match is None:
        raise MQTTDiscoveryError("MQTT discovery topic is invalid")
    if match.group("node") != expected_node_id:
        raise MQTTDiscoveryError("MQTT discovery topic nodeId does not match")
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise MQTTDiscoveryError(
            "MQTT discovery payload is not valid JSON"
        ) from exc
    if not isinstance(body, dict):
        raise MQTTDiscoveryError("MQTT discovery payload must be an object")
    allowed = {
        "deviceId",
        "model",
        "profile",
        "resources",
        "firmwareVersion",
    }
    if set(body) - allowed:
        raise MQTTDiscoveryError(
            "MQTT discovery payload contains unsupported fields"
        )
    device_id = body.get("deviceId")
    model = body.get("model")
    profile = body.get("profile")
    resources = body.get("resources")
    if (
        not isinstance(device_id, str)
        or not device_id
        or match.group("device") != device_id
    ):
        raise MQTTDiscoveryError(
            "MQTT discovery deviceId must match the topic"
        )
    if not isinstance(model, str) or not model:
        raise MQTTDiscoveryError("MQTT discovery model is required")
    if not isinstance(profile, str) or not profile:
        raise MQTTDiscoveryError("MQTT discovery profile is required")
    if (
        not isinstance(resources, list)
        or not resources
        or any(not isinstance(item, str) or not item for item in resources)
        or len(resources) != len(set(resources))
    ):
        raise MQTTDiscoveryError(
            "MQTT discovery resources must be unique strings"
        )
    firmware = body.get("firmwareVersion")
    if firmware is not None and not isinstance(firmware, str):
        raise MQTTDiscoveryError(
            "MQTT discovery firmwareVersion must be a string"
        )
    return {
        "hardwareKey": device_id,
        "hardwareId": device_id,
        "protocol": "mqtt",
        "transport": "mqtt-self-registration",
        "displayName": device_id,
        "model": model,
        "firmwareVersion": firmware,
        "capabilities": resources,
        "recommendedProfile": profile,
        "matchConfidence": "exact",
        "properties": {
            "DiscoveryTopic": topic,
        },
        "evidence": {
            "scope": "mqtt-self-registration",
            "retained": "true" if retained else "false",
            "telemetrySeparated": "true",
        },
    }
