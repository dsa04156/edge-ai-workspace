# DeviceStatus Policy

## 원칙

KubeEdge `DeviceStatus`는 고빈도 telemetry 저장/전송 경로가 아니다.
DeviceStatus는 control/status-plane의 저빈도 운영 snapshot으로 제한한다.

raw telemetry는 MQTT 기반 data-plane을 통해 InfluxDB에 저장한다.

```text
sensor/test publisher
  -> MQTT telemetry topic
  -> mqttvirtual mapper
  -> InfluxDB raw telemetry
  -> state-aggregator latest telemetry query
```

DeviceStatus는 다음 용도로만 사용한다.

- 운영 상태 요약
- 설정 반영 상태
- 장애 요약 상태
- command 적용 결과
- raw telemetry에서 계산된 상태 등급

## DeviceStatus에 허용하는 property

- `health`: `ok` / `degraded` / `offline` / `unknown`
- `severity`: `normal` / `warning` / `critical`
- `alarm_latched`: `true` / `false`
- `power`: `on` / `off`
- `mode`: `auto` / `manual` / `idle` / `maintenance`
- `sampling_interval`: command/desired 반영 확인용 저빈도 상태
- `config_version` 또는 `reported_config_version`
- `command_state`: `idle` / `pending` / `applied` / `failed`
- `last_error_code`
- `last_error_message`
- `temperature_status`: `normal` / `high` / `critical`
- `humidity_status`: `normal` / `high` / `low`
- `vibration_status`: `normal` / `warning` / `critical`

## DeviceStatus에 올리지 않는 property

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

`last_temperature`, `last_humidity`, `last_vibration` 같은 값은 30~60초 이상의 저빈도 snapshot일 때만 조건부 허용한다.
가능하면 raw 값 대신 `temperature_status`, `humidity_status`, `vibration_status`를 우선 사용한다.

## Mapper 보고 정책

`mqttvirtual` mapper는 MQTT payload를 수신하더라도 모든 property를 DeviceStatus로 report하지 않는다.
DeviceStatus allowlist에 포함된 property만 report 대상으로 둔다.

기본 allowlist:

```yaml
allowed_status_properties:
  - health
  - severity
  - alarm_latched
  - power
  - mode
  - sampling_interval
  - config_version
  - reported_config_version
  - command_state
  - last_error_code
  - last_error_message
  - temperature_status
  - humidity_status
  - vibration_status
```

raw telemetry property:

```yaml
raw_telemetry_properties:
  - temperature
  - humidity
  - vibration
  - rms
  - peak
  - waveform
  - raw_samples
```

## Throttling

DeviceStatus report는 changed-only, throttling, jitter를 적용한다.

기본값:

```bash
DEVICE_STATUS_FLUSH_SECONDS=30
DEVICE_STATUS_JITTER_SECONDS=10
DEVICE_STATUS_HEARTBEAT_SECONDS=120
```

정책:

- payload 수신마다 즉시 `ReportDeviceStatus`를 호출하지 않는다.
- latest status cache를 유지한다.
- 이전 보고값과 달라진 property만 pending report에 넣는다.
- 같은 값 반복 보고는 하지 않는다.
- heartbeat 목적의 같은 값 재보고는 120초 이상으로 제한한다.
- device별 flush 시점에 jitter를 둔다.

## ReportDeviceStates

`ReportDeviceStates`는 telemetry 수신마다 호출하지 않는다.
현재 데모 정책에서는 기본적으로 끈다.

```bash
DEVICE_STATES_REPORT_ENABLED=false
```

반드시 필요한 경우에만 60~120초 이상의 저빈도 heartbeat로 제한한다.
`state=online`은 참고값이며 live 판단의 단독 근거로 쓰지 않는다.

## Device Manifest 정책

- raw telemetry property는 `reportToCloud: false`
- 운영 상태 property만 `reportToCloud: true`
- Device `status.reportToCloud: false`
- Device `status.reportCycle: 120000`

예:

- env device
  - DeviceStatus: `health`, `sampling_interval`, 이후 `temperature_status`, `humidity_status`
  - InfluxDB: `temperature`, `humidity`
- vib device
  - DeviceStatus: `health`, `severity`, `alarm_latched`, `sampling_interval`, 이후 `vibration_status`
  - InfluxDB: `vibration`, 이후 `rms`, `peak`, raw vibration samples
- act device
  - DeviceStatus: `health`, `power`, `mode`, `sampling_interval`, 이후 `command_state`, `reported_config_version`
  - event DB: command event history, actuation latency, state transition history

## 현재 PoC 기준

현재 mapper 기반 PoC는 raw telemetry를 60초 주기로 InfluxDB에 적재한다.
실제 센서가 고빈도 데이터를 발행해도 DeviceStatus 주기를 올리지 않는다.
고빈도 원천 데이터는 MQTT/InfluxDB data-plane에서 처리하고, 대시보드 freshness는 현재 InfluxDB 적재/집계 주기에 맞춘다.
