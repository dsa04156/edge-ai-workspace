#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Dict, Iterable, Tuple

from sense_hat import SenseHat


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1883
DEFAULT_NODE = "etri-dev0003-raspi5"
DEFAULT_ALIAS = "sensehat-001"


def _mqtt_utf8(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(2, "big") + encoded


def _remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
        if length == 0:
            return bytes(encoded)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("MQTT broker closed the connection")
        chunks.extend(chunk)
    return bytes(chunks)


class SimpleMqttPublisher:
    def __init__(self, host: str, port: int, client_id: str, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout

    def __enter__(self) -> "SimpleMqttPublisher":
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        variable_header = _mqtt_utf8("MQTT") + bytes([4, 2]) + (30).to_bytes(2, "big")
        payload = _mqtt_utf8(self.client_id)
        packet = bytes([0x10]) + _remaining_length(len(variable_header) + len(payload)) + variable_header + payload
        self.sock.sendall(packet)
        response = _read_exact(self.sock, 4)
        if response != b"\x20\x02\x00\x00":
            raise ConnectionError(f"unexpected MQTT CONNACK: {response!r}")
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.sock.sendall(b"\xe0\x00")
        finally:
            self.sock.close()

    def publish(self, topic: str, payload: Dict[str, object]) -> None:
        message = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        variable_header = _mqtt_utf8(topic)
        packet = bytes([0x30]) + _remaining_length(len(variable_header) + len(message)) + variable_header + message
        self.sock.sendall(packet)


def read_sensehat(sense: SenseHat) -> Dict[str, float]:
    orientation = sense.get_orientation()
    gyro = sense.get_gyroscope_raw()
    return {
        "temp_humidity": round(float(sense.get_temperature_from_humidity()), 3),
        "temp_pressure": round(float(sense.get_temperature_from_pressure()), 3),
        "humidity": round(float(sense.get_humidity()), 3),
        "pressure": round(float(sense.get_pressure()), 3),
        "compass": round(float(sense.get_compass()), 3),
        "pitch": round(float(orientation["pitch"]), 3),
        "roll": round(float(orientation["roll"]), 3),
        "yaw": round(float(orientation["yaw"]), 3),
        "gyro_x": round(float(gyro["x"]), 6),
        "gyro_y": round(float(gyro["y"]), 6),
        "gyro_z": round(float(gyro["z"]), 6),
    }


def topic_payloads(prefix: str, readings: Dict[str, float]) -> Iterable[Tuple[str, Dict[str, float]]]:
    yield f"{prefix}/temperature", {
        "temp_humidity": readings["temp_humidity"],
        "temp_pressure": readings["temp_pressure"],
    }
    yield f"{prefix}/humidity", {"humidity": readings["humidity"]}
    yield f"{prefix}/pressure", {"pressure": readings["pressure"]}
    yield f"{prefix}/compass", {"compass": readings["compass"]}
    yield f"{prefix}/orientation", {
        "pitch": readings["pitch"],
        "roll": readings["roll"],
        "yaw": readings["yaw"],
    }
    yield f"{prefix}/gyroscope", {
        "gyro_x": readings["gyro_x"],
        "gyro_y": readings["gyro_y"],
        "gyro_z": readings["gyro_z"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish Sense HAT readings to mqttvirtual topics")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--node", default=DEFAULT_NODE)
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--client-id", default="sensehat-publisher-dev0003")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sense = SenseHat()
    prefix = f"etri/{args.node}/{args.alias}"

    while True:
        readings = read_sensehat(sense)
        with SimpleMqttPublisher(args.host, args.port, args.client_id) as mqtt:
            for topic, payload in topic_payloads(prefix, readings):
                mqtt.publish(topic, payload)
                print(json.dumps({"topic": topic, "payload": payload}, ensure_ascii=True), flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"sensehat publisher error: {exc}", file=sys.stderr)
        raise SystemExit(1)
