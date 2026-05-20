---
title: 네트워크 Troubleshooting
tags:
  - ops/troubleshooting
  - network
status: active
source:
  - docs/ops/troubleshooting-network.md
created: 2026-05-20
---

# 네트워크 Troubleshooting

네트워크 문제는 MQTT, mapper, InfluxDB, dashboard API 경로를 분리해서 확인한다.

## 우선 확인

- publisher가 올바른 노드의 로컬 mosquitto에 publish하는가
- [[MQTT Topic 규칙]]의 device name이 Device 이름과 일치하는가
- mapper Pod가 Running인가
- state-aggregator가 latest telemetry를 조회하는가
