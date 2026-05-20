# Dashboard Policy

## 원칙

대시보드는 실제 센서 데이터의 DB latest timestamp와 `DeviceStatus` snapshot freshness를 분리해서 표시한다.

`status.state=online`만으로 healthy 처리하지 않는다.
healthy 판단은 Jetson sensor-collector가 MQTT로 보낸 실제 센서 데이터가 InfluxDB에 최근 적재됐는지를 우선 기준으로 삼는다.
현재 Jetson Arduino 센서는 temperature/raw, light/value, magnetic/value, acceleration/x,y,z 값을 InfluxDB에 남긴다.
`DeviceStatus` timestamp와 `health=ok`는 운영 snapshot 해석용 보조 정보이며, DB latest timestamp가 없으면 healthy 근거로 쓰지 않는다.
`status.lastOnlineTime`보다 `twins[].reported.metadata.timestamp`가 더 최신이면 reported timestamp를 DeviceStatus freshness 기준으로 표시한다.

## Freshness 설정

현재 기본값:

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=20
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

현재 mapper 기반 PoC는 실제 센서값을 5초 주기로 InfluxDB에 적재하므로 telemetry freshness는 20초로 둔다.
운영 데모에서 순간 지연으로 degraded가 흔들리면 `TELEMETRY_FRESH_SECONDS=30` 또는 `60`으로 완화한다.

## Timestamp 처리

`twins[].reported.metadata.timestamp`는 문자열일 수 있다.
Unix epoch milliseconds와 seconds를 모두 처리한다.

- `1777508184621`처럼 10자리보다 크면 milliseconds
- 10자리 수준이면 seconds
- ISO datetime 문자열도 UTC 기준으로 파싱

parse 실패 시 해당 field는 freshness 판단에서 제외하고 reason에 parse error를 남기는 방향으로 확장한다.

## 판단 필드

- `Device.spec.nodeName`: 어느 노드에 할당됐는지 확인
- `Device.spec.protocol.protocolName`: `mqttvirtual` mapper 확인 여부 결정
- `Device.spec.properties[].pushMethod`: data-plane telemetry 대상 여부
- `DeviceStatus.status.lastOnlineTime`: fallback DeviceStatus timestamp
- `DeviceStatus.status.twins[].reported.metadata.timestamp`: DeviceStatus freshness 우선 기준
- InfluxDB `device_telemetry`: device live/freshness 기준
  - env/vib/temp: raw telemetry property
  - act/rpi-act: `health` liveness property
- KPI 관련 주의
  - `telemetry_device_count`: raw telemetry 대상(device.spec.properties.pushMethod 기반) device 수 (현재 코드 기준)
  - `device_telemetry_ratio`: telemetry 설정 비율 = telemetry_device_count / registered_device_count (fresh 비율 아님)
  - `telemetry_freshness_ratio`: 실제 최신 telemetry 비율 = fresh_telemetry_device_count / telemetry_device_count
  - `sensor_data_freshness_ratio`: 실제 센서 데이터 freshness 비율 = fresh_sensor_data_device_count / sensor_data_device_count. 현재 dashboard의 메인 freshness KPI
  - `device_status_freshness_ratio`: 최신 DeviceStatus 비율 = fresh_device_status_count / registered_device_count. status-plane 보조 지표이며 메인 건강 판단 KPI가 아님
  - `operator_focus_count`: degraded/unavailable device 수 + non-healthy node 수

## 상태 판단 순서

1. Kubernetes `Device` 목록과 `DeviceStatus` 목록을 조회한다.
2. 같은 namespace/name의 `DeviceStatus.status`가 있으면 병합해서 snapshot 필드로 표시한다.
3. 노드 미할당 또는 할당 노드 `unavailable`이면 `unavailable`.
4. `mqttvirtual` 디바이스인데 해당 노드의 mapper Pod가 Running이 아니면 `unavailable`.
5. `health=offline` 또는 명시 상태값 `offline/disconnected/failed/unavailable/false`면 `unavailable`.
6. InfluxDB latest timestamp가 `TELEMETRY_FRESH_SECONDS` 이내면 `telemetry_fresh=true`.
7. DB timestamp가 fresh하면 `severity=critical`이 아닌 한 `healthy`.
8. DB timestamp가 없거나 stale이면 `degraded`.
9. reported timestamp와 `lastOnlineTime` 중 최신 timestamp는 DeviceStatus snapshot 표시용으로 사용한다.
10. dashboard는 `device_status_fresh`와 `device_status_last_reported_at`도 계속 표시해 운영자가 KubeEdge reported path 상태를 별도로 볼 수 있게 한다.

## Explain Panel 표시 기준

Explain Panel은 운영자가 즉시 판단할 핵심값만 표시한다. Device 선택 시 기본 표시값은 `status`, `reason`, `node`, `sensor`, `last seen`, `mapper`, `service`이다.

DeviceStatus freshness, binding source, protocol/model 같은 세부 필드는 API와 문서에는 유지하지만 기본 Explain Panel에는 표시하지 않는다. 현재 PoC의 1차 판단은 실제 센서 데이터 freshness이므로, DeviceStatus stale은 data-plane이 fresh한 경우 별도 Issue로 올리지 않는다.

## API 응답 필드

`/state/devices`는 최소한 다음 정보를 포함한다.

```json
{
  "name": "env-device-01",
  "nodeName": "etri-dev0001-jetorn",
  "kubeedge_state": "online",
  "device_status_fresh": true,
  "device_status_last_reported_at": "2026-04-24T07:43:51Z",
  "telemetry_fresh": true,
  "telemetry_last_seen_at": "2026-04-24T07:43:55Z",
  "mapper_running": true,
  "node_ready": true,
  "health": "ok",
  "severity": "normal",
  "overall_status": "healthy",
  "reason": "recent InfluxDB telemetry"
}
```

## 해석 규칙

- `DeviceStatus`에 `power:on` 같은 값이 있어도 timestamp가 오래됐으면 현재값이 아니라 마지막 snapshot이다.
- dashboard의 healthy는 InfluxDB latest timestamp를 우선 기준으로 판단한다.
- 현재 Jetson Arduino 기반 device는 실제 센서값 temperature/raw, light/value, magnetic/value, acceleration/x,y,z row가 DB freshness 기준이다.
- `DeviceStatus`의 `health=ok`만 있고 InfluxDB latest row가 없으면 healthy가 아니라 degraded로 본다.
- InfluxDB row의 `device_id`가 Device 이름과 맞지 않으면 dashboard가 해당 telemetry를 매칭하지 못한다.
- dashboard의 healthy는 Device CR 존재 여부나 `state=online` 단독 판단이 아니라 node/mapper 선행 조건과 DB freshness 기준을 함께 본 결과다.
