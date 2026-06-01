from __future__ import annotations

import os
import socket
from typing import Any


def get_mqtt_status() -> dict[str, Any]:
    host = os.getenv("MQTT_HOST", "mqtt-broker.default.svc")
    port = int(os.getenv("MQTT_PORT", "1883"))
    timeout = float(os.getenv("MQTT_TIMEOUT_SECONDS", "3"))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"host": host, "port": port, "reachable": True}
    except OSError as exc:
        return {"host": host, "port": port, "reachable": False, "error": str(exc)}
