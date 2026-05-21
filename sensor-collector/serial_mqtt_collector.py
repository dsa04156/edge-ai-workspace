import json
import os
import time
import socket
from dataclasses import dataclass, field
from typing import Any

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyACM0")
BAUDRATE = int(os.getenv("BAUDRATE", "115200"))
SERIAL_TIMEOUT_SECONDS = float(os.getenv("SERIAL_TIMEOUT_SECONDS", "2"))

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_KEEPALIVE_SECONDS = int(os.getenv("MQTT_KEEPALIVE_SECONDS", "60"))

SITE = os.getenv("SITE", "etri")
EDGE_NODE = os.getenv("EDGE_NODE", socket.gethostname())
SOURCE_TIMESTAMP_FIELDS = ("source_ts", "ts", "timestamp", "sample_ts", "sample_time")


@dataclass
class PublishRecord:
    topic: str
    payload: str
    reason: str = "publish"


@dataclass
class CollectorState:
    """Tracks last source sample per MQTT topic so stale serial data is not republished as fresh."""

    last_signature_by_topic: dict[str, tuple[Any, str]] = field(default_factory=dict)


def _source_timestamp(data: dict[str, Any]) -> Any:
    for field_name in SOURCE_TIMESTAMP_FIELDS:
        if field_name in data and data[field_name] not in (None, ""):
            return data[field_name]
    return None


def _sample_fingerprint(data: dict[str, Any]) -> str:
    ignored = {"received_at", "collector_received_at", "edge_node"}
    stable = {key: value for key, value in data.items() if key not in ignored}
    return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_publish_record(line: str, state: CollectorState, now: int | None = None, edge_node: str = EDGE_NODE, site: str = SITE) -> PublishRecord | None:
    """Convert one newly read serial line to an MQTT publish record.

    The collector must not make a stale/repeated sensor sample look fresh by stamping
    a new collector receive time on the same final serial line. A sample is considered
    new only when its source timestamp/sequence or payload fingerprint changes.
    """

    line = (line or "").strip()
    if not line:
        return None

    data = json.loads(line)
    sensor = data.get("sensor")
    device_id = data.get("device_id", "arduino-001")
    if not sensor:
        print(f"[SKIP] missing sensor field: {data}")
        return None

    topic = f"{site}/{edge_node}/{device_id}/{sensor}"
    source_ts = _source_timestamp(data)
    fingerprint = _sample_fingerprint(data)
    signature = (source_ts, fingerprint)

    if state.last_signature_by_topic.get(topic) == signature:
        print(f"[SKIP] duplicate/stale serial sample topic={topic} source_ts={source_ts}")
        return None
    state.last_signature_by_topic[topic] = signature

    payload_data = dict(data)
    if source_ts is not None:
        payload_data["source_ts"] = source_ts
    payload_data["edge_node"] = edge_node
    payload_data["collector_received_at"] = int(time.time()) if now is None else int(now)
    payload_data.pop("received_at", None)

    return PublishRecord(topic=topic, payload=json.dumps(payload_data, ensure_ascii=False))


def run_collector() -> None:
    import serial
    import paho.mqtt.client as mqtt

    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=SERIAL_TIMEOUT_SECONDS)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE_SECONDS)
    client.loop_start()
    state = CollectorState()

    print(f"[START] edge_node={EDGE_NODE}, serial={SERIAL_PORT}, mqtt={MQTT_HOST}:{MQTT_PORT}")
    while True:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            record = build_publish_record(line, state)
            if record is None:
                continue
            result = client.publish(record.topic, record.payload)
            if hasattr(result, "rc") and result.rc != 0:
                print(f"[MQTT_WARN] publish rc={result.rc} topic={record.topic}")
            print(f"[PUB] {record.topic} {record.payload}")

        except json.JSONDecodeError:
            print(f"[SKIP] invalid json: {line if 'line' in locals() else ''}")

        except serial.SerialException as e:
            print(f"[SERIAL_ERROR] {e}")
            time.sleep(2)

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(1)


if __name__ == "__main__":
    run_collector()
