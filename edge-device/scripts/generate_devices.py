#!/usr/bin/env python3
import os
from dataclasses import dataclass


NAMESPACE = "default"
NODE_NAME = os.getenv("EDGE_NODE_NAME", "etri-dev0001-jetorn")
BROKER = "tcp://127.0.0.1:1883"
TOPIC_PREFIX = "factory/devices"
CYCLE_MS = 60000
OFFLINE_AFTER_MS = 15000
STATE_REPORT_CYCLE_MS = 30000
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb.telemetry.svc.cluster.local:8086")
INFLUX_ORG = os.getenv("INFLUX_ORG", "edgeai")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "device_telemetry")
INFLUX_MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "virtual_device_telemetry")
DEVICE_PLAN = os.getenv("DEVICE_PLAN", "jetson")


@dataclass(frozen=True)
class DeviceGroup:
    prefix: str
    count: int
    model: str
    telemetry_keys: list[str]
    status_keys: list[str]


GROUPS = [
    DeviceGroup(
        "env",
        8,
        "virtual-env-model",
        ["temperature", "humidity", "health", "sampling_interval"],
        ["temperature", "humidity", "health", "sampling_interval"],
    ),
    DeviceGroup(
        "vib",
        6,
        "virtual-vib-model",
        ["vibration", "severity", "alarm_latched", "health", "sampling_interval"],
        ["vibration", "severity", "alarm_latched", "health", "sampling_interval"],
    ),
    DeviceGroup(
        "act",
        6,
        "virtual-act-model",
        ["power", "mode", "health", "sampling_interval"],
        ["power", "mode", "health", "sampling_interval"],
    ),
]

RPI_GROUPS = [
    DeviceGroup(
        "rpi-env",
        4,
        "virtual-env-model",
        ["temperature", "humidity", "health", "sampling_interval"],
        ["temperature", "humidity", "health", "sampling_interval"],
    ),
    DeviceGroup(
        "rpi-vib",
        3,
        "virtual-vib-model",
        ["vibration", "severity", "alarm_latched", "health", "sampling_interval"],
        ["vibration", "severity", "alarm_latched", "health", "sampling_interval"],
    ),
    DeviceGroup(
        "rpi-act",
        3,
        "virtual-act-model",
        ["power", "mode", "health", "sampling_interval"],
        ["power", "mode", "health", "sampling_interval"],
    ),
]


def should_store_to_influx(key: str) -> bool:
    return key in {"temperature", "humidity", "vibration"}


def emit_influx_push_method(device_name: str, device_type: str, key: str) -> str:
    return f"""
    pushMethod:
      dbMethod:
        influxdb2:
          influxdb2ClientConfig:
            url: {INFLUX_URL}
            org: {INFLUX_ORG}
            bucket: {INFLUX_BUCKET}
          influxdb2DataConfig:
            measurement: {INFLUX_MEASUREMENT}
            tag:
              device_id: {device_name}
              device_type: {device_type}
              property: {key}
            fieldKey: value"""


def emit_device(group: DeviceGroup, index: int) -> str:
    device_name = f"{group.prefix}-device-{index:02d}"
    props = []
    for key in group.telemetry_keys:
        report_to_cloud = "true" if key in group.status_keys else "false"
        push_method = emit_influx_push_method(device_name, group.prefix, key) if should_store_to_influx(key) else ""
        props.append(
            f"""  - name: {key}
    collectCycle: {CYCLE_MS}
    reportCycle: {CYCLE_MS}
    reportToCloud: {report_to_cloud}
    visitors:
      protocolName: mqttvirtual
      configData:
        dataType: string
        jsonKey: {key}{push_method}"""
        )
    properties = "\n".join(props)
    return f"""apiVersion: devices.kubeedge.io/v1beta1
kind: Device
metadata:
  name: {device_name}
  namespace: {NAMESPACE}
spec:
  deviceModelRef:
    name: {group.model}
  nodeName: {NODE_NAME}
  properties:
{properties}
  protocol:
    protocolName: mqttvirtual
    configData:
      broker: {BROKER}
      subTopic: {TOPIC_PREFIX}/{device_name}/telemetry
      pubTopic: {TOPIC_PREFIX}/{device_name}/command
      clientID: {device_name}-client
      username: ""
      password: ""
      qos: 1
      offlineAfterMs: {OFFLINE_AFTER_MS}
status:
  reportToCloud: true
  reportCycle: {STATE_REPORT_CYCLE_MS}
"""


def main() -> None:
    groups = RPI_GROUPS if DEVICE_PLAN == "rpi" else GROUPS
    docs = []
    for group in groups:
        for i in range(1, group.count + 1):
            docs.append(emit_device(group, i))
    print("---\n".join(docs).rstrip())


if __name__ == "__main__":
    main()
