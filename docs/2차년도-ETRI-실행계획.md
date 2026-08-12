# 2026년도 2차년도 ETRI 실행계획

> 기준일: 2026-08-04
>
> 이 문서는 2차년도 옥동 PoC에서 ETRI가 책임지고 구현·검증할 범위를 고정한다. 협약 원문은 PDF를 따르며, 현재 구현 상태는 코드·Kustomize render·테스트를 기준으로 확인한다.

## 1. 2차년도 목표

옥동 현장의 PLC·MES·센서 데이터를 엣지 AI 플랫폼에 연결하고 다음 두 서비스를 하나의 운영 흐름으로 검증한다.

1. 센서·MES 데이터 기반 생산품질 양품·불량 판별
2. 메인·보조 유압펌프 및 모터 이상 감지

두 서비스는 모델 정확도만 평가하는 별도 프로그램이 아니다. 데이터 수집, 서비스 컨테이너 실행, 엣지·서버 분산, 결과 저장·조회, 장애 복구, 통합 모니터링을 함께 확인하는 대표 PoC다.

## 2. ETRI가 책임지는 범위

| 영역 | ETRI 책임 | 완료 증거 |
|---|---|---|
| 플랫폼 기준 | EdgeX 물리 Device/Profile/Core Data와 KubeEdge node/workload 책임 경계 고정 | `docs/프로젝트-범위.md`, root Kustomize render |
| 현장 연계 | Protocol Adapter와 edge telemetry agent의 입력·재전송 계약 | canonical Event, SQLite outbox, HTTPS persisted ACK 테스트 |
| 디바이스 관리 | 디바이스 등록·서비스 연결·상태·telemetry freshness 중앙 조회 | Core Metadata/Core Data readback, dashboard API |
| 서비스 실행 기반 | AI 서비스 컨테이너의 입력·출력 계약, 배치 위치, 재시작 정책 제공 | 서비스별 manifest와 E2E 기록 |
| 장애 대응 | 통신 단절 저장·재전송, 서비스 실패 재시작, 원인별 운영 절차 | 장애 주입 테스트와 runbook |
| 운영 가시화 | 센서·노드·서비스·알림·KPI를 한 화면에서 해석 가능하게 구성 | `state-aggregator`, dashboard, 검증 결과 |
| 확장 설계 | 물리·가상 디바이스, workflow source/binding을 후속 계약으로 정리 | 설계 문서와 dry-run preview |

AI 모델 자체의 연구 책임은 모델 담당 기관이 가지며, ETRI는 모델이 플랫폼 데이터 경로와 운영 흐름에서 재현되도록 연결한다.

## 3. 목표 아키텍처

```text
현장 PLC / MES / 센서 / 카메라
  ├─ Protocol Adapter (Serial/I2C/Modbus/OPC-UA/MQTT 등)
  ├─ canonical EdgeX v3 Event 생성
  └─ edge-telemetry-agent
       ├─ SQLite WAL outbox: 중앙 ACK 전까지 보존
       └─ HTTPS/mTLS ingest
             ↓
중앙 Edge AI 서버 (etri-ser0002-cgnmsb)
  ├─ ingest gateway
  ├─ EdgeX Core Keeper / Metadata / Data / Command / MessageBus
  ├─ PostgreSQL (Core Data 영구 저장)
  ├─ state-aggregator / dashboard
  └─ AI 서비스 컨테이너 및 결과 consumer

KubeEdge/Kubernetes
  └─ 노드·워크로드 배치와 상태 진단
```

중앙 MessageBus는 EdgeX 내부 런타임용이다. 센서에서 중앙으로 보내는 전송 경로나 엣지 장애 버퍼로 설명하지 않는다. RTSP 영상 프레임은 Core Data에 넣지 않고 요청된 Workflow Pod가 직접 구독하며 상태와 분석 결과 metadata만 표준 Event로 보낼 수 있다.

## 4. 현재 구현과 목표의 차이

| 구분 | 현재 checkout에서 확인되는 것 | 2차년도 승격 조건 |
|---|---|---|
| 중앙 EdgeX | `edgex/k8s`에 Core 서비스·PostgreSQL·gateway 배치 | 서버 1세트, health/readback 증거 |
| 엣지 수집 | direct adapter → SQLite outbox → HTTPS agent 템플릿 | 실제 PLC/MES endpoint와 장애 replay |
| Sense HAT | `sensehat-001` metadata contract와 I2C fixture | 현장 센서 데이터 계약으로 교체 가능해야 함 |
| Serial/Modbus/OPC-UA | adapter/설계·테스트 wave가 혼재 | protocol별 실제 endpoint·Profile·Event·consumer 독립 검증 |
| AI 서비스 | state-aggregator와 운영 화면 기반 | 품질 판별·펌프/모터 이상감지 컨테이너 E2E |
| Workflow | 브라우저 local 구성·validation·preview | 실행 권한·입출력 계약·운영 승인 후 승격 |
| 오프로딩/재배치 | 현재 운영 기능 아님 | 별도 범위 변경과 검증 후 후속 단계 |

현재 checkout이 live Argo revision의 discovery/controller를 모두 재현한다고 쓰지 않는다. 차이는 [저장소 구조](저장소-구조.md)와 운영 기록에 분리해 남긴다.

## 5. 월별 추진계획

| 기간 | ETRI 실행 | 산출물·판정 |
|---|---|---|
| 8월 | 서비스 범위, 노드·디바이스 목록, 데이터 항목·주기·연결 방식 확정 | PoC 범위서, 데이터 명세서 초안, 소유자 승인 |
| 9월 | PLC·MES·센서 입력을 canonical Event로 수집하고 중앙 저장 검증 | adapter 계약, outbox/HTTPS E2E, Core Data readback |
| 10월 | 품질 판별과 펌프·모터 이상감지 컨테이너 연결 | 서비스 API, workflow source binding, 결과 schema |
| 11월 | 엣지·서버 배치, 통신 장애·서비스 장애·재시작 시험 | 장애 시험결과서, 복구 시간·유실 건수 기록 |
| 12월 | 수집→전처리→추론→저장→알림→화면 통합 PoC | 통합 시연, 운영 runbook, 최종 시험결과서 |

## 6. 서비스 데이터 계약

모든 서비스는 플랫폼 공통 필드와 서비스별 payload를 분리한다.

```yaml
event:
  device_name: "edgex-device-name"
  profile_name: "device-profile"
  source_name: "telemetry-source"
  origin: 0                 # EdgeX Event nanosecond timestamp
  readings: []
service:
  service_id: "quality-classifier-v1"
  production_order_id: "MES order key"
  input_window: "10s"
  result: {}
  model_version: "model digest"
```

MES 생산 건 연결키, 공통 timestamp, 품질 결과, 이상 점수, 모델 버전은 AI 서비스가 임의로 재정의하지 않는다. 상세 schema는 서비스별 부록으로 분리하고 플랫폼 문서에는 연결 계약만 둔다.

## 7. 완료 판단

다음 순서를 모두 통과해야 대표 서비스가 완료된 것으로 판정한다.

1. 승인된 Device/Profile과 실제 입력 endpoint가 확인된다.
2. canonical Event가 edge outbox에 먼저 기록된다.
3. 중앙 gateway가 Core Data 영구 저장 후에만 ACK한다.
4. 품질 또는 이상감지 서비스가 동일 입력 window를 재현한다.
5. 결과가 저장되고 dashboard/API에서 조회된다.
6. 통신·서비스 장애 후 중복·유실·재처리 결과가 기록된다.
7. 운영자가 디바이스·서비스·노드·KPI 상태를 한 화면에서 설명할 수 있다.

## 8. 하지 않는 것

- 승인 없는 자동 디바이스 등록
- 임의 container image 실행
- 전체 공장망 자동 스캔
- RTSP 원본 프레임의 EdgeX Core Data 저장
- LLM이 Kubernetes·EdgeX를 직접 변경하는 자동 제어
- dynamic workflow/offloading/replanning을 현재 완료 기능으로 표현

관련 설계는 [2차년도 가상디바이스·워크플로 설계](2차년도-가상디바이스-워크플로-설계.md)에 남기되 운영 기능과 분리한다.
