---
title: MQTT Topic 규칙
aliases:
  - MQTT Topic Policy
tags:
  - mqtt
  - telemetry
  - device
status: active
source:
  - docs/project-context.md
created: 2026-05-20
---

# MQTT Topic 규칙

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

## 의미

- `telemetry`: 센서 또는 `test_device.py`가 발행하고 mapper가 구독한다.
- `command`: mapper가 명령을 발행하고 테스트 publisher가 구독한다.
- `heartbeat`: 테스트 publisher 보조 heartbeat이며 KubeEdge Device manifest에는 직접 연결하지 않는다.

## Broker

테스트 publisher는 실행한 서버의 로컬 mosquitto로 publish한다.

```text
tcp://127.0.0.1:1883
```
