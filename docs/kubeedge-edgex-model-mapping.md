# KubeEdge DeviceModel - EdgeX Device Profile 매핑표

## 목적

이 문서는 MapperFramework 리팩토링 이후의 모델 경계를 정리한다.
KubeEdge `DeviceModel`은 control/status plane의 Device/DeviceStatus 계약을 표현하고, EdgeX `Device Profile`은 향후 별도 raw telemetry ingestion plane의 resource/readings 계약을 표현한다.

중요 정책:

- MapperFramework는 raw telemetry export engine으로 확장하지 않는다.
- EdgeX가 `temperature`, `humidity`, `vibration`, `acceleration_x/y/z`, `current`, `voltage`, `waveform` 같은 raw telemetry ingestion을 담당한다.
- KubeEdge DeviceStatus에는 health/severity/command_state/online/offline/control_response 같은 저빈도 control/status summary만 올린다.
- `telemetry.Sample` / `telemetry.Sink`는 production raw telemetry path가 아니라 debug/internal compatibility path다.
- WARNING: MapperFramework에 `MQTTTelemetrySink`, `CollectorTelemetrySink`, `InfluxDBSink`, `KafkaSink`를 추가하지 않는다.

## 매핑 원칙

| 구분 | KubeEdge DeviceModel property | EdgeX Device Profile resource | 방향 |
|---|---|---|---|
| control/status summary | 유지 | 필요 시 derived/status resource로 별도 정의 | KubeEdge 중심 |
| raw sensor reading | DeviceStatus 주 경로 제외 | deviceResource로 정의 | EdgeX 중심 |
| command/desired | KubeEdge desired/command path | EdgeX command resource와 후속 연동 검토 | 경계 명시 필요 |
| freshness/source metadata | `mapperLastSeen`, `controlLastSeen`, `statusLastSeen`, `statusSource` | EdgeX event origin/reading timestamp/source metadata | plane별 별도 관리 |

Deprecated KubeEdge DeviceStatus field:

```yaml
deprecated_status_properties:
  - lastSeen
  - last_seen
  - telemetryFresh
  - telemetry_fresh
  - source
```

대체 필드:

```yaml
replacement_status_properties:
  - mapperLastSeen
  - controlLastSeen
  - statusLastSeen
  - statusSource
```

## KubeEdge DeviceModel property ↔ EdgeX Device Profile resource 매핑

| 디바이스군 | KubeEdge DeviceModel property | KubeEdge 처리 | EdgeX Device Profile resource | EdgeX 처리 | 비고/TODO |
|---|---|---|---|---|---|
| env / rpi-env | `health` | DeviceStatus summary 허용 | `Health` 또는 derived `DeviceHealth` | 선택적 derived/status | raw 값 아님 |
| env / rpi-env | `sampling_interval` | command/desired 반영 상태 허용 | `SamplingInterval` | command/config resource 후보 | 제어 경로 연동 방식 TODO |
| env / rpi-env | `temperature_status` | DeviceStatus summary 허용 | `TemperatureStatus` | derived/status 후보 | raw temperature에서 계산 가능 |
| env / rpi-env | `humidity_status` | DeviceStatus summary 허용 | `HumidityStatus` | derived/status 후보 | raw humidity에서 계산 가능 |
| env / rpi-env | `temperature` | DeviceStatus 제외 | `Temperature` | raw reading | EdgeX ingestion plane 담당 |
| env / rpi-env | `humidity` | DeviceStatus 제외 | `Humidity` | raw reading | EdgeX ingestion plane 담당 |
| vib / rpi-vib | `health` | DeviceStatus summary 허용 | `Health` 또는 derived `DeviceHealth` | 선택적 derived/status | raw 값 아님 |
| vib / rpi-vib | `severity` | DeviceStatus summary 허용 | `VibrationSeverity` | derived/status 후보 | alarm 정책과 연결 |
| vib / rpi-vib | `alarm_latched` | DeviceStatus summary 허용 | `AlarmLatched` | derived/status 후보 | debounce/hysteresis 결과 |
| vib / rpi-vib | `sampling_interval` | command/desired 반영 상태 허용 | `SamplingInterval` | command/config resource 후보 | 제어 경로 연동 방식 TODO |
| vib / rpi-vib | `vibration_status` | DeviceStatus summary 허용 | `VibrationStatus` | derived/status 후보 | raw vibration에서 계산 가능 |
| vib / rpi-vib | `vibration` | DeviceStatus 제외 | `Vibration` | raw reading | EdgeX ingestion plane 담당 |
| vib / rpi-vib | `acceleration_x` | DeviceStatus 제외 | `AccelerationX` | raw reading | EdgeX ingestion plane 담당 |
| vib / rpi-vib | `acceleration_y` | DeviceStatus 제외 | `AccelerationY` | raw reading | EdgeX ingestion plane 담당 |
| vib / rpi-vib | `acceleration_z` | DeviceStatus 제외 | `AccelerationZ` | raw reading | EdgeX ingestion plane 담당 |
| vib / rpi-vib | `waveform` | DeviceStatus 제외 | `Waveform` | raw reading/binary or object | payload format TODO |
| act / rpi-act | `health` | DeviceStatus summary 및 현행 liveness row | `Health` 또는 derived `DeviceHealth` | 선택적 derived/status | 현재 PoC actuator liveness는 `health` 유지 |
| act / rpi-act | `power` | DeviceStatus summary 허용 | `Power` | command/status resource 후보 | 통신 생존성 자체가 아님 |
| act / rpi-act | `mode` | DeviceStatus summary 허용 | `Mode` | command/status resource 후보 | enum 정리 TODO |
| act / rpi-act | `command_state` | DeviceStatus summary 허용 | `CommandState` | derived/status 후보 | command result 요약 |
| act / rpi-act | `control_response` | DeviceStatus summary 허용 | `ControlResponse` | event/status 후보 | 제어 응답 요약 |
| act / rpi-act | `current` | DeviceStatus 제외 | `Current` | raw/electrical reading | EdgeX ingestion plane 담당 |
| act / rpi-act | `voltage` | DeviceStatus 제외 | `Voltage` | raw/electrical reading | EdgeX ingestion plane 담당 |

## DeviceStatus summary allowlist

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

## raw telemetry 제외 목록

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

## TODO

- EdgeX Device Profile YAML 작성 시 각 resource의 type, unit, min/max, read/write 여부를 확정한다.
- KubeEdge DeviceModel property와 EdgeX Device Profile resource의 enum 값을 맞춘다.
- EdgeX event/reading timestamp와 KubeEdge `mapperLastSeen`/`statusLastSeen`의 dashboard 표시 경계를 정한다.
- actuator command를 KubeEdge desired path와 EdgeX command resource 중 어디에서 시작할지 결정한다.
- EdgeX ingestion plane 구축 후 state-aggregator가 raw freshness KPI를 어느 API에서 읽을지 정한다.
