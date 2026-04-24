#!/usr/bin/env python3
from dataclasses import dataclass


NAMESPACE = "default"
NODE_NAME = "etri-dev0001-jetorn"
BROKER = "tcp://127.0.0.1:1883"
TOPIC_PREFIX = "factory/devices"
CYCLE_MS = 60000
OFFLINE_AFTER_MS = 15000
STATE_REPORT_CYCLE_MS = 5000


@dataclass(frozen=True)
class DeviceGroup:
    prefix: str
    count: int
    model: str
    telemetry_keys: list[str]
    status_keys: list[str]


GROUPS = [
    DeviceGroup("env", 8, "virtual-env-model", ["temperature", "humidity", "sampling_interval"], ["sampling_interval"]),
    DeviceGroup("vib", 6, "virtual-vib-model", ["vibration", "alarm", "sampling_interval"], ["sampling_interval"]),
    DeviceGroup("act", 6, "virtual-act-model", ["power", "mode", "sampling_interval"], ["sampling_interval"]),
]


def emit_device(group: DeviceGroup, index: int) -> str:
    device_name = f"{group.prefix}-device-{index:02d}"
    props = []
    for key in group.telemetry_keys:
        report_to_cloud = "true" if key in group.status_keys else "false"
        props.append(
            f"""  - name: {key}
    collectCycle: {CYCLE_MS}
    reportCycle: {CYCLE_MS}
    reportToCloud: {report_to_cloud}
    visitors:
      protocolName: mqttvirtual
      configData:
        dataType: string
        jsonKey: {key}"""
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
    docs = []
    for group in GROUPS:
        for i in range(1, group.count + 1):
            docs.append(emit_device(group, i))
    print("---\n".join(docs).rstrip())


if __name__ == "__main__":
    main()
