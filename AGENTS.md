# AGENTS.md

## 작업 원칙

이 저장소는 KubeEdge node/workload 관리와 EdgeX 물리 디바이스 연동을 결합한 혼합 디바이스 엣지 AI 플랫폼 PoC다.
현재 목표는 복잡한 동적 오케스트레이션을 먼저 완성하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 운영 관점으로 보이게 만드는 것이다.

아래 문서는 해당 주제를 구현·변경·설명할 때 필요한 것만 읽는다. 이미 확인한 동일 상태의 문서는 재사용한다.

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

- 물리 inventory/state/telemetry/command 권위는 EdgeX, KubeEdge는 node/workload 관리다. legacy mapper를 병행 plane이나 fallback으로 쓰지 않는다.
- 광역 network probe·자동 등록·임의 command/hostPath를 추가하지 않는다. write command·actuator·runtime migration/offloading은 별도 승인과 검증 전까지 비활성이다.
- 운영 배포는 `edgex/k8s/kustomization.yaml`과 Argo CD `edgex-telemetry`를 따른다. 발견 후보나 설계 문서를 실제 연동 성공으로 보고하지 않는다.

디바이스·telemetry·배포·상태·연결 복구를 구현·변경·설명하거나 운영을 진단할 때 [.instruction-guides/implementation-policy.md](.instruction-guides/implementation-policy.md)를 읽고 따른다. 같은 작업에서 이미 확인했고 변경되지 않았다면 재사용한다.

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

- 중요한 작업 시작 시 관련 결정·미해결 위험을 조회한다. 같은 범위에서 이미 확인한 내용은 재사용하고, 범위·계약 변경이나 충돌이 생기면 다시 조회한다.
- 종료 전 새로 확정된 요구·결정·근거·검증·남은 위험만 기록한다. 새 영속 정보가 없으면 쓰지 않는다. 작업 방식 개선은 관찰 로그, UI 토큰은 디자인 문서에 두며 전문을 중복 저장하지 않는다.
- 비밀·개인정보·대화 전문·임시 추론·미검증 주장은 저장하지 않는다. 도구를 사용할 수 없으면 로컬 기록을 남기고 그 한계를 알린다.
