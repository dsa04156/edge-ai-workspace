# Dashboard Policy

## 원칙

대시보드는 device availability와 raw telemetry freshness를 분리해서 표시한다.

- `available/degraded/unavailable`은 control/status plane 기준이다.
- InfluxDB latest timestamp, `telemetryFresh`, `telemetry_fresh`, raw sensor sample 유무는 availability 판단에 쓰지 않는다.
- raw telemetry freshness는 `telemetry_status`와 sensor freshness KPI로 별도 표시한다.
- `status.state=online`만으로 available 처리하지 않는다. node, mapper, DeviceStatus summary, status heartbeat freshness를 함께 본다.
- MapperFramework 리팩토링 목표에서는 raw telemetry export engine을 추가하지 않는다. raw telemetry ingestion은 향후 EdgeX 기반 별도 plane이 담당한다.

## Freshness 설정

현재 기본값:

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=20
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

`DEVICE_STATUS_FRESH_SECONDS`는 DeviceStatus/control summary heartbeat freshness 기준이다.
`TELEMETRY_FRESH_SECONDS`는 raw sensor data freshness KPI 기준이며 availability 판단에는 사용하지 않는다.

## Timestamp 처리

`twins[].reported.metadata.timestamp`는 문자열일 수 있다.
Unix epoch milliseconds와 seconds를 모두 처리한다.

- `1777508184621`처럼 10자리보다 크면 milliseconds
- 10자리 수준이면 seconds
- ISO datetime 문자열도 UTC 기준으로 파싱

`statusLastSeen`, `controlLastSeen`, `mapperLastSeen`은 reported value 또는 reported metadata timestamp에서 읽는다.
parse 실패 시 해당 field는 freshness 판단에서 제외하고 reason에 parse error를 남기는 방향으로 확장한다.

## 판단 필드

Availability 판단 필드:

- `Device.spec.nodeName`: 어느 노드에 할당됐는지 확인
- Kubernetes Node Ready condition: assigned node가 Ready인지 확인
- Prometheus/node state의 `node_health`: dashboard 관측상 node unavailable/degraded 여부 보조 확인
- `Device.spec.protocol.protocolName`: `mqttvirtual` mapper 확인 여부 결정
- `mqttvirtual` mapper Pod: assigned node에서 Running + Ready인지 확인
- `DeviceStatus.status`: `status`, `phase`, `state`, `connection`, `connected`, `health`, `online`
- `DeviceStatus.status.twins`: `health`, `online`, `severity`, `statusLastSeen`, `controlLastSeen`, `mapperLastSeen`
- `DeviceStatus.status.lastOnlineTime` 및 reported timestamp: status snapshot 표시/보조 freshness

Telemetry freshness 판단 필드:

- `Device.spec.properties[].pushMethod`: raw telemetry 대상 여부
- InfluxDB `device_telemetry`: raw sensor latest timestamp
  - env/vib/temp: raw telemetry property
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
3. `protocolName=mqttvirtual`인데 해당 node의 mapper Pod가 없거나 Running/Ready가 아니면 `unavailable`.
   - reason: `assigned mapper is not running`
4. KubeEdge Device/DeviceStatus가 offline 계열 값을 보고하면 `unavailable`.
   - 대상 key: `status`, `phase`, `state`, `connection`, `connected`, `health`
   - offline 값: `offline`, `disconnected`, `failed`, `unavailable`, `false`
   - reason: `device status is <value>`
5. DeviceStatus/twin summary에서 `health=offline`이면 `unavailable`.
   - reason: `DeviceStatus health is offline`
6. DeviceStatus/twin summary에서 `online=false`이면 `unavailable`.
   - reason: `DeviceStatus online is false`
7. `statusLastSeen`, `controlLastSeen`, `mapperLastSeen` 중 최신 heartbeat가 `DEVICE_STATUS_FRESH_SECONDS`보다 오래됐으면 `degraded`.
   - reason: `status heartbeat is stale`
8. assigned node가 degraded이면 `degraded`.
   - reason: `assigned node is degraded`
9. DeviceStatus `severity=critical` 또는 `health=error/failed/degraded/critical`이면 `degraded`.
10. 위 조건이 모두 정상이면 `available`.
    - telemetry 대상이면 reason에 sensor data freshness가 별도임을 명시한다.

## Telemetry status 분리

Raw telemetry 상태는 availability와 별도로 `telemetry_status`로 해석한다.

- telemetry 미설정: `disabled`
- telemetry 설정 + InfluxDB latest timestamp fresh: `fresh`
- telemetry 설정 + InfluxDB latest timestamp 없음/stale: `stale`

다음 값만으로는 device를 unavailable/degraded로 만들지 않는다.

- InfluxDB latest timestamp 없음
- `telemetry_fresh=false`
- raw sensor sample 없음
- `telemetry_freshness_ratio=0.0`

## Explain Panel 표시 기준

Explain Panel은 운영자가 즉시 판단할 핵심값만 표시한다. Device 선택 시 기본 표시값은 `status`, `reason`, `node`, `sensor`, `last seen`, `mapper`, `service`이다.

Device availability 문제는 node/mapper/DeviceStatus/control heartbeat 순서로 설명한다.
Sensor data freshness 문제는 availability와 분리해서 EdgeX/collector/MQTT/DB 적재 경로 점검 대상으로 설명한다.

## API 응답 필드

`/state/devices`는 최소한 다음 정보를 포함한다.

```json
{
  "name": "env-device-01",
  "nodeName": "etri-dev0001-jetorn",
  "kubeedge_state": "online",
  "device_status_fresh": true,
  "device_status_last_reported_at": "2026-04-24T07:43:51Z",
  "telemetry_fresh": false,
  "telemetry_status": "stale",
  "telemetry_last_seen_at": null,
  "mapper_running": true,
  "node_ready": true,
  "health": "ok",
  "severity": "normal",
  "overall_status": "available",
  "reason": "control/status path is available; sensor data freshness is separate"
}
```

## 해석 규칙

- `DeviceStatus`에 `power:on` 같은 값이 있어도 timestamp가 오래됐으면 현재값이 아니라 마지막 snapshot이다.
- dashboard의 availability는 Device CR 존재 여부나 `state=online` 단독 판단이 아니라 node/mapper/DeviceStatus/control heartbeat 선행 조건을 함께 본 결과다.
- InfluxDB row의 `device_id`가 Device 이름과 맞지 않으면 dashboard가 해당 telemetry를 매칭하지 못하지만, 이 경우도 availability는 유지되고 `telemetry_status=stale`로 표시된다.
- 현재 Jetson Arduino 기반 device의 raw sensor값 temperature/raw, light/value, magnetic/value, acceleration/x,y,z row는 sensor freshness KPI에만 반영한다.
