---
title: DeviceStatus 정책
aliases:
  - DeviceStatus Policy
tags:
  - device/status
  - kubeedge
  - policy
status: active
source:
  - docs/device-status-policy.md
created: 2026-05-20
---

# DeviceStatus 정책

KubeEdge `DeviceStatus`는 고빈도 telemetry 저장/전송 경로가 아니다. DeviceStatus는 control/status-plane의 저빈도 운영 snapshot으로 제한한다.

## 원칙

- raw telemetry는 MQTT 기반 data-plane을 통해 InfluxDB에 저장한다.
- DeviceStatus는 운영 상태 요약, 설정 반영 상태, 장애 요약 상태, command 적용 결과, raw telemetry에서 계산된 상태 등급만 담는다.
- `status.state=online`은 참고값이며 live 판단의 단독 근거로 쓰지 않는다.

## 허용 property

- `health`
- `severity`
- `alarm_latched`
- `power`
- `mode`
- `sampling_interval`
- `config_version`
- `reported_config_version`
- `command_state`
- `last_error_code`
- `last_error_message`
- `temperature_status`
- `humidity_status`
- `vibration_status`

## 올리지 않는 property

- `temperature` raw stream
- `humidity` raw stream
- `vibration` raw stream
- `rms`
- `peak`
- `raw_samples`
- `waveform`
- image / frame
- every-event log
- inference result stream


> [!note]
> 현재 대시보드 메인 freshness KPI는 Jetson Arduino 센서 MQTT 데이터가 InfluxDB에 최근 적재됐는지를 보는 `sensor_data_freshness_ratio`이다. DeviceStatus freshness는 control/status-plane 보조 snapshot으로만 해석한다.
