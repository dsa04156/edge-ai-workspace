#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import signal
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List

try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError:
    mqtt = None


BROKER_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "factory/devices").rstrip("/")
QOS = int(os.getenv("MQTT_QOS", "1"))
PUBLISH_JITTER = float(os.getenv("PUBLISH_JITTER", "0.3"))
ENABLE_HEARTBEAT = os.getenv("ENABLE_HEARTBEAT", "0") not in {"0", "false", "False"}
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
DEVICE_FILTER = {item.strip() for item in os.getenv("DEVICE_FILTER", "").split(",") if item.strip()}
DEVICE_PLAN = os.getenv("DEVICE_PLAN", "all").strip().lower()
SELF_TEST = os.getenv("SELF_TEST", "0") in {"1", "true", "True"}
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "stable").strip().lower()
ACT_STATE_CHANGE_PROBABILITY = float(os.getenv("ACT_STATE_CHANGE_PROBABILITY", "0.0"))
VIB_NORMAL_MAX = float(os.getenv("VIB_NORMAL_MAX", "1.0"))
VIB_ALARM_HIGH_THRESHOLD = float(os.getenv("VIB_ALARM_HIGH_THRESHOLD", "1.8"))
VIB_ALARM_LOW_THRESHOLD = float(os.getenv("VIB_ALARM_LOW_THRESHOLD", "1.2"))
VIB_ALARM_SET_COUNT = int(os.getenv("VIB_ALARM_SET_COUNT", "2"))
VIB_ALARM_CLEAR_COUNT = int(os.getenv("VIB_ALARM_CLEAR_COUNT", "3"))

JETSON_NODE = "etri-dev0001-jetorn"
RPI_NODE = "etri-dev0002-raspi5"


@dataclass
class VirtualDevice:
    device_id: str
    device_type: str
    interval: int
    last_power: str = "on"
    last_mode: str = "auto"
    alarm_latched: bool = False
    alarm_high_count: int = 0
    alarm_low_count: int = 0

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
                "health": "ok",
                "sampling_interval": str(self.interval),
            }

        if self.device_type == "vib":
            upper_bound = 2.5 if SIMULATION_MODE in {"random", "fault", "faulty"} else VIB_NORMAL_MAX
            vibration = round(random.uniform(0.2, upper_bound), 3)
            if vibration >= VIB_ALARM_HIGH_THRESHOLD:
                self.alarm_high_count += 1
                self.alarm_low_count = 0
            elif vibration <= VIB_ALARM_LOW_THRESHOLD:
                self.alarm_low_count += 1
                self.alarm_high_count = 0
            else:
                self.alarm_high_count = 0
                self.alarm_low_count = 0

            if self.alarm_high_count >= VIB_ALARM_SET_COUNT:
                self.alarm_latched = True
            if self.alarm_low_count >= VIB_ALARM_CLEAR_COUNT:
                self.alarm_latched = False

            if self.alarm_latched:
                severity = "critical"
            elif vibration >= VIB_ALARM_LOW_THRESHOLD:
                severity = "warning"
            else:
                severity = "normal"

            return {
                "vibration": str(vibration),
                "severity": severity,
                "alarm_latched": "true" if self.alarm_latched else "false",
                "health": "degraded" if self.alarm_latched else "ok",
                "sampling_interval": str(self.interval),
            }

        if self.device_type == "act":
            if SIMULATION_MODE in {"random", "fault", "faulty"} and random.random() < ACT_STATE_CHANGE_PROBABILITY:
                self.last_power = "off" if self.last_power == "on" else "on"
            if SIMULATION_MODE in {"random", "fault", "faulty"} and random.random() < ACT_STATE_CHANGE_PROBABILITY:
                choices = [item for item in ["auto", "manual", "idle"] if item != self.last_mode]
                self.last_mode = random.choice(choices)
            return {
                "power": self.last_power,
                "mode": self.last_mode,
                "health": "offline" if self.last_power == "off" else "ok",
                "sampling_interval": str(self.interval),
            }

        if self.device_type == "temp":
            temperature = random.randint(280, 320)
            return {
                "temperature": str(temperature),
                "health": "ok",
                "sampling_interval": str(self.interval),
            }

        return {
            "health": "unknown",
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

    VirtualDevice("temp-device-01", "temp", 5),

    VirtualDevice("rpi-env-device-01", "env", 5),
    VirtualDevice("rpi-env-device-02", "env", 5),
    VirtualDevice("rpi-env-device-03", "env", 5),
    VirtualDevice("rpi-env-device-04", "env", 5),

    VirtualDevice("rpi-vib-device-01", "vib", 5),
    VirtualDevice("rpi-vib-device-02", "vib", 5),
    VirtualDevice("rpi-vib-device-03", "vib", 5),

    VirtualDevice("rpi-act-device-01", "act", 5),
    VirtualDevice("rpi-act-device-02", "act", 5),
    VirtualDevice("rpi-act-device-03", "act", 5),
]


RPI_DEVICE_IDS = {
    "rpi-act-device-01",
    "rpi-act-device-02",
    "rpi-act-device-03",
    "rpi-env-device-01",
    "rpi-env-device-02",
    "rpi-env-device-03",
    "rpi-env-device-04",
    "rpi-vib-device-01",
    "rpi-vib-device-02",
    "rpi-vib-device-03",
}

DEVICE_PLANS = {
    "all": None,
    "jetson": {
        "node": JETSON_NODE,
        "devices": {
            "act-device-01",
            "act-device-02",
            "act-device-03",
            "act-device-04",
            "act-device-05",
            "act-device-06",
            "env-device-01",
            "env-device-02",
            "env-device-03",
            "env-device-04",
            "env-device-05",
            "env-device-06",
            "env-device-07",
            "env-device-08",
            "vib-device-01",
            "vib-device-02",
            "vib-device-03",
            "vib-device-04",
            "vib-device-05",
            "vib-device-06",
            "temp-device-01",
        },
    },
    "rpi": {
        "node": RPI_NODE,
        "devices": RPI_DEVICE_IDS,
    },
    "raspi": {
        "node": RPI_NODE,
        "devices": RPI_DEVICE_IDS,
    },
}


def select_devices() -> List[VirtualDevice]:
    plan = DEVICE_PLANS.get(DEVICE_PLAN)
    plan_devices = None if plan is None else plan["devices"]
    return [
        d
        for d in DEVICES
        if (plan_devices is None or d.device_id in plan_devices)
        and (not DEVICE_FILTER or d.device_id in DEVICE_FILTER)
    ]


def selected_node() -> str:
    plan = DEVICE_PLANS.get(DEVICE_PLAN)
    if plan is None:
        return "all"
    return plan["node"]


def expected_keys(device_type: str) -> set[str]:
    if device_type == "env":
        return {"temperature", "humidity", "health", "sampling_interval"}
    if device_type == "vib":
        return {"vibration", "severity", "alarm_latched", "health", "sampling_interval"}
    if device_type == "act":
        return {"power", "mode", "health", "sampling_interval"}
    if device_type == "temp":
        return {"temperature", "health", "sampling_interval"}
    return {"health", "sampling_interval"}


def run_self_test(devices: Iterable[VirtualDevice]) -> int:
    failures = 0
    for device in devices:
        payload = device.build_payload()
        keys = set(payload)
        expected = expected_keys(device.device_type)
        if keys != expected:
            print(f"[FAIL] {device.device_id} payload keys={sorted(keys)} expected={sorted(expected)}")
            failures += 1
        if device.telemetry_topic() != f"{TOPIC_PREFIX}/{device.device_id}/telemetry":
            print(f"[FAIL] {device.device_id} telemetry topic={device.telemetry_topic()}")
            failures += 1
        if device.command_topic() != f"{TOPIC_PREFIX}/{device.device_id}/command":
            print(f"[FAIL] {device.device_id} command topic={device.command_topic()}")
            failures += 1
        heartbeat = device.build_heartbeat()
        if heartbeat.get("status") != "online" or heartbeat.get("device_id") != device.device_id:
            print(f"[FAIL] {device.device_id} heartbeat={heartbeat}")
            failures += 1

    if failures:
        print(f"[ERROR] self test failed: {failures}")
        return 1
    print("[INFO] self test passed")
    return 0


running = True


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[INFO] Connected to MQTT broker {BROKER_HOST}:{BROKER_PORT}")
        for device in userdata["devices"]:
            client.subscribe(device.command_topic(), qos=QOS)
            print(f"[SUB] {device.command_topic()}")
    else:
        print(f"[ERROR] MQTT connect failed, rc={rc}")


def on_disconnect(client, userdata, flags, rc, properties=None):
    print(f"[WARN] Disconnected from MQTT broker, rc={rc}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    print(f"[CMD] {msg.topic} <- {payload}")
    for device in userdata["devices"]:
        if msg.topic != device.command_topic():
            continue
        try:
            body = json.loads(payload)
        except json.JSONDecodeError:
            return
        if "sampling_interval" in body:
            try:
                device.interval = int(body["sampling_interval"])
                print(f"[APPLY] {device.device_id} sampling_interval={device.interval}")
            except (TypeError, ValueError):
                pass
        return


def handle_signal(signum, frame):
    global running
    running = False
    print("\n[INFO] Stopping publisher...")


def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if DEVICE_PLAN not in DEVICE_PLANS:
        allowed = ", ".join(sorted(DEVICE_PLANS))
        print(f"[ERROR] Unknown DEVICE_PLAN={DEVICE_PLAN!r}. Allowed values: {allowed}")
        sys.exit(1)

    devices = select_devices()
    if not devices:
        print(f"[ERROR] No devices selected. Check DEVICE_PLAN={DEVICE_PLAN!r} and DEVICE_FILTER.")
        sys.exit(1)

    if SELF_TEST:
        sys.exit(run_self_test(devices))

    if mqtt is None:
        print("[ERROR] paho-mqtt is required unless SELF_TEST=1")
        sys.exit(1)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"virtual-sensor-publisher-{os.uname().nodename}",
        userdata={"devices": devices},
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    print(f"[INFO] topic prefix: {TOPIC_PREFIX}")
    print(
        f"[INFO] broker={BROKER_HOST}:{BROKER_PORT} "
        f"qos={QOS} heartbeat={ENABLE_HEARTBEAT} "
        f"heartbeat_topic=legacy-debug-only "
        f"device_plan={DEVICE_PLAN} target_node={selected_node()} "
        f"device_count={len(devices)}"
    )
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
