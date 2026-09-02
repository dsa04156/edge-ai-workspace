# AGENTS.md

## 작업 원칙

이 저장소는 KubeEdge node/workload 관리와 EdgeX 물리 디바이스 연동을 결합한 혼합 디바이스 엣지 AI 플랫폼 PoC다.
현재 목표는 복잡한 동적 오케스트레이션을 먼저 완성하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 운영 관점으로 보이게 만드는 것이다.

작업 전 아래 문서를 기준으로 판단한다.

- `docs/프로젝트-범위.md`: 현재 구현, 후속 설계와 명시적 제외 범위의 최상위 기준
- `docs/저장소-구조.md`: 현재 구현 경로, 배포 소유권과 legacy 경계
- `docs/프로젝트-배경.md`: 과제 배경, 현재 목표, PoC 방향
- `docs/물리-디바이스-상태-정책.md`: EdgeX 물리 디바이스 상태와 telemetry 정책
- `docs/대시보드-판단-정책.md`: 대시보드 상태 판단 기준
- `docs/단계별-추진계획.md`: 2026년도 2차년도 옥동 PoC 목표, 일정, 기관별 역할과 산출물

## 현재 우선순위

1. 옥동 PLC·MES·센서 데이터 접근범위와 생산품질 판별, 유압펌프·모터 이상감지 서비스
   2종의 입력·출력 계약을 확정한다.
2. 현재 고정 센서 서비스 데모는 데이터 수집·배포·상태 가시화의 기술 기준선으로
   유지하되, 옥동 AI 서비스 2종을 이미 구현한 것으로 대체 설명하지 않는다.
3. EdgeX Device Profile/Device 등록과 Device Service 연동을 안정화한다.
4. 디바이스-서비스 연결 구조를 대시보드에서 보이게 한다.
5. 물리 디바이스 inventory, state, telemetry, command의 권위는 EdgeX로 단일화한다.
6. MapperFramework와 KubeEdge Device/DeviceStatus는 물리 연동의 legacy 경로로 두고 병행 plane이나 fallback으로 사용하지 않는다.
7. 워크플로우 실행, 엣지·서버 작업 분산, 장애 저장·재전송은 2차년도 구축 목표로
   단계별 구현·검증하며, 현재 dry-run 화면이나 기존 legacy 코드를 완료 기능으로
   설명하지 않는다. agent-assisted planning은 별도 후속 고도화로 둔다.

## 서비스 설계 dry-run 경계

과거 AI Pipeline/Workflow Builder와 전용 샘플 실행 API는 현재 대시보드 기능이 아니다.
`state-aggregator`의 `서비스 설계` 화면은 실제 EdgeX 입력과 Git 서비스 계약을 사용해
브라우저 안에서 서비스 초안, validation과 execution plan을 확인하는 dry-run 도구다.
이를 동적 오케스트레이션, 배포 또는 실행 기능으로 설명하지 않는다.

현재 허용되는 범위는 다음으로 제한한다.

- EdgeX Core Metadata에 등록된 `Device`·`DeviceProfile`과 Device Service 상태 조회
- EdgeX Core Data latest Event/Reading 기준 source freshness 확인
- Git `ServiceDescriptor` 기반 서비스 stage와 실제 EdgeX device/resource 매핑 확인
- 브라우저 상태와 versioned local draft 안에서만 동작하는 stage 구성과 source bind/release
- 실행 전 validation과 execution plan preview
- Kubernetes apply/delete/restart, EdgeX metadata/state mutation, command publish,
  actuator command, runtime migration/offloading 실행 없음

이 기능을 현재 운영 기능으로 승격하려면 먼저 `docs/프로젝트-범위.md`,
`docs/저장소-구조.md`, `docs/단계별-추진계획.md`에 범위, 검증 기준, 운영 책임을 명시한다.

## 운영 객체와 용어

- `물리 source`는 실제 Arduino, Sense HAT, PLC, 카메라와 그 연결 endpoint를 뜻한다.
  `arduino-001`, `sensehat-001`은 물리 source ID이며 aggregate EdgeX Device 이름으로
  가정하지 않는다.
- `EdgeX 등록 디바이스`는 Core Metadata의 `Device`다. 한 물리 source가 기능·resource별
  여러 EdgeX Device로 fan-out될 수 있다.
- `관측 트윈`은 EdgeX Device/Profile과 최신 Event/Reading을 읽기 전용으로 결합한
  대시보드 projection이다. 가상 하드웨어나 simulator가 아니며, desired/reported 제어
  상태를 가진 KubeEdge Device Twin이나 actuator 제어 기능도 아니다.
- `현장 엣지 노드`는 KubeEdge/Kubernetes node와 Prometheus node snapshot으로 관측한다.
  물리 source나 EdgeX Device와 같은 객체로 합치지 않는다.
- 관측 트윈과 AI 서비스는 N:M 관계다. 하나의 트윈을 여러 서비스가 사용할 수 있고,
  하나의 서비스도 여러 트윈을 입력으로 사용할 수 있다.
- 실제 simulator를 명시하는 경우가 아니면 `가상 디바이스`, `가상 자원`, `자원 풀`을
  현재 물리 디바이스 inventory나 관측 트윈의 이름으로 사용하지 않는다.

## 구현 규칙

- 물리 디바이스는 EdgeX Core Metadata의 Device Profile과 Device로 사전 등록한다.
- EdgeX Device Service가 MQTT/Serial/Modbus/OPC-UA/RTSP endpoint의 연결, 표준화, 상태와 지원 command를 독점 관리한다.
- 일반 `edge-device-discovery`는 지정된 모든 edge node에서 USB Serial의 `/dev/serial/by-id/*`를 읽기 전용으로 수동적(passive) 관측한다. dev0003의 별도 I2C Agent만 allowlist bus/address와 read-only chip identity를 확인한다. 발견 후보는 승인 전 임시 정보이며 EdgeX inventory, Device Service 통신 성공 또는 센서 응답 근거가 아니다.
- MQTT/Modbus/OPC-UA/RTSP/REST 네트워크 endpoint는 광역 probe하지 않고 대시보드에서 후보로 직접 선언한다. 후보에는 비밀번호, token, URL userinfo와 임의 image/command/hostPath를 저장하지 않는다.
- 발견 후보의 `accepted`는 검토 상태일 뿐 자동 Device 등록이나 workload 배포가 아니다. exact node/protocol/path가 검증된 Git Adapter Catalog binding과 일치한 후보만 기존 EdgeX 등록 마법사로 넘길 수 있다.
- 발견 후보, 상태 이력, 승인과 등록 Saga는 Adapter Controller의 PVC SQLite에 보관한다. 기존 `edgex-device-discovery-registry` ConfigMap은 최초 기동의 1회 migration 입력일 뿐 권위 저장소가 아니며 최종 Device/Profile/state/Event 권위는 계속 EdgeX다.
- 발견 DaemonSet의 read-only `/dev`, `/sys` host mount는 고정된 수동 관측 agent에만 허용한다. 이 예외를 Device Service workload나 UI 입력형 hostPath로 확장하지 않는다.
- 중앙 EdgeX Core Keeper, Core Metadata, Core Data, Core Command, 내부 MessageBus,
  PostgreSQL과 ingest gateway는 `etri-ser0002-cgnmsb`에 한 세트만 배치한다.
- 중앙 내부 `edgex-messagebus`는 ClusterIP로 분리하며 고정 ClusterIP/PodIP/node IP를 데이터 경로에 사용하지 않는다.
- MQTT broker는 MQTT-only 장비 또는 명시적 local pub/sub가 필요한 노드에만 둔다. Modbus, OPC-UA, Serial, I2C 직접 Device Service에는 MQTT를 요구하지 않는다.
- `edgex-edge`에는 공식 EdgeX Device SDK 기반 `device-serial-jetson`과
  `device-sensehat-raspi`가 배포되어 각각 `etri-dev0001-jetorn`의 Arduino Serial과
  `etri-dev0003-raspi5`의 Sense HAT I2C를 직접 수집한다. 이전 `edgex-edge-agent-*`,
  outbox PVC와 Agent 전용 Metadata bootstrap은 퇴역 상태다.
- 현재 검증된 수직 슬라이스는 `arduino-001` → `device-serial-jetson`과
  `sensehat-001` → `device-sensehat-raspi`다. 세부 EdgeX Device 목록과 resource 계약은
  `docs/프로젝트-범위.md`를 따르며, 중앙 Core Data Event와 dashboard freshness까지 같은
  물리 source identity로 연결한다.
- RTSP frame은 Core Data로 운반하지 않고 승인된 소비 서비스 Pod가 요청 시 직접
  구독한다. 상태·분석 결과 metadata만 EdgeX Event로 전달할 수 있다.
- Device Profile의 read-only command GET은 현재값 조회에 사용한다. write command, actuator mutation, runtime migration/offloading은 별도 승인과 검증 전까지 비활성이다.
- KubeEdge는 엣지 노드와 워크로드 관리에만 사용하며 KubeEdge Device/DeviceModel/DeviceStatus를 물리 디바이스 권위나 병행 plane으로 사용하지 않는다.
- EdgeX 운영 배포의 단일 진입점은 root `edgex/k8s/kustomization.yaml`이며 Argo CD Application `edgex-telemetry`가 동기화한다.
- `edgex/telemetry-plane/`의 edge Agent 코드는 운영 경로가 아니다. 중앙 ingest gateway는 유지되지만 현재 Serial Device Service 데이터 경로에는 참여하지 않는다.
- 운영 namespace는 중앙 `edgex-system`과 물리 노드 Device Service용 `edgex-edge`로 분리한다.
- `mappers/mqttvirtual/`, mapper direct-to-Influx, `command`/`heartbeat` topic은 legacy test/integration 경로이며 fallback이 아니다.
- 대시보드 분류상 물리 디바이스 노드 availability는 Kubernetes/KubeEdge와 Prometheus
  node snapshot으로 판단한다.
- 센서 디바이스 availability는 중앙 EdgeX `adminState`, `operatingState`, Core Data
  최신 Event freshness로 판단하며 Kubernetes node placement를 gate로 사용하지 않는다.


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

사용자·운영자 대상 기술 문서는 필요할 때 `ELI5`(초등학생에게 설명하듯) 요약을 함께 둔다.
요약은 일상 비유와 짧은 문장으로 목표·원인·결과를 먼저 설명하고, 바로 뒤에서 정확한
측정 경계·근거·제한을 연결한다. ELI5 요약은 시험 결과나 운영 범위를 단순화해 과장하는
수단이 아니며, 수치·API·안전 경계를 대체하지 않는다. 시간·원인·임계값의 관계가 핵심인
문서에는 읽기 전용 교육용 인터랙티브 설명을 추가할 수 있으나, 실제 제어·시험 도구처럼
표시하거나 live 상태를 바꾸면 안 된다.

## 산출물 우선순위

즉시 필요한 산출물은 서비스 데모 시나리오, 디바이스 등록/관리 절차, 디바이스-서비스 바인딩 명세, 대시보드 정보 구조, 옥동 시나리오 KPI 정의다.
연차별 정량 목표, 1000 디바이스 실증 계획, 논문/특허/표준 계획은 그 다음이다.

## Semantica 영속 기억

- 중요한 작업을 시작할 때 Semantica 그래프 요약을 확인하고, 현재 작업과 관련된 과거 결정 및 미해결 위험을 조회한 뒤 계획한다.
- 기존 아키텍처, 범위, 제약 또는 인터페이스를 변경하려는 시점에는 관련 선행 결정을 다시 조회해 충돌 여부를 확인한다.
- 중요한 작업의 최종 답변을 작성하기 전에 이번 작업에서 확정된 요구사항, 설계 결정과 근거, 검증 결과, 남은 위험을 Semantica에 기록한다.
- 대화 전문, 임시 추론, 자격 증명, 비밀정보, 개인정보 또는 검증되지 않은 주장은 저장하지 않는다.
- 저장할 영속 정보가 없으면 기록을 만들지 않는다. Semantica를 사용할 수 없으면 기록한 것처럼 말하지 말고 최종 답변에 해당 사실을 알린다.
