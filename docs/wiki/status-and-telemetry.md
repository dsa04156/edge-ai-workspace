# 상태와 텔레메트리

## 한 줄 요약

`DeviceStatus`는 저빈도 status/control snapshot이다.
raw telemetry는 data-plane stream이며 `DeviceStatus`로 취급하지 않는다.

## 현재 기준

프로젝트는 두 신호를 분리한다.

| 신호 | Plane | 의미 |
|---|---|---|
| raw telemetry | data-plane | 센서 값, 이력, freshness, 분석 입력 |
| DeviceStatus | status/control-plane | health, severity, command state, online/offline, control response |

telemetry 대상 device의 dashboard availability는 fresh telemetry를 우선 기준으로 본다.
`DeviceStatus` freshness는 별도 운영 신호이며 health의 단독 증거가 아니다.

## 경계

현재 정책상 아래 해석은 금지한다.

- raw telemetry 값을 `DeviceStatus`로 올리지 않는다.
- MapperFramework를 raw telemetry export engine으로 확장하지 않는다.
- `status.state=online`만으로 healthy라고 판단하지 않는다.
- `DeviceStatus` stale이 raw sensor data stale을 자동으로 뜻하지 않는다.
- raw telemetry freshness가 모든 property별 freshness를 보장하지 않는다.

## Freshness 해석

dashboard는 아래 값을 분리한다.

| 필드 | 의미 |
|---|---|
| `telemetry_fresh` | InfluxDB device-level latest sample이 freshness window 안에 있음 |
| `device_status_fresh` | KubeEdge DeviceStatus snapshot이 freshness window 안에 있음 |

InfluxDB `_start`와 `_stop`은 query window다.
실제 sample timestamp는 `_time`이다.

## 운영상 의미

device가 degraded로 보이면 아래 순서로 좁힌다.

1. node readiness와 node health
2. mapper pod running 상태
3. telemetry latest sample time
4. `DeviceStatus` snapshot freshness
5. service binding metadata

telemetry는 fresh인데 `DeviceStatus`가 stale이면 data-plane은 살아 있고 status-plane snapshot이 stale한 상태로 설명한다.
`DeviceStatus`는 fresh인데 telemetry가 stale이면 status/control snapshot은 보이지만 raw sensor stream이 stale한 상태로 설명한다.

## 관련 Wiki

- [현재 데모 흐름](current-demo-flow.md)
- [대시보드와 KPI 모델](dashboard-and-kpi.md)
- [운영 진입점](operations-entry-points.md)

## 근거 문서

- [DeviceStatus 정책](../device-status-policy.md)
- [Raw Telemetry Data Plane](../raw-telemetry-data-plane.md)
- [대시보드 정보 구조](../dashboard-information-structure.md)
- [현재 데모 경로](../current-demo-path.md)
