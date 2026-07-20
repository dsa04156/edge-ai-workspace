# 옥동 시나리오 생산성 KPI

## 목적

이 문서는 EdgeX 기반 물리 디바이스 운영 가시화를 옥동 실공장 시나리오의 생산성 언어로 설명한다. 목표는 자동 제어 효과를 주장하는 것이 아니라, 운영자가 inventory, Device Service 연결, Core Data event freshness와 서비스 영향 범위를 빠르게 이해해 점검 시간을 줄일 수 있음을 보이는 것이다.

```text
EdgeX device 상태와 최신 event를 한 화면에서 보고 문제 위치를 좁히는 운영 가시화 PoC
```

## 현장 문제와 개선점

| 현장 문제 | Dashboard 정보 | 생산성 의미 |
|---|---|---|
| 관리 대상 inventory가 분산됨 | Core Metadata `registered_device_count` | 관리 범위를 한 기준으로 확인 |
| 어떤 수집 서비스가 장치를 소유하는지 불명확 | profile, Device Service, protocol | 담당 수집 경로를 즉시 식별 |
| 등록 상태와 실제 데이터 유입을 혼동 | admin/operating/connection + Core Data freshness | 상태 문제와 event 문제를 분리 |
| AI·저장소 영향 범위 추적이 느림 | source/resource/latest readings + consumer relation | 영향 범위를 빠르게 설명 |
| 모든 장치를 수동 점검 | degraded/unavailable focus list | 우선 점검 대상 축소 |

Kubernetes node 정보는 AI/workload 배치 진단에만 사용한다. 물리 디바이스 KPI의 authority 또는 availability gate가 아니다.

## 핵심 KPI

### 1. 등록 디바이스 수

| 항목 | 내용 |
|---|---|
| 이름 | `registered_device_count` |
| 의미 | EdgeX Core Metadata에 등록된 device 수 |
| 운영자 해석 | 현재 관리 대상 물리 device 규모 |

### 2. 사용 가능 디바이스 수

| 항목 | 내용 |
|---|---|
| 이름 | `available_device_count` |
| 의미 | 허용된 admin 상태, `operatingState=UP`, fresh Core Data event를 만족한 수 |
| 운영자 해석 | 현재 EdgeX 경로에서 관측 가능한 device 규모 |

`degraded_device_count`와 `unavailable_device_count`를 함께 제시해 점검 범위를 설명한다.

### 3. EdgeX 연결 비율

| 항목 | 내용 |
|---|---|
| 이름 | `edgex_connection_ratio` |
| 분자 | `edgex_connected_device_count` |
| 분모 | `registered_device_count` |
| 운영자 해석 | Core Metadata/Device Service 상태로 connected인 관리 대상 비율 |

### 4. Device Service 가용 비율

| 항목 | 내용 |
|---|---|
| 이름 | `device_service_availability_ratio` |
| 분자 | `device_service_available_count` |
| 분모 | `registered_device_count` |
| 운영자 해석 | EdgeX Device Service 수집 경로가 사용 가능한 device 비율 |

### 5. Core Data event 관측 수

| 항목 | 내용 |
|---|---|
| 이름 | `core_data_event_device_count` |
| 의미 | 최신 Core Data event가 존재하는 device 수 |
| 운영자 해석 | 등록 이후 실제 event가 한 번 이상 관측된 범위 |

### 6. Core Data freshness 비율

| 항목 | 내용 |
|---|---|
| 이름 | `core_data_freshness_ratio` |
| 분자 | `fresh_core_data_event_device_count` |
| 분모 | `registered_device_count` |
| 보조 수치 | `stale_core_data_event_device_count` |
| device field | `latest_event_timestamp`, `telemetry_freshness` |
| 운영자 해석 | 최근 event가 계속 들어오는 관리 대상 비율 |

Freshness는 `EDGEX_EVENT_FRESH_SECONDS`를 기준으로 `fresh`, `stale`, `no_events`를 구분한다. `latest_readings`는 최신 event의 `source_name`, `resource_name`, value와 timestamp를 제공한다.

### 7. 운영자 우선 점검 대상 수

| 항목 | 내용 |
|---|---|
| 이름 | `operator_focus_count` |
| 의미 | degraded device 수 + unavailable device 수 |
| 운영자 해석 | 전체를 순회하지 않고 먼저 점검할 물리 device 수 |

Focus reason은 `admin_state`, `operating_state`, `connection_state`, `device_service_available`, `telemetry_freshness`로 설명한다. Node 이상 수를 이 물리 device KPI에 더하지 않는다.

### 8. 서비스 영향 범위

| 항목 | 내용 |
|---|---|
| 이름 | service binding coverage |
| 근거 | `device_service_name`, profile, protocol, Core Data source/resource, consumer relation |
| 운영자 해석 | 어느 device input이 AI 서비스, 저장소, dashboard에 영향을 주는지 확인 |

이 지표는 device → EdgeX Device Service → Core Data → consumer의 추적 가능성을 설명한다. 자동 orchestration 성능 지표가 아니다.

## MQTT canary KPI 해석

현재 전달 범위의 physical example은 `vib-arduino-acceleration-01`이다. 다음 증거를 함께 제시한다.

1. `source=edgex`
2. profile과 Device Service identity
3. `protocol_names`의 MQTT
4. admin/operating/connection 상태
5. latest Core Data event timestamp와 freshness
6. latest acceleration readings의 source/resource/value
7. AI/storage/dashboard consumer 관계

단일 canary 결과를 전체 공장, 전체 protocol 또는 장기 가용성 성과로 외삽하지 않는다.

## 생산성 설명 문구

```text
본 PoC는 EdgeX Core Metadata의 device 등록·서비스 연결 상태와 Core Data 최신 event를 통합 dashboard에서 가시화한다. 운영자는 profile, Device Service, protocol, admin/operating/connection 상태와 source/resource별 최신 reading을 한 흐름에서 확인하고, degraded/unavailable focus list로 점검 대상을 좁힐 수 있다. 이를 통해 현장 점검 경로 단순화와 원인 파악 시간 단축 가능성을 설명한다.
```

이는 측정된 인력 절감률, 자동 복구율 또는 생산량 증가율을 뜻하지 않는다. 실제 정량 효과는 현장 baseline, 반복 측정, 운영 승인으로 별도 검증해야 한다.

## Protocol wave 경계

| 범위 | KPI 포함 여부 |
|---|---|
| MQTT `vib-arduino-acceleration-01` | 현재 canary 증거가 있을 때 포함 |
| Serial | 구현·현장 검증 전에는 제외 |
| Modbus | 구현·현장 검증 전에는 제외 |
| OPC-UA | 구현·현장 검증 전에는 제외 |
| RTSP | 구현·현장 검증 전에는 제외 |

후속 wave는 각각 Core Metadata identity, Device Service, protocol contract, Core Data event freshness와 consumer 처리를 검증한 뒤 KPI에 포함한다.

## 현재 범위에서 말하지 않는 것

- 자동 device 제어 또는 자동 복구 효과
- 동적 workflow 실행 성능
- runtime offloading 또는 자동 재배치 효과
- 미구현 protocol의 연결률
- 문서 예시만으로 입증한 live 배포 상태

Workflow/node 설계 화면과 운영 보조 agent는 read-only 또는 dry-run이다. EdgeX 또는 Kubernetes 리소스를 수정하지 않는다.
