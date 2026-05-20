---
title: 디바이스 MOC
tags:
  - wiki/moc
  - device
status: active
created: 2026-05-20
---

# 디바이스 MOC

## 핵심 노트

- [[디바이스 등록]]
- [[DeviceStatus 정책]]
- [[디바이스-서비스 연결 구조]]
- [[MQTT Topic 규칙]]

## 정책 요약

- KubeEdge `Device`는 현재 사전 등록 방식으로 운영한다.
- Jetson 디바이스는 `etri-dev0001-jetorn`에 할당한다.
- Raspberry Pi 디바이스는 `etri-dev0002-raspi5`에 할당한다.
- raw telemetry 값은 [[DeviceStatus 정책]]에 올리지 않는다.
- raw telemetry는 MQTT/InfluxDB data-plane으로 처리한다.
