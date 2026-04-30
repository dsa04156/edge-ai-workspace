# Dashboard Policy

## 원칙

대시보드는 `DeviceStatus` snapshot freshness와 raw telemetry freshness를 분리해서 판단한다.

`status.state=online`만으로 healthy 처리하지 않는다.
`status.lastOnlineTime`보다 `twins[].reported.metadata.timestamp`가 더 최신이면 reported timestamp를 DeviceStatus freshness 기준으로 우선 사용한다.

## Freshness 설정

현재 기본값:

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=90
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

현재 mapper 기반 PoC는 raw telemetry를 60초 주기로 InfluxDB에 적재하므로 telemetry freshness는 90초로 둔다.
별도 고빈도 telemetry consumer를 붙이면 `TELEMETRY_FRESH_SECONDS`는 data-plane 적재 주기에 맞춰 다시 낮출 수 있다.

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
- InfluxDB `device_telemetry`: raw telemetry live/freshness 기준

## 상태 판단 순서

1. Kubernetes `Device` 목록과 `DeviceStatus` 목록을 조회한다.
2. 같은 namespace/name의 `DeviceStatus.status`가 있으면 병합해서 판단한다.
3. 노드 미할당 또는 할당 노드 `unavailable`이면 `unavailable`.
4. `mqttvirtual` 디바이스인데 해당 노드의 mapper Pod가 Running이 아니면 `unavailable`.
5. `health=offline` 또는 명시 상태값 `offline/disconnected/failed/unavailable/false`면 `unavailable`.
6. reported timestamp와 `lastOnlineTime` 중 최신 timestamp를 DeviceStatus snapshot 기준으로 사용한다.
7. DeviceStatus timestamp가 `DEVICE_STATUS_FRESH_SECONDS` 이내면 `device_status_fresh=true`.
8. InfluxDB latest telemetry timestamp가 `TELEMETRY_FRESH_SECONDS` 이내면 `telemetry_fresh=true`.
9. `telemetry_fresh=true`이고 `device_status_fresh=true`이면 `severity=critical`이 아닌 한 `healthy`.
10. `telemetry_fresh=true`이고 `device_status_fresh=false`이면 live data-plane은 살아 있지만 status snapshot이 stale이므로 `degraded`.
11. `telemetry_fresh=false`이고 `device_status_fresh=true`이면 status snapshot은 있으나 raw telemetry가 stale하므로 `degraded`.
12. 둘 다 false이면 노드/mapper 상태에 따라 `degraded` 또는 `unavailable`로 표시하고 reason에 원인을 남긴다.

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
  "reason": "fresh DeviceStatus reported timestamp and recent telemetry"
}
```

## 해석 규칙

- `DeviceStatus`에 `power:on` 같은 값이 있어도 timestamp가 오래됐으면 현재값이 아니라 마지막 snapshot이다.
- InfluxDB에 값이 있어도 DeviceStatus가 stale이면 KubeEdge reported path 문제를 별도로 본다.
- InfluxDB latest timestamp가 fresh하면 raw telemetry data-plane은 살아 있다고 본다.
- telemetry가 없는 actuator류는 DeviceStatus snapshot이 fresh하면 healthy로 볼 수 있다.
- dashboard의 healthy는 Device CR 존재 여부나 `state=online`이 아니라 freshness와 mapper/node 상태를 함께 본 결과다.
