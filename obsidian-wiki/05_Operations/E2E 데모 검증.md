---
title: E2E 데모 검증
aliases:
  - E2E Demo Verification
tags:
  - ops/verification
  - demo
status: active
source:
  - docs/ops/e2e-demo-verification.md
created: 2026-05-20
---

# E2E 데모 검증

```text
test publisher
-> local mosquitto
-> mqttvirtual mapper
-> InfluxDB
-> state-aggregator
-> dashboard
```

## 판단 기준

- [[MQTT Topic 규칙]]이 맞는가
- publisher가 디바이스 할당 노드에서 실행되는가
- [[대시보드 정책]]에 따라 telemetry freshness가 fresh로 계산되는가
- DeviceStatus snapshot은 raw telemetry와 분리되어 표시되는가
