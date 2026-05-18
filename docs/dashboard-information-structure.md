# Dashboard Information Structure

## 목적

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC dashboard가 어떤 정보를 보여줘야 하는지 운영 관점에서 정리한다.

현재 dashboard의 목적은 복잡한 자동 제어를 보여주는 것이 아니라, 디바이스와 서비스의 연결 구조, node 상태, telemetry freshness, DeviceStatus freshness, KPI를 한 화면에서 해석 가능하게 만드는 것이다.

## 한 줄 정의

```text
node state + device state + telemetry freshness + service binding + KPI -> 운영 dashboard
```

## dashboard 정보 구조 원칙

1. Device CR 존재 여부만으로 정상 판단하지 않는다.
2. `status.state=online`만으로 healthy 판단하지 않는다.
3. DB latest timestamp freshness와 DeviceStatus snapshot freshness를 분리한다.
4. mapper Running 여부와 node Ready 상태를 함께 본다.
5. service binding은 workflow orchestration이 아니라 서비스 데모 연결 구조로 해석한다.
6. 운영자가 먼저 볼 항목과 원인 후보를 dashboard에서 바로 확인할 수 있게 한다.

## 주요 API

현재 dashboard는 `state-aggregator`의 다음 API를 중심으로 구성한다.

| API | 역할 |
|---|---|
| `GET /state/dashboard` | dashboard 전체 데이터와 KPI 조회 |
| `GET /state/devices` | device별 상태, telemetry, DeviceStatus, mapper 정보 조회 |
| `GET /state/nodes` | node별 상태와 metric 조회 |
| `GET /state/summary` | 전체 운영 상태 요약 조회 |
| `GET /metrics` | Prometheus scrape용 metric 제공 |

## `/state/dashboard` 상위 구조

현재 `DashboardState` 모델은 다음 구조를 가진다.

```text
generated_at
nodes[]
devices[]
workflows[]
summary
kpis
```

현재 연구 방향에서는 `workflows[]`를 dashboard의 핵심 future 방향으로 확장하지 않는다. 과거 event 구조와 호환을 위해 남아 있는 필드로 보고, 현재 dashboard 설명은 `nodes`, `devices`, `kpis`, service binding 중심으로 둔다.

## 최상위 dashboard 영역

권장 dashboard 영역은 다음이다.

| 영역 | 목적 | 주요 지표 |
|---|---|---|
| Overview KPI | 전체 상태 요약 | active node, registered device, live device, telemetry ratio |
| Node State | node별 운영 상태 | node_health, cpu, memory, network |
| Device State | device별 상태 | overall status, node, telemetry age, properties |
| Device-Service Relation | device-node-telemetry-service 연결 | device -> node -> telemetry/status -> service group |
| Freshness Panel | data-plane/status-plane freshness 분리 | telemetry_fresh, device_status_fresh |
| Issue / Focus List | 운영자가 먼저 볼 대상 | degraded/unavailable reason |
| Scenario KPI | 서비스 데모 설명 지표 | operator_focus_count, service-bound count, freshness ratio |

## KPI 구조

현재 dashboard KPI는 다음 의미로 정리한다.

| KPI | 의미 | 운영 해석 |
|---|---|---|
| `active_node_count` | 사용 가능한 node 수 | 현재 운영 가능한 edge/cloud node 규모 |
| `node_online_ratio` | node online 비율 | 전체 node 중 online/healthy 비율 |
| `registered_device_count` | 등록 device 수 | KubeEdge에 등록된 device 규모 |
| `device_operational_ratio` | 운영 가능 device 비율 | healthy 또는 unavailable 제외 device 비율 해석 후보 |
| `live_device_count` | live 판단 device 수 | state-aggregator 최종 `overall_status`가 `healthy`인 device 수 |
| `telemetry_device_count` | telemetry 대상 device 수 | raw telemetry data-plane 대상(device.spec.properties.pushMethod 기반) device 수 |
| `device_telemetry_ratio` | telemetry 대상 device 비율 | telemetry 대상 device 수 / 전체 등록 device 수 (fresh 비율 아님) |
| `operator_focus_count` | 운영자가 우선 확인할 대상 수 | 현재 구현은 SLA/노드/대상 device 중심 합계(예: `sla_risk_workflow_count` + non-healthy node count + unavailable device count)으로 계산되며, degraded/stale telemetry/stale DeviceStatus를 자동으로 포함하지는 않음 |
| `service_bound_device_count` | 서비스 데모에 연결된 device 수 | device-service 연결 구조 가시성 |

현재 dashboard KPI에서는 service binding 이름을 사용한다.

```text
service_bound_device_count
device_service_binding_ratio
```

이 값은 workflow orchestration이 아니라 service/demo binding 의미로 해석한다.

## Device card 정보 구조

각 device card 또는 row는 다음 정보를 포함하는 것이 좋다.

| 필드 | 의미 | 출처 |
|---|---|---|
| `name` | device 이름 | KubeEdge Device metadata |
| `namespace` | namespace | KubeEdge Device metadata |
| `device_type` | device 분류 | 이름/model/protocol 기반 분류 |
| `node_name` / `nodeName` | 할당 node | `Device.spec.nodeName` |
| `protocol` | mapper protocol | `Device.spec.protocol.protocolName` |
| `model` | DeviceModel 이름 | `Device.spec.deviceModelRef.name` |
| `properties` | device property 목록 | `Device.spec.properties` |
| `telemetry_enabled` | raw telemetry 대상 여부 | property `pushMethod` 여부 |
| `service_connected` | service binding 여부 | 현재는 service/demo binding 의미로 해석 |
| `service_demo_group` | 서비스 데모 그룹 | `state-aggregator` backend 판단 |
| `service_binding_source` | 바인딩 판단 출처 | `device_name_pattern`, `event_binding` 등 |
| `service_binding_reason` | 바인딩 판단 이유 | `state-aggregator` backend 판단 |
| `mapper_running` | mapper Running 여부 | mapper pod 상태 |
| `node_ready` | 할당 node Ready 여부 | Kubernetes/Prometheus node 상태 |
| `telemetry_fresh` | DB latest timestamp freshness | InfluxDB latest timestamp |
| `telemetry_last_seen_at` | DB latest time | InfluxDB |
| `device_status_fresh` | DeviceStatus snapshot freshness | DeviceStatus timestamp |
| `device_status_last_reported_at` | DeviceStatus latest time | DeviceStatus |
| `health` | 운영 health 값 | DeviceStatus twin/status |
| `severity` | 운영 severity 값 | DeviceStatus twin/status |
| `overall_status` / `status` | dashboard 최종 상태 | state-aggregator 판단 |
| `reason` / `status_reason` | 상태 판단 이유 | state-aggregator 판단 |

## Node card 정보 구조

각 node card 또는 row는 다음 정보를 포함한다.

| 필드 | 의미 |
|---|---|
| `hostname` | node 이름 |
| `node_type` | cloud server, edge AI device, edge light device 등 |
| `node_health` | healthy / degraded / unavailable |
| `compute_pressure` | CPU 압력 |
| `memory_pressure` | memory 압력 |
| `network_pressure` | network 압력 |
| `raw_metrics.cpu_utilization` | CPU 사용률 |
| `raw_metrics.memory_usage_ratio` | memory 사용률 |
| `collected_at` | metric 수집 시각 |

## Device-Service Relation 영역

현재 dashboard의 relation 영역은 다음 흐름을 보여주는 것이 적절하다.

```text
Device -> Node -> Telemetry / Status -> Service Demo
```

현재 `dashboard.js`는 backend가 내려준 `service_demo_group`과 `service_binding_reason`을 사용해 다음 관계를 보여준다.

```text
Device -> Node -> Telemetry / Status -> Service Demo
```

즉, 서비스 그룹 판단 로직은 frontend의 device 이름 하드코딩이 아니라 `state-aggregator`의 `DeviceState` 응답 필드를 기준으로 한다.

예시:

```text
vib-device-01 -> etri-dev0001-jetorn -> fresh DB timestamp -> 설비 상태 모니터링 서비스
act-device-01 -> etri-dev0001-jetorn -> fresh DB timestamp -> command 상태 확인
rpi-env-device-01 -> etri-dev0002-raspi5 -> DB timestamp pending -> Raspberry Pi edge 상태 확인
```

## Freshness 표시 방식

freshness는 반드시 두 축으로 나눠 보여준다.

| freshness | 의미 | healthy 판단에서의 역할 |
|---|---|---|
| `telemetry_fresh` | raw telemetry data-plane이 최근 갱신됐는지 | InfluxDB latest 기준 |
| `device_status_fresh` | DeviceStatus snapshot이 최근 갱신됐는지 | DeviceStatus timestamp 기준 |

기본 기준값:

```bash
DEVICE_STATUS_FRESH_SECONDS=90
TELEMETRY_FRESH_SECONDS=90
MAPPER_HEARTBEAT_FRESH_SECONDS=60
```

해석:

- telemetry 최신값(InfluxDB)이 fresh이면 state-aggregator는 healthy로 판단하는 1차 기준이 된다 — DeviceStatus snapshot이 stale하더라도 telemetry가 fresh하면 최종 `healthy`로 표시될 수 있다.
- telemetry만 fresh이면 data-plane은 살아 있지만 status-plane이 stale한 상태로 별도 표기한다.
- DeviceStatus만 fresh이면 status-plane은 최신이나 raw telemetry가 stale한 상태로 별도 표기한다.
- 둘 다 stale이면 degraded 또는 unavailable 원인을 reason에 표시한다.

## InfluxDB Query Notes

- InfluxDB UI에서 볼 수 있는 `_start` / `_stop` 필드는 각 row의 device start/stop 이벤트가 아니라 Flux 쿼리의 조회 범위(window)를 보여주는 메타필드이다.
- 실제 telemetry 발생 시각은 `_time` 필드가 되며, dashboard와 state-aggregator는 `_time` 또는 명시된 `telemetry_last_seen_at` 값을 사용해 freshness를 판단한다.


## 상태 판단 표시

상태는 다음 세 단계로 단순화한다.

| 상태 | dashboard 의미 | 운영자 행동 |
|---|---|---|
| `healthy` | node/mapper/device/telemetry/status freshness가 기준을 만족 | 정상 관찰 |
| `degraded` | 일부 경로는 살아 있지만 fresh signal 또는 snapshot이 부족 | 원인 후보 확인 |
| `unavailable` | node, mapper, device assignment, offline 상태 등 운영 경로가 끊김 | 즉시 점검 |

주의:

- `status.state=online`은 참고값이다.
- dashboard의 healthy는 Device CR 존재나 `online` 값만으로 결정하지 않는다.

## Issue / Focus List

운영자가 먼저 확인할 대상은 다음 기준으로 뽑는다.

1. `unavailable` device
2. `degraded` device
3. `unavailable` node
4. mapper가 Running이 아닌 node
5. telemetry freshness가 없는 device
6. DeviceStatus freshness가 없는 device
7. service-connected device 중 상태가 degraded/unavailable인 device

표시할 문구는 `reason` 또는 `status_reason`을 우선 사용한다.

예시:

```text
vib-device-01: DB latest timestamp is missing
act-device-03: DB timestamp fresh; DeviceStatus snapshot is stale
rpi-env-device-02: assigned node is unavailable
```

## 운영자 기준 화면 해석 순서

운영자는 dashboard를 볼 때 기술 컴포넌트 이름보다 아래 질문 순서로 해석한다.

| 순서 | 운영자 질문 | dashboard/API에서 보는 값 |
|---|---|---|
| 1 | 지금 관리 대상 device가 몇 개인가? | `registered_device_count`, device list |
| 2 | 실제 데이터가 들어오는 device는 몇 개인가? | `live_device_count`, `device_telemetry_ratio`, `telemetry_fresh` |
| 3 | 운영 snapshot은 최신인가? | `device_status_fresh`, `device_status_last_reported_at` |
| 4 | 문제가 있으면 어느 node/device부터 봐야 하는가? | `operator_focus_count`, issue list, `reason` |
| 5 | device가 어떤 서비스 데모에 연결되는가? | `service_demo_group`, `service_binding_reason` |
| 6 | Jetson/Raspberry Pi 경로가 모두 보이는가? | node list, device `node_name`, mixed-device coverage |
| 7 | 이 상태를 생산성 효과로 어떻게 설명할 수 있는가? | `okdong-productivity-kpi.md`의 KPI 설명 |

이 순서를 기준으로 화면 문구는 “기술 내부 구조”보다 “운영자가 무엇을 먼저 확인해야 하는가”를 우선한다.

## Scenario KPI 영역

서비스 데모 관점에서는 다음 KPI를 함께 보여주는 것이 좋다.

| 표시 이름 | 의미 |
|---|---|
| Service-bound devices | 서비스 데모와 연결된 device 수 |
| Telemetry visibility | fresh telemetry device 비율 |
| Status visibility | fresh DeviceStatus device 비율 |
| Operator focus | 운영자가 우선 확인할 대상 수 |
| Mixed-device coverage | Jetson/Raspberry Pi/x86 연결 범위 |
| Issue reason coverage | reason이 있는 degraded/unavailable 항목 수 |

## naming 주의점

현재 코드에는 과거 workflow/event 구조에서 온 이름이 일부 남아 있다.

주의할 이름:

- `workflows[]`
- `WorkflowState`
- `WorkflowEvent`
- `POST /workflow-event`
- `GET /state/cost-model`

현재 연구 방향에서는 위 항목을 새로운 핵심 방향으로 설명하지 않는다. 참고: 코드와 API/모델에는 `WorkflowEvent`, `WorkflowState`, `ActionType`, `CostModelState` 등 legacy 호환용 필드가 남아 있으나, 현재 데모의 핵심 경로에서는 사용되지 않는 보조 필드로 간주한다.

문서와 dashboard 설명에서는 다음 표현을 우선 사용한다.

- service binding
- service-connected device
- demo group
- device-service relation
- 운영 가시화

이미 정리된 이름:

| 정리 전 이름 | 현재 이름 |
|---|---|
| `workflow_bound_device_count` | `service_bound_device_count` |
| `device_workflow_binding_ratio` | `device_service_binding_ratio` |

추후 검토할 항목:

| 현재 이름 | 검토 방향 |
|---|---|
| `workflow` 기반 event/API 설명 | 현재 데모에서는 service/demo binding과 분리해서 설명 |
| `workflows` dashboard 중심 표현 | 현재 데모에서는 숨기거나 archive 의미로 축소 |

## 현재 dashboard.js 기준 매핑

현재 `edge-orch/state-aggregator/app/static/dashboard.js`에서 확인되는 주요 UI 매핑은 다음이다.

| UI id / 함수 | 표시 내용 |
|---|---|
| `activeNodeCount` | `kpis.active_node_count` |
| `nodeRatio` | `kpis.node_online_ratio` |
| `deviceCount` | `kpis.registered_device_count` |
| `deviceHealthRatio` | `kpis.device_operational_ratio`, `kpis.live_device_count` |
| `telemetryRatio` | `kpis.device_telemetry_ratio` |
| `serviceBindingCount` | `kpis.service_bound_device_count` |
| `serviceBindingRatio` | `kpis.device_service_binding_ratio` |
| `focusCount` | `kpis.operator_focus_count` |
| `renderNodes` | node list, node health, cpu, memory |
| `renderDevices` | device list, status, node, telemetry age, properties |
| `renderRelations` | Device -> Node -> Twin / Telemetry |
| `renderAlerts` | unhealthy node/device alert |
| `renderScenario` | scenario KPI와 device status detail |

## 현재 범위에서 제외하는 것

다음은 dashboard 정보 구조의 현재 목표가 아니다.

- workflow stage별 자동 이동 시각화
- runtime replanning 결과 시각화
- placement engine의 자동 배치 결정 시각화
- cost model 기반 offloading 판단 시각화
- agent-assisted planning 결과를 운영자가 승인하는 UI
- LLM 기반 전역 제어 dashboard

위 항목은 현재 연구 방향에서 진행하는 다음 단계로 표현하지 않는다. 필요한 경우 과거 실험 또는 archive 자료로만 다룬다.

## 관련 문서

- `docs/current-demo-path.md`: 현재 device/MQTT/mapper/state-aggregator/dashboard 연결 경로
- `docs/device-service-binding.md`: 디바이스-서비스 연결 구조
- `docs/service-demo-scenario.md`: 서비스 데모 시나리오
- `docs/device-status-policy.md`: DeviceStatus와 raw telemetry 분리 정책
- `docs/dashboard-policy.md`: dashboard 상태 판단 기준
- `docs/okdong-productivity-kpi.md`: 옥동 시나리오 생산성 KPI 정의
