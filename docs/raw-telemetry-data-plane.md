# Raw Telemetry Data Plane Architecture

## 목적

이 문서는 현재 KubeEdge 기반 mixed-device PoC에서 raw telemetry와 KubeEdge MapperFramework 책임을 분리하는 목표를 정의한다.
수정된 목표는 MapperFramework를 raw telemetry export engine으로 확장하지 않는 것이다.
향후 raw telemetry ingestion은 EdgeX 기반 별도 telemetry ingestion plane이 담당한다.

## 변경된 공식 구조

```text
control/status plane
  KubeEdge Device / DeviceModel
    -> mqttvirtual mapper / MapperFramework DMI adapter
    -> DeviceStatus summary: health, severity, command_state, online/offline, control response
    -> state-aggregator / dashboard

raw telemetry ingestion plane (future)
  Sensor / Arduino / collector
    -> EdgeX Device Service / EdgeX MessageBus
    -> EdgeX Core Data / app service / persistence pipeline
    -> telemetry store and analytics consumers
```

현재 문서/코드 정리 기준에서 `temperature`, `humidity`, `vibration`, `acceleration_x/y/z`, `current`, `voltage`, `waveform` 같은 raw telemetry는 MapperFramework 주 경로에서 제외한다.
기존 `telemetry.Sample`/`telemetry.Sink` 형태는 production raw telemetry path가 아니라 debug/internal compatibility path로만 남긴다.

## MapperFramework가 유지할 책임

| 범위 | 유지 책임 |
|---|---|
| KubeEdge 연동 | `Device`, `DeviceModel`, `DeviceStatus`와 DMI adapter 연동 |
| control/status summary | `health`, `severity`, `command_state`, `online/offline`, `control_response` 등 저빈도 운영 요약 처리 |
| command/desired | desired 값 수신, MQTT command publish, command 적용 결과 summary 보고 |
| DeviceStatus 보호 | allowlist 기반으로 raw telemetry field가 DeviceStatus summary에 들어가지 못하게 차단 |
| dashboard 입력 | state-aggregator가 해석할 수 있는 control/status snapshot 제공 |

## 제거/축소할 telemetry 관련 코드

| 대상 | 결정 |
|---|---|
| MapperFramework raw telemetry export engine | 확장하지 않음 |
| `temperature`, `humidity`, `vibration`, `acceleration_x/y/z`, `current`, `voltage`, `waveform` 주 경로 처리 | MapperFramework 주 경로에서 제외 |
| `telemetry.Sample` / `telemetry.Sink` | debug/internal compatibility path로만 유지하거나 제거 검토 |
| `MQTTTelemetrySink` | 추가하지 않음 |
| `CollectorTelemetrySink` | 추가하지 않음 |
| `InfluxDBSink` | 추가하지 않음 |
| `KafkaSink` | 추가하지 않음 |
| raw telemetry -> DeviceStatus 변환 | 금지 |

WARNING: MapperFramework에 `MQTTTelemetrySink`, `CollectorTelemetrySink`, `InfluxDBSink`, `KafkaSink` 또는 유사 production raw telemetry sink를 추가하지 않는다. raw telemetry ingestion은 EdgeX plane에서 다룬다.

## DeviceStatus summary field 목록

허용 summary field는 운영 상태와 제어 응답을 나타내는 저빈도 값으로 제한한다.

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

Deprecated summary field:

```yaml
deprecated_status_properties:
  - lastSeen
  - last_seen
  - telemetryFresh
  - telemetry_fresh
  - source
```

`temperature_status`, `humidity_status`, `vibration_status`는 raw 값이 아니라 상태 등급이다.
가능하면 raw 값 대신 status 등급을 DeviceStatus로 올린다.

## raw telemetry 제외 field 목록

다음 field는 DeviceStatus summary와 MapperFramework control/status 주 경로에서 제외한다.

```yaml
excluded_raw_telemetry_fields:
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
  - waveform
  - raw_samples
  - rms
  - peak
  - image
  - frame
  - value
  - raw
```

## state-aggregator / dashboard 정책

- `/state/dashboard` payload는 availability와 telemetry freshness를 분리해서 해석한다.
- Availability는 node 상태, mapper Pod Running/Ready, DeviceStatus summary, `statusLastSeen`/`controlLastSeen`/`mapperLastSeen` freshness를 종합해 `available/degraded/unavailable`로 판단한다.
- DeviceStatus freshness는 status-plane snapshot/heartbeat 최신성이다.
- raw telemetry ingestion freshness는 `telemetry_status`와 sensor freshness KPI로 별도 표시한다.
- InfluxDB latest timestamp, `telemetryFresh`, `telemetry_fresh`, raw sensor sample 유무만으로 device를 unavailable 처리하지 않는다.
- `status.state=online` 하나만으로 available을 판단하지 않는다.

## EdgeX TODO

- EdgeX Device Profile과 KubeEdge DeviceModel 간 매핑표는 `docs/kubeedge-edgex-model-mapping.md`에 둔다.
- TODO: EdgeX profile의 device resource 이름과 KubeEdge DeviceModel property 이름의 1:1/파생 관계를 정리한다.
- TODO: EdgeX event/reading field와 dashboard 상태 필드의 연결 범위를 정의한다.
- TODO: EdgeX ingestion plane과 KubeEdge DeviceStatus summary plane의 장애/freshness KPI 경계를 정의한다.
