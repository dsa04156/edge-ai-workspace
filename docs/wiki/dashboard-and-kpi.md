# 대시보드와 KPI 모델

## 한 줄 요약

dashboard는 운영 판단 화면이다.
node 상태, device 상태, telemetry freshness, service binding, KPI 의미를 묶어 운영자가 어디를 먼저 봐야 할지 판단하게 한다.

## 현재 기준

dashboard는 아래 질문에 답해야 한다.

1. 어떤 node가 active인가?
2. 어떤 device가 등록되어 있는가?
3. 각 device가 어느 node에 할당되어 있는가?
4. 최근 telemetry가 있는가?
5. `DeviceStatus` snapshot이 fresh한가?
6. mapper와 node 선행 조건이 정상인가?
7. 어떤 service demo group이 각 device를 쓰는가?
8. 어떤 degraded/unavailable 항목을 먼저 봐야 하는가?
9. 이 데모 상태가 생산성 KPI 설명과 어떻게 연결되는가?

주요 API 표면은 `state-aggregator`의 dashboard state다.

```text
generated_at
nodes[]
devices[]
workflows[]
summary
kpis
```

현재 설명은 `nodes`, `devices`, `kpis`, service binding 중심으로 둔다.
`workflows[]`는 호환 필드로 남아 있지만 현재 방향의 핵심 주장으로 쓰지 않는다.

## 상태 판단

dashboard는 `Device` 존재 여부나 `status.state=online`만으로 health를 판단하지 않는다.

telemetry 대상 device는 InfluxDB latest sample freshness를 data-plane의 주요 신호로 본다.
mapper 상태와 node 상태는 선행 조건이다.
`DeviceStatus` freshness는 status-plane 관측 신호다.

상태 용어:

| 상태 | 의미 |
|---|---|
| `available` | 선행 조건이 정상이고 필요한 telemetry freshness가 충족됨 |
| `degraded` | 일부 신호는 있으나 freshness 또는 보조 조건이 약함 |
| `unavailable` | node, mapper, assignment, offline 상태 또는 필수 signal path가 끊김 |

## KPI 해석

중요 KPI:

| KPI | 용도 |
|---|---|
| `active_node_count` | 사용 가능한 node 수 |
| `registered_device_count` | KubeEdge 등록 device 규모 |
| `live_device_count` | state-aggregator가 healthy로 판단한 device 수 |
| `telemetry_device_count` | telemetry 대상 device 수 |
| `sensor_data_freshness_ratio` | raw sensor freshness의 핵심 비율 |
| `device_status_freshness_ratio` | status-plane snapshot freshness 비율 |
| `service_bound_device_count` | service demo group에 연결된 device 수 |
| `operator_focus_count` | degraded/unavailable device와 non-healthy node 수 |

KPI 표현은 운영 가시화와 생산성 설명에 연결한다.
자율 제어 성과처럼 쓰지 않는다.

## 운영상 의미

dashboard는 다음 점검 대상을 분명히 보여줘야 한다.
Issue 설명은 내부 구현 flag보다 node, mapper, sensor freshness, service binding 원인 후보를 먼저 보여준다.

Explain panel은 아래 운영 필드를 먼저 보여준다.

- status
- reason
- node
- sensor
- last seen
- mapper
- service

namespace, protocol, model, binding-source 같은 구현 세부값은 API에 남길 수 있지만 첫 운영 화면을 지배하지 않게 한다.

## 관련 Wiki

- [운영 모델](operating-model.md)
- [현재 데모 흐름](current-demo-flow.md)
- [상태와 텔레메트리](status-and-telemetry.md)
- [운영 진입점](operations-entry-points.md)

## 근거 문서

- [대시보드 정보 구조](../dashboard-information-structure.md)
- [대시보드 판단 기준](../dashboard-policy.md)
- [디바이스-서비스 바인딩](../device-service-binding.md)
- [옥동 생산성 KPI](../okdong-productivity-kpi.md)
