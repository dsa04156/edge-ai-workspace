# 대시보드와 KPI 모델

## 한 줄 요약

Dashboard는 EdgeX Core Metadata inventory/management state와 Core Data 최신 Event freshness를 같은 physical-device 판단으로 보여주고, Kubernetes/KubeEdge node·workload는 별도 진단 정보로 보여주는 운영 화면이다.

## 현재 dashboard 모델

`state-aggregator`의 EdgeX-backed API가 dashboard 입력이다.

```text
EdgeX Core Metadata + Core Data
  -> state-aggregator
  -> /state/devices, /state/dashboard, /state/summary
  -> dashboard
```

Dashboard는 다음 질문에 답해야 한다.

1. EdgeX에 어떤 physical Device, Profile, Device Service가 등록되어 있는가?
2. 관리 상태와 Device Service 연결 상태는 어떤가?
3. 최신 Core Data Event/Reading이 freshness 기준 안에 있는가?
4. 어떤 device를 먼저 점검해야 하는가?
5. 관련 Kubernetes/KubeEdge node와 workload는 정상 배치·실행 중인가?
6. 이 device가 어떤 서비스 데모 consumer와 연결되는가?
7. 연결이 Git에 등록됐는가, 장비가 실제 관측됐는가, Device Service 통신과 최신 데이터는
   각각 어떤 상태인가?
8. 새 장비에 재사용할 Adapter Runtime이 있는가, 없으면 검증된 node/hardware binding으로
   배포 가능한가?

`workflows[]`와 workflow KPI는 호환 또는 dry-run planning 표면일 수 있지만 current physical health나 자동 orchestration 완료의 근거가 아니다.

## Device API와 Explain Panel

`/state/devices`의 EdgeX physical-device contract는 다음 필드를 사용한다.

| 필드 | 의미 |
|---|---|
| `source` | physical authority이며 현재 값은 `edgex` |
| `name` | Core Metadata Device 이름 |
| `profile_name` | Device Profile |
| `device_service_name` | Core Metadata 호환용 논리 수집 서비스 식별자 |
| `protocol_names` | 등록 protocol 목록 |
| `admin_state` | Core Metadata 관리 허용 상태 |
| `operating_state` | Device Service가 보고한 동작 상태 |
| `connection_state` | `connected`, `disconnected`, `unknown`으로 정규화한 연결 상태 |
| `device_service_available` | `operating_state=UP` 여부 |
| `latest_event_timestamp` | 최신 Core Data Event/Reading 시각 |
| `latest_readings` | 최신 Event의 source/resource/value type/value/unit 정보 |
| `telemetry_freshness` | `fresh`, `stale`, `no_events` |
| `node_name` | 선택적 Kubernetes placement 진단 정보 |
| `physical_device_id` | EdgeX tag의 물리 source identity |
| `hardware_binding_id` | Git 카탈로그 exact 물리 연결 identity |

Explain Panel은 최소한 overall status와 reason, Profile, Device Service, protocol, `admin_state`, `operating_state`, `connection_state`, 최신 Event 시각/age, `telemetry_freshness`, typed Readings, 선택적 `node_name`을 보여준다. node/workload 근거와 EdgeX state/event 근거를 하나의 physical availability reason으로 섞지 않는다.

## Physical availability 판단

Physical availability는 EdgeX 필드와 Core Data 최신 Event로만 계산한다.

| 결과 | 판단 |
|---|---|
| `unavailable` | `admin_state=LOCKED`, `operating_state=DOWN`, 또는 `connection_state=disconnected` |
| `degraded` | `operating_state=UNKNOWN`, `connection_state=unknown`, 최신 Event가 없거나 stale, 또는 origin을 해석할 수 없음 |
| `available` | 잠기지 않았고 `operating_state=UP`, `connection_state=connected`, 최신 Core Data Event가 fresh |

`device_service_available`은 Device Service 상태를 빠르게 보이는 보조 field이며 단독으로 `available`을 뜻하지 않는다. `node_name`, Kubernetes Node Ready, workload 상태는 service execution/placement 진단에는 중요하지만 위 physical availability의 gate가 아니다.

## KPI

Physical-device KPI의 분모는 Core Metadata inventory다.

| KPI | 의미 |
|---|---|
| `registered_device_count` | Core Metadata 등록 Device 수 |
| `available_device_count` | EdgeX 상태와 fresh Core Data Event 기준 available 수 |
| `degraded_device_count` | EdgeX 또는 Event freshness가 불완전한 device 수 |
| `unavailable_device_count` | locked/down/disconnected device 수 |
| `edgex_connected_device_count` / `edgex_connection_ratio` | connected device 수 / registered device 수 |
| `edgex_operating_up_count`, `edgex_operating_down_count`, `edgex_operating_unknown_count` | EdgeX operating state breakdown |
| `edgex_admin_unlocked_count`, `edgex_admin_locked_count` | EdgeX admin state breakdown |
| `device_service_available_count` / `device_service_availability_ratio` | Device Service available 수 / registered device 수 |
| `core_data_event_device_count` | Core Data Event가 있는 device 수 |
| `fresh_core_data_event_device_count`, `stale_core_data_event_device_count` | fresh/stale 최신 Core Data Event device 수 |
| `core_data_freshness_ratio` | fresh 최신 Core Data Event device 수 / registered device 수 |
| `operator_focus_count` | degraded + unavailable physical device 수 |

`active_node_count`와 `node_online_ratio`는 node/workload 관찰용 별도 KPI다. `sla_risk_workflow_count`는 workflow dry-run/compatibility 영역이며 physical-device KPI나 `operator_focus_count`에 포함하지 않는다.

## 제외한 health 입력

다음은 current physical health, availability, KPI의 입력이나 fallback이 아니다.

- KubeEdge `DeviceStatus`와 DeviceStatus freshness
- MapperFramework 또는 mapper readiness
- mapper direct-write latest sample
- KubeEdge `Device`/`DeviceModel`, `mqttvirtual`, legacy mapper heartbeat

Kubernetes/KubeEdge node와 workload는 별도 card/filter에서 관찰한다. node 장애는 workload와 AI service에 영향을 줄 수 있지만 EdgeX physical availability를 덮어쓰지 않는다.

## direct 전달 상태

현재 운영 배포 진입점은 root `edgex/k8s/kustomization.yaml`이다. 중앙 namespace는 `edgex-system`, Serial/I2C Device Service namespace는 `edgex-edge`다. physical input `arduino-001`, `sensehat-001`의 기존 기능별 Device 12개와 승인 Saga의 Arduino aggregate 전환 Device 1개, 총 13개 identity를 API/KPI에서 집계한다. `장비 관리` 목록은 이 identity를 두 물리 source 카드로 묶고 개별 상태와 Reading은 카드 상세에서 표시한다.

2026-07-21 Jetson Serial, Raspberry Pi 직접 I2C Device Service, 중앙 server2 Core/PostgreSQL과 대시보드 조회를 같은 실행에서 확인했다. 과거 MQTT 기반 Sense HAT/HTTPS-outbox 증거는 보관 이력이며 현재 경로의 durable replay 근거가 아니다.

Serial과 Sense HAT I2C는 정상 경로만 지원 완료로 표시한다. 실제 분리·복구, Modbus, OPC-UA, 다른 I2C 장비·주소와 RTSP workflow는 프로토콜별 live evidence가 확보되기 전까지 지원 완료로 표시하지 않는다.

## Workflow/augmentation 경계

Workflow Designer와 augmentation resource 표면은 read-only 또는 dry-run이다. dashboard는 resource profile, validation, plan preview를 보여줄 수 있지만 Kubernetes workload 생성·이동, runtime offloading, EdgeX mutation, command publish를 수행하거나 완료된 운영 기능으로 주장하지 않는다.

`Device Management`는 이 경계와 분리된 검증 관리 화면이다. 첫 영역은 Git binding 등록,
EdgeX 장비 관측, Device Service 통신, Core Data 최신성을 별도 상태로 표시한다. 등록만으로
장비 감지를 추정하지 않는다. 운영자는 Runtime inventory, owner, phase와 EdgeX consumer를
확인하고, Git allowlist의 node/hardware binding만 선택해 Runtime과 EdgeX Profile/Device
연결을 함께 validation·apply한다. protocol package는 재사용 가능, 설치 가능, 연결 등록
필요, 검증 필요를 구분한다. state-aggregator에는
Kubernetes 쓰기 권한이 없으며 내부 HMAC으로 Adapter Controller에 요청한다. 외부/Argo
runtime은 재사용만 하고 Controller 소유 runtime만 재시작·조건부 퇴역한다.

## 관련 Wiki

- [현재 데모 흐름](현재-데모-흐름.md)
- [상태와 텔레메트리](상태와-텔레메트리.md)
- [운영 모델](운영-모델.md)
- [Adapter Runtime과 Device 연결 관리](../ops/어댑터-런타임-디바이스-연결-관리.md)

## 근거 문서

- [대시보드 판단 기준](../대시보드-판단-정책.md)
- [프로젝트 배경](../프로젝트-배경.md)
- [현재 서비스 데모 운영 Runbook](../ops/현재-데모-운영-절차.md)
