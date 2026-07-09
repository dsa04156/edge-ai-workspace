# Dashboard Policy

## 원칙

대시보드는 control/status plane과 raw telemetry freshness를 분리해서 표시하되, telemetry-enabled device의 최종 availability는 InfluxDB latest telemetry freshness를 직접 반영한다.

- telemetry-enabled device의 `available/degraded/unavailable`은 node/mapper 선행 조건을 먼저 통과한 뒤, InfluxDB device-level latest telemetry sample freshness를 기준으로 판단한다.
- DeviceStatus는 고빈도 raw telemetry 경로가 아니라 control/status-plane의 저빈도 운영 snapshot이다. DeviceStatus freshness는 availability의 1차 기준이 아니라 보조 관찰 신호다.
- raw telemetry freshness는 `telemetry_status`와 sensor freshness KPI에도 별도 표시해 원인을 구분한다.
- `status.state=online`만으로 available 처리하지 않는다. node, mapper, InfluxDB freshness, DeviceStatus의 명시 offline/critical 신호를 함께 본다.
- MapperFramework 리팩토링 목표에서는 raw telemetry export engine을 추가하지 않는다. raw telemetry ingestion은 향후 EdgeX 기반 별도 plane이 담당한다.

## Freshness 설정

현재 기본값:

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=90
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

`TELEMETRY_FRESH_SECONDS`는 InfluxDB latest telemetry sample freshness 기준이며, telemetry-enabled device의 dashboard availability 판단에 직접 사용한다.
`DEVICE_STATUS_FRESH_SECONDS`는 DeviceStatus/control summary heartbeat freshness 기준이며, status-plane snapshot 관찰용 보조 신호다.

## Timestamp 처리

`twins[].reported.metadata.timestamp`는 문자열일 수 있다.
Unix epoch milliseconds와 seconds를 모두 처리한다.

- `1777508184621`처럼 10자리보다 크면 milliseconds
- 10자리 수준이면 seconds
- ISO datetime 문자열도 UTC 기준으로 파싱

`statusLastSeen`, `controlLastSeen`, `mapperLastSeen`은 reported value 또는 reported metadata timestamp에서 읽는다.
parse 실패 시 해당 field는 freshness 판단에서 제외하고 reason에 parse error를 남기는 방향으로 확장한다.

InfluxDB latest sample freshness는 row의 `_time`을 기준으로 계산한다. InfluxDB UI의 `_start`, `_stop`은 Flux query window이므로 device freshness 기준으로 쓰지 않는다.

## 판단 필드

Availability 판단 필드:

- `Device.spec.nodeName`: 어느 노드에 할당됐는지 확인
- Kubernetes Node Ready condition: assigned node가 Ready인지 확인
- Prometheus/node state의 `node_health`: dashboard 관측상 node unavailable/degraded 여부 보조 확인
- `Device.spec.protocol.protocolName`: `mqttvirtual` mapper 확인 여부 결정
- `mqttvirtual` mapper Pod: assigned node에서 Running + Ready인지 확인
- `DeviceStatus.status`: `status`, `phase`, `state`, `connection`, `connected`, `health`, `online`
- `DeviceStatus.status.twins`: `health`, `online`, `severity`, `statusLastSeen`, `controlLastSeen`, `mapperLastSeen`, `last_error_code`, `last_error_message`
- `DeviceStatus.status.lastOnlineTime` 및 reported timestamp: status snapshot 표시/보조 freshness
- InfluxDB `device_telemetry`: telemetry-enabled device의 latest sample `_time`

Telemetry freshness 판단 필드:

- `Device.spec.properties[].pushMethod`: raw telemetry 대상 여부
- InfluxDB `device_telemetry`: raw sensor latest timestamp
  - env/vib/temp/light/magnetic/acceleration: raw telemetry property
  - act/rpi-act: 기존 호환 liveness property

KPI 관련 주의:

- `telemetry_device_count`: raw telemetry 대상(device.spec.properties.pushMethod 기반) device 수
- `device_telemetry_ratio`: telemetry 설정 비율 = telemetry_device_count / registered_device_count
- `telemetry_freshness_ratio`: 실제 최신 telemetry 비율 = fresh_telemetry_device_count / telemetry_device_count
- `sensor_data_freshness_ratio`: 실제 센서 데이터 freshness 비율 = fresh_sensor_data_device_count / sensor_data_device_count
- `device_status_freshness_ratio`: 최신 DeviceStatus/control heartbeat 비율 = fresh_device_status_count / registered_device_count
- `operator_focus_count`: degraded/unavailable device 수 + non-healthy node 수

## Availability 판단 순서

State Aggregator는 다음 우선순위로 device 상태를 계산한다.

1. `spec.nodeName`이 없으면 `unavailable`.
   - reason: `device is not assigned to a node`
2. assigned node가 Kubernetes Ready가 아니거나 dashboard node state가 unavailable이면 `unavailable`.
   - reason: `assigned node is unavailable`
3. KubeEdge Device/DeviceStatus가 offline 계열 값을 보고하면 `unavailable`.
   - 대상 key: `status`, `phase`, `state`, `connection`, `connected`, `health`
   - offline 값: `offline`, `disconnected`, `failed`, `unavailable`, `false`
   - reason: `device status is <value>`
4. DeviceStatus/twin summary에서 `health=offline`이면 `unavailable`.
   - reason: `DeviceStatus health is offline`
5. DeviceStatus/twin summary에서 `online=false`이면 `unavailable`.
   - reason: `DeviceStatus online is false`
6. `protocolName=mqttvirtual`인데 해당 node의 mapper Pod가 없거나 Running/Ready가 아니면 `unavailable`.
   - reason: `assigned mapper is not running`
7. telemetry-enabled device인데 InfluxDB latest telemetry sample이 없으면 `degraded`.
   - reason: `latest telemetry sample is missing`
8. telemetry-enabled device인데 InfluxDB latest telemetry sample이 `TELEMETRY_FRESH_SECONDS`보다 오래됐으면 `degraded`.
   - reason: `latest telemetry sample is stale`
9. `statusLastSeen`, `controlLastSeen`, `mapperLastSeen` 중 최신 heartbeat가 `DEVICE_STATUS_FRESH_SECONDS`보다 오래됐으면 `degraded`.
   - reason: `status heartbeat is stale`
10. assigned node가 degraded이면 `degraded`.
    - reason: `assigned node is degraded`
11. DeviceStatus `severity=critical` 또는 `health=error/failed/degraded/critical`이면 `degraded`.
12. 위 조건이 모두 정상이면 `available`.
    - telemetry 대상 device reason: `latest telemetry sample is fresh`
    - non-telemetry device reason: `control/status path is available` 또는 `registered control/status path is available`

## Telemetry status 분리

Raw telemetry 상태는 telemetry-enabled device availability 판단의 직접 입력이며, 동시에 원인 식별을 위한 `telemetry_status`와 freshness KPI로도 표시한다.

- telemetry 미설정: `disabled`
- telemetry 설정 + InfluxDB latest timestamp fresh: `fresh`
- telemetry 설정 + InfluxDB latest timestamp 없음/stale: `stale`

단, `telemetry_freshness_ratio=0.0` 같은 집계 KPI 자체는 개별 device 상태의 원인이 아니라 결과 요약으로만 해석한다.

## Explain Panel 표시 기준

Explain Panel은 운영자가 즉시 판단할 핵심값만 표시한다. Device 선택 시 기본 표시값은 `status`, `reason`, `node`, `sensor`, `last seen`, `mapper`, `service`이다.

Device availability 문제는 node/mapper 선행 조건을 먼저 확인하고, telemetry-enabled device는 InfluxDB latest sample freshness를 확인한다.
DeviceStatus/control heartbeat는 운영 snapshot 최신성 보조 신호로 표시한다.

## API 응답 필드

`/state/devices`는 최소한 다음 정보를 포함한다.

`/state/devices/{device_id}/telemetry`는 선택한 device의 최근 InfluxDB telemetry samples를 시간순으로 반환하며 dashboard detail graph에서 사용한다. 기본 조회 범위는 `-30m`, 기본 limit은 `300`이다.

`/state/virtual-resources`는 자원증강형 가상디바이스를 Resource Profile 단위로 반환한다.
이 API는 가상 센서 생성 경로가 아니라 AI HAT/GPU/cache 같은 보강 실행 자원 상태 조회 경로다.
실행 인스턴스가 0개여도 registry에 있는 profile은 숨기지 않으며, 상태는 `configured_not_running`으로 표시한다.

`/state/dashboard`는 service resource observation 실패 시 dashboard 전체를 500으로 내리지 않는다.
이 경우 `resource_profiles.observation_error`에 원인을 남기고 service resource KPI만 0으로 degrade한다.
`/state/operator-assistant`와 `/state/operator-chat`도 같은 degraded dashboard snapshot을 사용한다.
resource observation 실패가 먼저 발생하면 chat은 Qwen 호출 전에 read-only degraded observation 응답을 반환한다.

```json
{
  "name": "env-arduino-temperature-01",
  "nodeName": "etri-dev0001-jetorn",
  "kubeedge_state": "online",
  "device_status_fresh": false,
  "device_status_last_reported_at": "2026-05-26T07:43:51Z",
  "telemetry_fresh": false,
  "telemetry_status": "stale",
  "telemetry_last_seen_at": "2026-05-26T07:20:47Z",
  "telemetry_age_seconds": 1384.5,
  "mapper_running": true,
  "node_ready": true,
  "health": "ok",
  "severity": "normal",
  "overall_status": "degraded",
  "reason": "latest telemetry sample is stale"
}
```

## 해석 규칙

- `DeviceStatus`에 `power:on` 같은 값이 있어도 timestamp가 오래됐으면 현재값이 아니라 마지막 snapshot이다.
- dashboard의 availability는 Device CR 존재 여부나 `state=online` 단독 판단이 아니라 node/mapper 선행 조건, InfluxDB latest telemetry freshness, DeviceStatus summary의 offline/critical 신호를 함께 본 결과다.
- InfluxDB row의 `device_id`가 Device 이름과 맞지 않으면 dashboard가 해당 telemetry를 매칭하지 못하므로 `telemetry_status=stale`, freshness KPI 저하, telemetry-enabled device의 `degraded`로 표시된다.
- 현재 Jetson Arduino 기반 device의 raw sensor값 temperature/raw, light/value, magnetic/value, acceleration/x,y,z row는 InfluxDB latest sample freshness와 sensor freshness KPI에 반영한다.
