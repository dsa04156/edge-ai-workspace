#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import signal
import sys
import time
from dataclasses import dataclass
from typing import Dict, List

import paho.mqtt.client as mqtt


BROKER_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "factory/devices").rstrip("/")
QOS = int(os.getenv("MQTT_QOS", "1"))
PUBLISH_JITTER = float(os.getenv("PUBLISH_JITTER", "0.3"))
ENABLE_HEARTBEAT = os.getenv("ENABLE_HEARTBEAT", "1") not in {"0", "false", "False"}
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
DEVICE_FILTER = {item.strip() for item in os.getenv("DEVICE_FILTER", "").split(",") if item.strip()}


@dataclass
class VirtualDevice:
    device_id: str
    device_type: str
    interval: int

    def telemetry_topic(self) -> str:
        return f"{TOPIC_PREFIX}/{self.device_id}/telemetry"

    def command_topic(self) -> str:
        return f"{TOPIC_PREFIX}/{self.device_id}/command"

    def heartbeat_topic(self) -> str:
        return f"{TOPIC_PREFIX}/{self.device_id}/heartbeat"

    def build_payload(self) -> Dict[str, str]:
        if self.device_type == "env":
            temperature = random.randint(275, 305)
            humidity = random.randint(35, 65)
            return {
                "temperature": str(temperature),
                "humidity": str(humidity),
                "sampling_interval": str(self.interval),
            }

        if self.device_type == "vib":
            vibration = round(random.uniform(0.2, 2.5), 3)
            alarm = "true" if vibration >= 1.8 else "false"
            return {
                "vibration": str(vibration),
                "alarm": alarm,
                "sampling_interval": str(self.interval),
            }

        if self.device_type == "act":
            power = random.choice(["on", "off"])
            mode = random.choice(["auto", "manual", "idle"])
            return {
                "power": power,
                "mode": mode,
                "sampling_interval": str(self.interval),
            }

        if self.device_type == "temp":
            temperature = random.randint(280, 320)
            return {
                "temperature": str(temperature),
                "sampling_interval": str(self.interval),
            }

        return {
            "status": "unknown",
            "sampling_interval": str(self.interval),
        }

    def build_heartbeat(self) -> Dict[str, str]:
        return {
            "device_id": self.device_id,
            "status": "online",
            "ts": str(int(time.time())),
        }


DEVICES: List[VirtualDevice] = [
    VirtualDevice("act-device-01", "act", 5),
    VirtualDevice("act-device-02", "act", 5),
    VirtualDevice("act-device-03", "act", 5),
    VirtualDevice("act-device-04", "act", 5),
    VirtualDevice("act-device-05", "act", 5),
    VirtualDevice("act-device-06", "act", 5),

    VirtualDevice("env-device-01", "env", 5),
    VirtualDevice("env-device-02", "env", 5),
    VirtualDevice("env-device-03", "env", 5),
    VirtualDevice("env-device-04", "env", 5),
    VirtualDevice("env-device-05", "env", 5),
    VirtualDevice("env-device-06", "env", 5),
    VirtualDevice("env-device-07", "env", 5),
    VirtualDevice("env-device-08", "env", 5),

    VirtualDevice("vib-device-01", "vib", 5),
    VirtualDevice("vib-device-02", "vib", 5),
    VirtualDevice("vib-device-03", "vib", 5),
    VirtualDevice("vib-device-04", "vib", 5),
    VirtualDevice("vib-device-05", "vib", 5),
    VirtualDevice("vib-device-06", "vib", 5),
]


running = True


def on_connect(client: mqtt.Client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[INFO] Connected to MQTT broker {BROKER_HOST}:{BROKER_PORT}")
        for device in DEVICES:
            client.subscribe(device.command_topic(), qos=QOS)
            print(f"[SUB] {device.command_topic()}")
    else:
        print(f"[ERROR] MQTT connect failed, rc={rc}")


def on_disconnect(client: mqtt.Client, userdata, flags, rc, properties=None):
    print(f"[WARN] Disconnected from MQTT broker, rc={rc}")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    payload = msg.payload.decode("utf-8", errors="replace")
    print(f"[CMD] {msg.topic} <- {payload}")


def handle_signal(signum, frame):
    global running
    running = False
    print("\n[INFO] Stopping publisher...")


def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="virtual-sensor-publisher")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    devices = [d for d in DEVICES if not DEVICE_FILTER or d.device_id in DEVICE_FILTER]
    if not devices:
        print("[ERROR] No devices selected. Check DEVICE_FILTER.")
        sys.exit(1)

    print(f"[INFO] topic prefix: {TOPIC_PREFIX}")
    print(f"[INFO] qos={QOS} heartbeat={ENABLE_HEARTBEAT} device_count={len(devices)}")

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    last_sent: Dict[str, float] = {d.device_id: 0.0 for d in devices}
    last_heartbeat: Dict[str, float] = {d.device_id: 0.0 for d in devices}

    try:
        while running:
            now = time.time()

            for device in devices:
                if now - last_sent[device.device_id] >= device.interval:
                    payload = device.build_payload()
                    payload["ts"] = str(int(now))

                    client.publish(
                        device.telemetry_topic(),
                        json.dumps(payload, ensure_ascii=False),
                        qos=QOS,
                        retain=False,
                    )

                    print(f"[PUB] {device.telemetry_topic()} -> {payload}")
                    last_sent[device.device_id] = now + random.uniform(0.0, PUBLISH_JITTER)

                if ENABLE_HEARTBEAT and now - last_heartbeat[device.device_id] >= HEARTBEAT_INTERVAL:
                    hb = device.build_heartbeat()
                    client.publish(
                        device.heartbeat_topic(),
                        json.dumps(hb, ensure_ascii=False),
                        qos=QOS,
                        retain=False,
                    )
                    print(f"[HB ] {device.heartbeat_topic()} -> {hb}")
                    last_heartbeat[device.device_id] = now

            time.sleep(0.2)

    finally:
        client.loop_stop()
        client.disconnect()
        print("[INFO] Publisher stopped.")


if __name__ == "__main__":
    main()
