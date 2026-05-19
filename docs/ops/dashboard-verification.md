# Dashboard 검증 체크리스트

## 목적

이 문서는 KubeEdge 혼합 디바이스 PoC dashboard가 서비스 데모와 통합 운영 가시화를 제대로 보여주는지 확인하기 위한 체크리스트다.

검증 대상은 read-only 상태 표시다. workflow/offloading/placement/autonomous agent 제어, MQTT command 실행, actuator command 실행은 검증 대상이 아니다.

## 1. Overview KPI

Dashboard 상단 KPI에서 다음 항목이 보여야 한다.

| 표시 항목 | API/KPI 필드 | 의미 |
|---|---|---|
| registered device count | `kpis.registered_device_count` | KubeEdge Device CR로 등록된 device 수 |
| live device count | `kpis.live_device_count` | 현재 healthy device 수 |
| telemetry configured ratio | `kpis.device_telemetry_ratio` | telemetry-enabled device / 전체 registered device |
| telemetry freshness ratio | `kpis.telemetry_freshness_ratio` | fresh telemetry device / telemetry-enabled device |
| DeviceStatus freshness ratio | `kpis.device_status_freshness_ratio` | fresh DeviceStatus snapshot / 전체 registered device |
| operator focus count | `kpis.operator_focus_count` | degraded/unavailable device 수 + non-healthy node 수 |
| service-bound device count | `kpis.service_bound_device_count` | service demo group에 묶인 device 수 |
| device-service binding ratio | `kpis.device_service_binding_ratio` | service-bound device / 전체 registered device |

주의:

- `device_telemetry_ratio`는 telemetry configured ratio다.
- telemetry freshness는 `telemetry_freshness_ratio`와 `fresh_telemetry_device_count`로 본다.
- 두 비율을 같은 의미로 설명하지 않는다.
- `operator_focus_count`에는 workflow risk를 포함하지 않는다.

## 2. Device Table / Device List

각 device row에서 다음 필드를 표시하거나 바로 확인할 수 있어야 한다.

| 필드 | 확인 의미 |
|---|---|
| `name` | device name |
| `node_name` | 할당된 edge node |
| `device_type` | env/vib/act/rpi-env/rpi-vib/rpi-act/temp 등 분류 |
| `telemetry_enabled` | InfluxDB data-plane 대상인지 여부 |
| `telemetry_fresh` | InfluxDB device-level latest sample 기준 fresh 여부 |
| `telemetry_last_seen_at` | latest sample `_time` |
| `telemetry_property` | latest sample property. act/rpi-act는 `health` 기준 |
| `device_status_fresh` | DeviceStatus snapshot freshness. healthy 필수 조건 아님 |
| `mapper_running` | 할당 node의 mqttvirtual mapper Running 여부 |
| `node_ready` | dashboard 기준 node health. Kubernetes Ready와 구분 |
| `overall_status` / `status` | 최종 상태 |
| `reason` / `status_reason` | 운영자가 볼 원인 문구 |
| `service_demo_group` | 연결된 서비스 데모 그룹 |
| `service_connected` | 서비스 데모 연결 여부 |

정상 기준:

- telemetry-enabled device는 `telemetry_fresh=true`이면 DeviceStatus stale이어도 healthy 가능하다.
- `node_ready=false`, `mapper_running=false`, `telemetry_fresh=false`는 reason 또는 issue/focus list에서 원인이 보여야 한다.

## 3. Service Binding / Relation View

연결 관계 영역에서 다음 흐름이 보여야 한다.

```text
Device -> Edge Node -> Telemetry/Status -> Service Demo
```

서비스 그룹 기준:

| device 계열 | service demo group |
|---|---|
| `env-device-*`, `rpi-env-device-*`, `temp-device-01` | 환경 상태 모니터링 |
| `vib-device-*`, `rpi-vib-device-*` | 설비/진동 상태 모니터링 |
| `act-device-*`, `rpi-act-device-*` | command 상태 확인 |

확인 항목:

- device row 또는 relation view에 `service_demo_group`이 표시된다.
- `service_bound_device_count`가 표시된다.
- `device_service_binding_ratio`가 표시된다.
- service binding은 frontend 하드코딩이 아니라 state-aggregator API의 `service_demo_group`, `service_binding_source`, `service_binding_reason` 값을 렌더링한다.

## 4. Issue / Focus List

운영 상태 영역은 운영자가 먼저 볼 대상을 줄이는 용도다.

Issue/focus list 기준:

- degraded device
- unavailable device
- non-healthy node
- `mapper_running=false`
- `telemetry_fresh=false`
- `node_ready=false`

`operator_focus_count` 기준:

```text
degraded/unavailable device 수 + non-healthy node 수
```

포함하지 않는 것:

```text
workflow risk
offloading risk
placement risk
autonomous agent action
```

## 5. Explain Panel

Dashboard의 Explain Panel은 RAG 챗봇이나 LLM agent가 아니라 현재 `/state/dashboard` payload를 deterministic JavaScript rule로 해석하는 read-only 설명 영역이다.

확인 방법:

1. Device list에서 device row를 클릭한다.
2. 우측 또는 하단 Explain Panel에 device 상세 필드와 적용 rule이 표시되는지 확인한다.
3. Overview KPI 카드를 클릭한다.
4. KPI key, 현재 값, 정의 설명이 표시되는지 확인한다.
5. 운영 상태 Issue/Focus 항목을 클릭한다.
6. 우선 점검 대상이 된 이유와 다음 확인 위치가 표시되는지 확인한다.

Device row 클릭 시 표시되어야 하는 필드:

| 필드 | 의미 |
|---|---|
| `device name` | device name |
| `node_name` | 할당 node |
| `device_type` | device 분류 |
| `overall_status` | 최종 상태 |
| `reason` | state-aggregator 판단 이유 |
| `telemetry_enabled` | telemetry 대상 여부 |
| `telemetry_fresh` | InfluxDB latest sample freshness |
| `telemetry_last_seen_at` | latest sample timestamp |
| `telemetry_property` | latest sample property |
| `telemetry_value` | latest sample value |
| `device_status_fresh` | DeviceStatus snapshot freshness |
| `device_status_last_reported_at` | DeviceStatus snapshot timestamp |
| `mapper_running` | 할당 node mapper Running 여부 |
| `node_ready` | dashboard 기준 node_ready |
| `service_demo_group` | 연결된 서비스 데모 그룹 |
| `service_connected` | 서비스 데모 연결 여부 |

적용 rule 확인 기준:

| Rule | 조건 | 설명 요지 |
|---|---|---|
| Rule A | `overall_status=healthy`, `telemetry_fresh=true` | InfluxDB latest telemetry가 fresh하므로 healthy |
| Rule B | `severity=critical` | telemetry는 들어오지만 severity critical로 degraded |
| Rule C | `telemetry_enabled=true`, `telemetry_fresh=false` | publisher/MQTT/mapper/InfluxDB 경로 확인 |
| Rule D | `mapper_running=false` | 할당 node의 mqttvirtual mapper 확인 |
| Rule E | `node_ready=false` | dashboard 기준 node unavailable 확인 |
| Rule F | `telemetry_fresh=true`, `device_status_fresh=false` | data-plane은 살아 있고 status-plane 점검 필요 |
| Rule G | `service_connected=false` | service binding rule 또는 naming rule 확인 |

KPI 설명 확인 기준:

- `registered_device_count`: KubeEdge에 등록된 전체 Device CR 수
- `live_device_count`: state-aggregator 최종 status가 healthy인 device 수
- `telemetry_device_count`: telemetry_enabled device 수
- `device_telemetry_ratio`: telemetry configured ratio. freshness 비율 아님
- `fresh_telemetry_device_count`: telemetry_fresh == true인 device 수
- `telemetry_freshness_ratio`: fresh telemetry device 수 / telemetry_enabled device 수
- `fresh_device_status_count`: device_status_fresh == true인 device 수
- `device_status_freshness_ratio`: fresh DeviceStatus device 수 / 전체 device 수
- `operator_focus_count`: degraded/unavailable device 수 + non-healthy node 수
- `service_bound_device_count`: service demo group에 연결된 device 수
- `device_service_binding_ratio`: service-bound device 수 / 전체 registered device 수

Issue/Focus 설명 확인 기준:

- `telemetry_fresh=false`: publisher 실행 위치, local mosquitto, mapper log, InfluxDB 적재 상태 확인
- `mapper_running=false`: mapper pod와 node 배치 확인
- `node_ready=false`: node 상태와 edgecore/cloudcore 확인
- `device_status_fresh=false` + `telemetry_fresh=true`: DeviceStatus report path 확인

## 6. Reason 문구

reason은 운영자가 바로 다음 점검 위치를 알 수 있게 구체적이어야 한다.

허용/권장 예시:

```text
recent InfluxDB telemetry
recent InfluxDB telemetry, but severity is critical
mapper is running but telemetry has not reached InfluxDB
InfluxDB telemetry stale
assigned mapper is not running
assigned node is unavailable
device is not bound to expected node
DeviceStatus stale but telemetry fresh
```

해석 기준:

- `recent InfluxDB telemetry`: data-plane latest sample이 fresh하다.
- `InfluxDB telemetry stale`: publisher/MQTT/mapper/InfluxDB 경로 중 하나가 끊겼을 수 있다.
- `assigned mapper is not running`: 해당 node의 mqttvirtual mapper부터 확인한다.
- `assigned node is unavailable`: node/Prometheus/node-exporter 상태부터 확인한다.
- `DeviceStatus stale but telemetry fresh`: status-plane은 오래됐지만 data-plane은 살아 있으므로 healthy 가능하다.

## 7. InfluxDB timestamp 표시 해석

Dashboard와 API의 telemetry freshness는 InfluxDB latest sample 기준이다.

- InfluxDB UI의 `_start`와 `_stop`은 Flux query 조회 window이며 device start/stop 이벤트가 아니다.
- 실제 telemetry sample timestamp는 `_time`이다.
- Dashboard의 `telemetry_fresh`는 device-level latest sample 기준이다.
- property별 latest freshness를 보장하지 않는다.
- act/rpi-act device의 dashboard freshness 기준 property는 현재 `health` liveness row다.
- `ts`는 publisher payload에는 포함될 수 있지만 현재 dashboard freshness 판단용 DB push property가 아니다.

## 8. API 기반 빠른 확인

port-forward:

```bash
kubectl -n edge-orch port-forward svc/state-aggregator 8000:80
# 현재 로컬 클러스터처럼 service가 default namespace에 있으면:
# kubectl -n default port-forward svc/state-aggregator 8000:8000
```

확인:

```bash
curl -s http://localhost:8000/state/dashboard
python3 tools/check_dashboard_api.py --base-url http://localhost:8000
```

특정 device 확인:

```bash
python3 tools/check_dashboard_api.py --base-url http://localhost:8000 --device rpi-act-device-03
```

## 9. 화면 정상 판정

정상 화면은 다음을 만족한다.

1. Overview KPI에서 telemetry configured ratio와 telemetry freshness ratio가 분리되어 보인다.
2. DeviceStatus freshness ratio가 telemetry freshness와 별도 KPI로 보인다.
3. Device list에서 telemetry property, latest timestamp, mapper/node 상태, reason을 확인할 수 있다.
4. Relation view에서 device-service binding이 보인다.
5. Issue/focus list가 degraded/unavailable device, non-healthy node, mapper/telemetry/node 문제를 보여준다.
6. act/rpi-act device는 `telemetry_property=health`로 liveness를 설명한다.
7. workflow/offloading/placement/autonomous agent가 현재 구현 기능처럼 보이지 않는다.
