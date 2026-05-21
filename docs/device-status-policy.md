# DeviceStatus Policy

## 원칙

KubeEdge `DeviceStatus`는 고빈도 telemetry 저장/전송 경로가 아니다.
DeviceStatus는 control/status-plane의 저빈도 운영 snapshot으로 제한한다.

raw telemetry는 MQTT 기반 data-plane에서 처리하며, 목표 구조에서는 `raw-stream-bridge`가 Redis Streams에 append하고 InfluxDB에 batch write한다.

```text
sensor/test publisher
  -> MQTT telemetry topic
  -> raw-stream-bridge
  -> Redis Streams telemetry:raw / Redis latest cache
  -> InfluxDB raw telemetry history
  -> state-aggregator latest telemetry query
```

`mqttvirtual` mapper는 같은 MQTT 입력을 볼 수 있지만 raw telemetry 영구 저장 책임을 갖지 않는다. mapper는 KubeEdge DMI adapter, command/desired 처리, latest operational state, DeviceStatus/Twin reported에 집중한다.

DeviceStatus는 다음 용도로만 사용한다.

- 운영 상태 요약
- 설정 반영 상태
- 장애 요약 상태
- command 적용 결과
- raw telemetry에서 계산된 상태 등급

state-aggregator는 DeviceStatus를 저빈도 운영 snapshot으로 보고, dashboard에서는 `device_status_fresh`와 `device_status_freshness_ratio`로 최신성을 따로 계산한다.
실제 센서 데이터 최신성은 `telemetry_fresh`, `fresh_sensor_data_device_count`, `sensor_data_freshness_ratio`로 분리해서 본다. `telemetry_freshness_ratio`는 기존 호환 지표로 유지한다. telemetry-enabled device의 healthy 판단 1차 기준은 InfluxDB device-level latest sample freshness이며, DeviceStatus freshness는 필수 조건이 아니다.

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
  - InfluxDB liveness: 현재 구현 기준 `ts` property
  - 향후 확장 후보: command event history, actuation latency, state transition history

## 현재 PoC 기준

현재 Jetson sensor-collector 기반 PoC는 Arduino 센서값을 MQTT로 발행한다. 현 구현에는 mapper가 `reportCycle`마다 latest snapshot을 InfluxDB에 쓰는 전환기 경로가 남아 있지만, 목표 구조는 raw-stream-bridge가 MQTT raw stream을 Redis Streams와 InfluxDB에 event-driven/batch 방식으로 저장하는 것이다.
실제 센서가 고빈도 데이터를 발행해도 DeviceStatus 주기를 올리지 않는다.
고빈도 원천 데이터는 MQTT/Redis Streams/InfluxDB data-plane에서 처리하고, 대시보드 freshness는 InfluxDB latest timestamp에 맞춘다.

즉, dashboard의 `telemetry_device_count`는 telemetry-enabled device 수이고 `device_telemetry_ratio`는 telemetry-enabled device / 전체 registered device 비율이다. `fresh_sensor_data_device_count`와 `sensor_data_freshness_ratio`는 InfluxDB device-level latest sample freshness를 현재 메인 운영 KPI로 나타낸다. `fresh_telemetry_device_count`와 `telemetry_freshness_ratio`는 같은 data-plane freshness의 호환 지표다. InfluxDB UI의 `_start`와 `_stop`은 Flux query 조회 window이며 device start/stop 이벤트가 아니다. 실제 telemetry sample timestamp는 `_time`이다. Dashboard의 `telemetry_fresh`는 device-level latest sample 기준이며, property별 latest freshness를 보장하지 않는다. `ts`는 publisher payload와 Device manifest의 DB push property로 freshness 기준에 사용한다.
