# AGENTS.md

## 작업 원칙

이 저장소는 KubeEdge node/workload 관리와 EdgeX 물리 디바이스 연동을 결합한 혼합 디바이스 엣지 AI 플랫폼 PoC다.
현재 목표는 복잡한 동적 오케스트레이션을 먼저 완성하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 운영 관점으로 보이게 만드는 것이다.

작업 전 아래 문서를 기준으로 판단한다.

- `docs/프로젝트-배경.md`: 과제 배경, 현재 목표, PoC 방향
- `docs/물리-디바이스-상태-정책.md`: EdgeX 물리 디바이스 상태와 telemetry 정책
- `docs/대시보드-판단-정책.md`: 대시보드 상태 판단 기준
- `docs/단계별-추진계획.md`: 동적 오프로딩, agent-assisted planning 후속 계획

## 현재 우선순위

1. 서비스 데모 1종을 먼저 완성한다.
2. EdgeX Device Profile/Device 등록과 Device Service 연동을 안정화한다.
3. 디바이스-서비스 연결 구조를 대시보드에서 보이게 한다.
4. 물리 디바이스 inventory, state, telemetry, command의 권위는 EdgeX로 단일화한다.
5. MapperFramework와 KubeEdge Device/DeviceStatus는 물리 연동의 legacy 경로로 두고 병행 plane이나 fallback으로 사용하지 않는다.
6. 동적 워크플로우, 오프로딩, agent-assisted planning은 후속 고도화로 둔다.

## Workflow Builder Prototype 경계

`state-aggregator` dashboard 안에 workflow stage, device/source binding, validation, execution plan을 보여주는 화면이 있더라도 이를 현재 PoC의 동적 오케스트레이션 완성 기능으로 설명하지 않는다.

현재 허용되는 범위는 다음으로 제한한다.

- EdgeX Core Metadata에 등록된 `Device` 목록과 Device Service 관리 상태 조회
- EdgeX Core Data latest Event/Reading 기준 source freshness 확인
- 물리 온디바이스, 데이터 source, resource profile 매핑 확인
- 브라우저 상태 안에서만 동작하는 workflow stage 구성과 device/resource bind/release dry-run
- 실행 전 validation과 execution plan preview
- Kubernetes apply/delete/restart, EdgeX metadata/state mutation, command publish, actuator command, runtime migration/offloading 실행 없음

이 기능을 현재 운영 기능으로 승격하려면 먼저 `docs/프로젝트-범위.md`, `docs/저장소-구조.md`, `docs/단계별-추진계획.md`에 범위, 검증 기준, 운영 책임을 명시한다.

## 구현 규칙

- 물리 디바이스 inventory와 schema는 중앙 EdgeX Core Metadata의 Device Profile과 Device를 권위로 사용한다.
- Jetson과 Raspberry Pi의 EdgeX Device Service가 실제 프로토콜 endpoint 연결, 표준화, 상태와 command를 독점 관리한다.
- Device Service는 Event/Reading을 `etri-ser0002-cgnmsb`의 중앙 EdgeX MessageBus에 발행하고 Core Data가 PostgreSQL에 저장한다.
- 중앙 EdgeX Core Keeper, Core Metadata, Core Data, Core Command, 내부 MessageBus, PostgreSQL은 server2에 한 세트만 배치한다.
- `edgex-device-mqtt`는 `etri-dev0001-jetorn`, `edgex-device-mqtt-sensehat`는 `etri-dev0003-raspi5`에 배치한다.
- 현재 1차 수직 슬라이스에는 SQLite offline replay가 없으며 중앙 MessageBus·네트워크 장애 시 telemetry가 유실될 수 있다. 복구 기준은 새 Event 수집 재개다.
- 현재 승인된 프로토콜은 MQTT 하나다. Serial, Modbus, OPC-UA, RTSP는 프로토콜별 profile·실장비·command·state·telemetry 검증 전까지 완료로 주장하지 않는다.
- KubeEdge는 엣지 노드와 워크로드 관리에만 사용하며 KubeEdge Device/DeviceModel/DeviceStatus를 물리 디바이스 권위나 병행 plane으로 사용하지 않는다.
- root `edgex/k8s/kustomization.yaml`이 현재 운영 배포 진입점이다.
- `edgex/telemetry-plane/`, HTTPS ingest gateway, edge telemetry agent, SQLite outbox와 `edgex/k8s/base/` overlays는 비활성 설계·프로토타입이며 현재 배포 경로가 아니다.
- `mappers/mqttvirtual/`, mapper direct-to-Influx, `command`/`heartbeat` topic은 legacy test/integration 경로이며 fallback이 아니다.
- 대시보드의 물리 디바이스 availability는 중앙 EdgeX `adminState`, `operatingState`, Core Data 최신 Event freshness로 판단한다.
- Kubernetes node placement는 물리 디바이스 availability gate가 아닌 선택적 진단 정보다.


## Legacy / Archive Boundary

아래 경로와 주제는 현재 PoC 구현 경로가 아니라 과거 실험, 참조, 보관 자료로 본다.

- `edge-orch/workflow_executor/`: 과거 workflow 실행/orchestration 실험
- `edge-orch/workflow_reporter/`: 과거 stage event reporting 실험
- `edge-orch/placement_engine/`: 과거 placement/offloading/replanning 실험
- `workflow/`: 과거 workflow/event/scenario manifest
- `docs/archive/*`: 과거 통합 기록, 연구 초안, legacy orchestration 자료
- legacy orchestration, dynamic offloading, runtime replanning, agent-assisted planning 관련 문서와 코드

처리 규칙:

- 위 자료는 히스토리와 비교 근거로만 읽고, 현재 서비스 데모 요구사항이나 구현 목표로 해석하지 않는다.
- 현재 작업 대상으로 승격하려면 먼저 `docs/프로젝트-범위.md`와 `docs/저장소-구조.md`를 갱신해 범위 변경을 명시한다.
- 별도 승인 없이 위 경로의 내용을 dashboard, DeviceStatus, telemetry, service demo의 현재 동작으로 설명하지 않는다.
- 삭제/이동은 이 문서의 규칙만으로 수행하지 않고, 별도 정리 작업에서 승인 후 진행한다.

## 문서 표현 규칙

유지할 표현:

- 서비스 데모 우선
- 디바이스-서비스 연결 구조
- 통합 운영 가시화
- 실공장 기반 PoC
- 현장 적용성
- 생산성 향상 효과
- 단계적 확장

피할 표현:

- 완전 자율형 오케스트레이션
- LLM이 전체 제어를 수행
- 동적 워크플로우 전체 구현 완료
- 고도화 기능이 이미 실증 완료된 것처럼 보이는 표현

## 산출물 우선순위

즉시 필요한 산출물은 서비스 데모 시나리오, 디바이스 등록/관리 절차, 디바이스-서비스 바인딩 명세, 대시보드 정보 구조, 옥동 시나리오 KPI 정의다.
연차별 정량 목표, 1000 디바이스 실증 계획, 논문/특허/표준 계획은 그 다음이다.
