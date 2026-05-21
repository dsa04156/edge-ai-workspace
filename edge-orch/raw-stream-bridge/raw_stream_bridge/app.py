from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass

import paho.mqtt.client as mqtt
import redis
from influxdb_client import InfluxDBClient, Point, WriteOptions

from raw_stream_bridge.core import Sample, normalize_mqtt_message, to_redis_latest_record, to_redis_stream_fields


@dataclass(frozen=True)
class BridgeConfig:
    mqtt_host: str = os.getenv("MQTT_HOST", "127.0.0.1")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_topics: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("MQTT_TOPICS", "factory/devices/+/telemetry,etri/+/+/+").split(",")
        if item.strip()
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://redis.telemetry.svc.cluster.local:6379/0")
    stream_key: str = os.getenv("STREAM_KEY", "telemetry:raw")
    latest_prefix: str = os.getenv("LATEST_PREFIX", "telemetry:latest")
    stream_maxlen: int = int(os.getenv("STREAM_MAXLEN", "1000000"))
    latest_ttl_seconds: int = int(os.getenv("LATEST_TTL_SECONDS", "60"))
    influx_url: str = os.getenv("INFLUX_URL", "http://influxdb.telemetry.svc.cluster.local:8086")
    influx_org: str = os.getenv("INFLUX_ORG", "edgeai")
    influx_bucket: str = os.getenv("INFLUX_BUCKET", "device_telemetry")
    influx_token: str = os.getenv("INFLUX_TOKEN", "")
    influx_measurement: str = os.getenv("INFLUX_MEASUREMENT", "raw_sensor_telemetry")
    influx_batch_size: int = int(os.getenv("INFLUX_BATCH_SIZE", "500"))
    influx_flush_interval_ms: int = int(os.getenv("INFLUX_FLUSH_INTERVAL_MS", "1000"))


class RawStreamBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.redis = redis.Redis.from_url(config.redis_url, decode_responses=True)
        self.influx = InfluxDBClient(url=config.influx_url, token=config.influx_token, org=config.influx_org)
        self.write_api = self.influx.write_api(
            write_options=WriteOptions(
                batch_size=config.influx_batch_size,
                flush_interval=config.influx_flush_interval_ms,
            )
        )

    def handle_payload(self, topic: str, payload: bytes) -> int:
        samples = normalize_mqtt_message(topic, payload)
        for sample in samples:
            self.write_sample(sample)
        return len(samples)

    def write_sample(self, sample: Sample) -> None:
        fields = to_redis_stream_fields(sample)
        self.redis.xadd(self.config.stream_key, fields, maxlen=self.config.stream_maxlen, approximate=True)
        latest_key, latest_fields = to_redis_latest_record(sample, self.config.latest_prefix)
        self.redis.hset(latest_key, mapping=latest_fields)
        self.redis.expire(latest_key, self.config.latest_ttl_seconds)

        point = (
            Point(self.config.influx_measurement)
            .tag("device_id", sample.device_id)
            .tag("sensor", sample.sensor)
            .tag("edge_node", sample.edge_node)
            .tag("source", "mqtt")
            .tag("schema_version", sample.schema_version)
            .field("value", _numeric_or_text(sample.value))
            .time(sample.timestamp_ms, write_precision="ms")
        )
        self.write_api.write(bucket=self.config.influx_bucket, org=self.config.influx_org, record=point)

    def close(self) -> None:
        self.write_api.flush()
        self.influx.close()


def _numeric_or_text(value):
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    try:
        return float(text)
    except ValueError:
        return text


def main() -> None:
    config = BridgeConfig()
    bridge = RawStreamBridge(config)
    stop = False

    def on_message(_client, _userdata, msg):
        try:
            count = bridge.handle_payload(msg.topic, msg.payload)
            if count:
                print(f"raw-stream-bridge wrote {count} sample(s) topic={msg.topic}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep bridge alive on bad payloads
            print(f"raw-stream-bridge error topic={msg.topic} err={exc}", flush=True)

    client = mqtt.Client(client_id=os.getenv("MQTT_CLIENT_ID", "raw-stream-bridge"))
    client.on_message = on_message
    client.connect(config.mqtt_host, config.mqtt_port, keepalive=60)
    for topic in config.mqtt_topics:
        client.subscribe(topic, qos=1)
    client.loop_start()

    def handle_stop(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    try:
        while not stop:
            time.sleep(1)
    finally:
        client.loop_stop()
        bridge.close()


if __name__ == "__main__":
    main()
