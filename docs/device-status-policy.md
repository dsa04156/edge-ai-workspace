# DeviceStatus Policy

## 원칙

KubeEdge `DeviceStatus`는 고빈도 telemetry 저장/전송 경로가 아니다.
DeviceStatus는 control/status-plane의 저빈도 운영 snapshot으로 제한한다.

raw telemetry는 향후 EdgeX 기반 별도 telemetry ingestion plane에서 처리한다.
수정된 MapperFramework 리팩토링 목표에서는 `mqttvirtual` mapper를 raw telemetry export engine으로 확장하지 않는다.

```text
control/status plane
  KubeEdge Device / DeviceModel
  -> mqttvirtual mapper / MapperFramework DMI adapter
  -> DeviceStatus summary
  -> state-aggregator / dashboard

raw telemetry ingestion plane (future)
  Sensor / collector
  -> EdgeX Device Service / EdgeX MessageBus
  -> telemetry store / analytics consumers
```

`mqttvirtual` mapper는 KubeEdge DMI adapter, command/desired 처리, DeviceStatus/Twin reported를 담당한다. raw telemetry 영구 저장은 MapperFramework 주 경로에서 제외한다.
기존 `telemetry.Sample` / `telemetry.Sink` package는 production raw telemetry path가 아니라 debug/internal compatibility path로만 취급한다.
WARNING: MapperFramework에 `MQTTTelemetrySink`, `CollectorTelemetrySink`, `InfluxDBSink`, `KafkaSink`를 추가하지 않는다.

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
- `online` / `offline`: 연결 상태 summary
- `control_response` 또는 `last_control_response`: 제어 응답 summary
- `last_error_code`
- `last_error_message`
- `temperature_status`: `normal` / `high` / `critical`
- `humidity_status`: `normal` / `high` / `low`
- `vibration_status`: `normal` / `warning` / `critical`
- `mapperLastSeen`: mapper가 status/control snapshot을 마지막으로 처리한 시각
- `controlLastSeen`: command/control path의 마지막 처리 시각
- `statusLastSeen`: DeviceStatus summary 마지막 보고 시각
- `statusSource`: status summary 출처

Deprecated property:

- `lastSeen`, `last_seen`: `mapperLastSeen`, `controlLastSeen`, `statusLastSeen` 중 의미에 맞는 필드로 대체한다.
- `telemetryFresh`, `telemetry_fresh`: DeviceStatus allowlist에서 제외한다. raw telemetry freshness는 EdgeX ingestion plane 또는 dashboard data-plane KPI에서 계산한다.
- `source`: `statusSource`로 대체한다.

## DeviceStatus에 올리지 않는 property

- `temperature` raw stream
- `humidity` raw stream
- `vibration` raw stream
- `acceleration_x`, `acceleration_y`, `acceleration_z`
- `current`
- `voltage`
- `x`, `y`, `z`
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
  - command_state
  - online
  - offline
  - control_response
  - last_control_response
  - alarm_latched
  - power
  - mode
  - sampling_interval
  - config_version
  - reported_config_version
  - last_error_code
  - last_error_message
  - temperature_status
  - humidity_status
  - vibration_status
  - mapperLastSeen
  - controlLastSeen
  - statusLastSeen
  - statusSource
```

deprecated_status_properties:

```yaml
deprecated_status_properties:
  - lastSeen
  - last_seen
  - telemetryFresh
  - telemetry_fresh
  - source
```

raw telemetry property:

```yaml
raw_telemetry_properties:
  - temperature
  - humidity
  - vibration
  - acceleration_x
  - acceleration_y
  - acceleration_z
  - current
  - voltage
  - x
  - y
  - z
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
  - InfluxDB liveness: 현재 구현 기준 `health` property
  - 향후 확장 후보: command event history, actuation latency, state transition history

## 현재 PoC 기준

현재 Jetson sensor-collector 기반 PoC는 Arduino 센서값을 MQTT로 발행한다. 수정된 목표에서는 이 raw sensor property 저장 경로를 MapperFramework 확장 목표에서 제외하고, 향후 EdgeX telemetry ingestion plane으로 분리한다.
실제 센서가 고빈도 데이터를 발행해도 DeviceStatus 주기를 올리지 않는다.
원천 데이터는 EdgeX 기반 telemetry plane에서 처리하고, MapperFramework는 control/status summary만 KubeEdge DeviceStatus로 보고한다.

EdgeX Device Profile과 KubeEdge DeviceModel 간 매핑표는 `docs/kubeedge-edgex-model-mapping.md`에 둔다.

즉, dashboard의 `telemetry_device_count`와 `device_telemetry_ratio`는 기존 호환 지표로 남아 있을 수 있지만, MapperFramework 리팩토링의 새 목표는 raw telemetry 저장/전송을 이 경로에 추가하지 않는 것이다. EdgeX ingestion plane이 붙기 전까지 raw telemetry freshness KPI는 전환 대상 지표로 취급한다. DeviceStatus freshness는 별도 status-plane snapshot 최신성으로 유지한다.
