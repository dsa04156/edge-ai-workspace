# AGENTS.md

## 작업 원칙

이 저장소는 KubeEdge node/workload 관리와 EdgeX 물리 디바이스 연동을 결합한 혼합 디바이스 엣지 AI 플랫폼 PoC다.
현재 목표는 복잡한 동적 오케스트레이션을 먼저 완성하는 것이 아니라, 디바이스와 서비스를 실제로 연결하고 이를 대시보드에서 운영 관점으로 보이게 만드는 것이다.

아래 문서는 해당 주제를 구현·변경·설명할 때 필요한 것만 읽는다. 이미 확인한 동일 상태의 문서는 재사용한다.

- `docs/현재-구현-상태.md`: 최신 개발 체크포인트, 배포·검증 근거와 다음 작업
- `docs/프로젝트-범위.md`: 현재 구현, 후속 설계와 명시적 제외 범위의 최상위 기준
- `docs/저장소-구조.md`: 현재 구현 경로, 배포 소유권과 legacy 경계
- `docs/프로젝트-배경.md`: 과제 배경, 현재 목표, PoC 방향
- `docs/물리-디바이스-상태-정책.md`: EdgeX 물리 디바이스 상태와 telemetry 정책
- `docs/대시보드-판단-정책.md`: 대시보드 상태 판단 기준
- `docs/서버측-가상-디바이스-통합-설계.md`: 서버 실행환경 VD의 후속 설계·구현 지침과 과거 구현 경계
- `docs/단계별-추진계획.md`: 2026년도 2차년도 옥동 PoC 목표, 일정, 기관별 역할과 산출물

## 사용자 확정 개발 순서 (2026-09-30)

전체 개발은 아래 순서를 따른다. 상세 책임과 인수 기준은
[1세부 개발범위와 우선순위](docs/1세부-개발범위와-우선순위.md)를 원본으로 사용한다.

1. Device / Service Profile 정의
2. Device Manager
3. Workflow 실행 구조
4. Device Scheduler
5. Offloading Controller
6. Edge AI Server 연계 API
7. Virtual Device
8. Multi-Device Orchestration
9. 대규모 Workload 실행
10. 복구 / 고가용성 / 운영

- `Profile → Manager → Scheduler → Offloading API`는 초기 핵심 기능의 요약이며 위 순서를 대체하지 않는다.
- 1세부는 디바이스 선택·서버 자원 요청·결과 기반 실행/재배치를 담당한다. 서버 내부 GPU/NPU
  스케줄러는 세부2 등 연계 대상의 책임이며 자체 구현을 선행조건으로 두지 않는다.
- 새 저장소를 만들지 않고 현재 저장소의 `profile-spec/`를 독립 개발 영역으로 사용한다.
  기존 수집·관측·Runtime Operator·대시보드를 재사용하며 Schema와 읽기 전용 연결부터 진행한다.
- Profile은 장비명 `compatibleDevices` 나열 대신 Capability 조건으로 정의한다. 정적 Profile과
  RuntimeState, Profile과 실제 인스턴스를 분리하고 기존 실행·성능 검증 근거를 유지한다.
- 다음 산출물은 DeviceProfile·ServiceProfile·VirtualDeviceProfile·RuntimeState의 네 가지
  v1 Schema 초안·예제·검증·기존 필드 대응표다. DB·REST API·새 실행 제어기부터 만들지 않는다.
  VD 설계 M0~M6는 7단계의 세부 참고로 두며 전체 개발의 시작점으로 삼지 않는다.
- 아래 9월 15일 범위와 검증 근거는 기존 기반이다. 이 순서 기록을 신규 구현·실장비 시험·배포
  완료로 해석하지 않고, 9월 28일 철회한 VD·수동 Workflow 프로토타입도 자동 재개하지 않는다.

## 기존 개발 기반과 승인된 실행 범위 (2026-09-15)

과제의 현장 우선순위는 아래에 유지한다. 현재 사용자가 진행 중인 개발은 **AI 서비스별 목록·상태·
실행 위치·시험 부하·후보 판단·이동·복귀를 하나의 운영 화면으로 연결하고, 모델과 장비 종류를
확장하는 것**이다. Llama나 Nano→Orin→Spark 순서를 모든 서비스의 고정 구조로 만들지 않는다.

- 현재 실행 경로는 `edge-orch/runtime-operator/`의 RuntimeService·gateway·배치 제어기와
  `edge-orch/state-aggregator/`의 OFFLOAD DEMO다. 등록 계약 안에서 실행·중지·준비 후 경로
  전환·기존 요청 정리·정책별 복귀를 수행한다. 이는 서비스 설계 dry-run과 별개다.
- Llama는 기존 resident worker를 사용하며 현재 승인 없는 자동 증강·복귀 정책이다.
  승인 모드는 서비스별 옵션이다. 정책 활성과 현재 서비스 실행 여부는 구분한다.
- `digits-classifier`는 학습된 실제 이미지 분류 모델을 공통 JSON 텐서 adapter로 연결한
  첫 비 Llama 실행 검증이다. ARM64 Raspberry Pi와 x86 서버 사이의 **정책 지정 전환**을
  검증했다. 새 `modelRuntime`는 성능 자격 측정 전 `preferred`만 허용하며 부하 기반 자동
  증강·복귀는 미활성이다. 이를 전체 AI 범용화나 현장 모델 실증 완료로 설명하지 않는다.
- 기존 AI가 목록에 보이더라도 공통 실행 계약에 미연결이면 제어 가능·자동 이동 가능으로
  표시하지 않는다. HTTP 합성 시험 서비스와 실제 AI도 구분한다.
- 다음 범위는 서비스별 노드 실행·성능 자격, 과부하 이동·저부하 복귀, 다중 서비스 자원
  경쟁 검증이다. 미측정 성능을 추정해 자동 정책을 활성화하지 않는다.
- 상세 상태·검증·후속 설계는 [현재 구현 상태](docs/현재-구현-상태.md)와
  [전체 AI 서비스 자동 배치 설계안](docs/전체-AI-서비스-자동-배치-설계안.md)을 따른다.

## 사용자 확정 운영·작업 방식

- 2026-09-30 사용자 요청으로 Llama·숫자 분류·합성 runtime 서비스, 센서 anomaly·모빌인트·VD
  데모와 Modbus fixture의 운영 실행·접속 리소스를 정리했다. 기존 실행·시험 소스는 보존 근거이며
  상시 운영으로 설명하거나 자동 재배포하지 않는다. EdgeX 수집·노드 관리·Runtime Operator·
  대시보드·드라이버·PVC는 유지한다. 현재 상태와 복구 범위는 `docs/현재-구현-상태.md`를 따른다.
- 새 브랜치나 worktree를 임의 생성하지 않고 현재 브랜치에서 작업한다. 기존 미커밋 변경을
  보존하고 이번 작업의 변경과 구분한다. 배포된 파일·커밋된 코드·로컬 변경을 동일시하지 않는다.
- AI 시험 부하는 사용자가 현재 실행 노드의 버튼으로 시작·제거한다. 부하는 선택 서비스에
  실제 추론 요청을 반복하는 것이며 장비 전체 CPU/GPU 스트레스와 구분한다.
- 이동 후 같은 서비스 UID/run ID의 부하는 새 요청 경로를 따라 유지한다. **제거 버튼의
  소유권은 처음 시작한 노드에 유지**한다. 부하 제거는 반복 요청만 멈추고 서비스는 유지하며,
  서비스 중지는 부하 종료·진행 요청 정리·실행 자원 정리를 수행한다.
- 별도 시험 실행 요청 없이 반복 부하를 임의 생성하거나, 다음 노드에 새 시험을 자동 시작하지
  않는다. 제어기 재시작으로 중단된 시험도 자동 재실행하지 않는다.
- 설명은 사용자가 화면에서 무엇을 누르면 무엇이 바뀌는지 먼저 알려준다. 구현·검증·미구현을
  구분하고, API·모델 계약·이미지 digest 등 세부사항은 근거로 덧붙인다.

## 과제의 현장 우선순위

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

- 2026-09-22 사용자 채택 후속 설계는 [서버측 가상 디바이스 통합 설계](docs/서버측-가상-디바이스-통합-설계.md)다.
  루트 01·02 문서는 보존한 입력이며 최신 수정은 통합 문서에 모은다. 이번 요청은 문서 통합이며
  부록의 개발 명령을 신규 코드 변경·실장비 시험·운영 배포 승인으로 해석하지 않는다.
- 가상 디바이스는 서비스의 서버측 실행환경을 등록·관리하는 객체다. 전용 EdgeX Device/Profile이
  등록 원본이며 `VD 1개 ↔ RuntimeService UID 1개의 서버 실행 슬롯 1개`로 연결한다.
  등록만으로 자원을 선점하지 않고 일반 Pod·서비스 템플릿·후보 수를 VD로 자동 집계하지 않는다.
- 공통 Virtual Device Service는 명령 전달을 담당하고 기존 Runtime Operator만 실행체 생성·준비·
  요청 전환·drain·반환을 수행한다. 트윈은 읽기 전용 관측이다. AI 데이터는 기존 gateway 경로를 유지한다.
- `activate`는 서버 전환·유지, `setAutomatic`은 기존 정책 복귀, `disable`은 안전한 로컬 복귀 후
  서버 반환이다. 서비스 전체 suspend와 구분하며 로컬 복귀가 불가능하면 BLOCKED로 서버 처리를 유지한다.
  같은 서버 슬롯의 중복 등록, 새 VirtualDevice CRD, 하드웨어·가속기 에뮬레이션 완료 주장은 허용하지 않는다.
- 혼합100개는 관리 규모 목표다. 등록/바인딩/관측/제어/실행/공식 자격을 분리하고 100개 Pod 상시
  실행으로 바꾸지 않는다. 센서 목록은 EdgeX Device별 행을 유지하되 기능 수를 물리 장비 수로 합산하지 않는다.
  Node·source·기능 endpoint의 산정 단위와 정지 VD의 공식 포함은 평가조건 확정이 필요하다.
- 9월15일 SQLite 독립 논리 등록부·통합 화면 확장은 9월16일 철회된 이력이다.
  `docs/서비스형-가상-디바이스-설계.md`와 `docs/물리-가상-디바이스-통합-화면.md`의 소스·시험·정의는
  보존하며 새 EdgeX/서버 슬롯 계약의 현재 구현이나 재배포 승인으로 취급하지 않는다.
  기존 물리 관리·독립 시험·일반 워크로드는 보존하고 원천 실패를 정상 정지로 표시하지 않는다.
  상주 Llama 계약의 복제·모델 교체는 별도 계약이 필요하며 코드 변경 승인은 운영 배포 승인이 아니다.

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

## 노드 후보와 성능의 의미

- 클러스터에 등록된 전체 노드, 서비스가 현재 실행되는 노드, 서비스별 실행 검증 노드,
  서비스별 성능 검증 노드를 구분한다.
- `verifiedNodes`는 해당 모델·실행 형태의 실행을 확인한 목록이다. 처리량이나 자동 이동
  자격을 뜻하지 않는다. 숫자 분류의 두 노드는 첫 ARM64/x86 검증 대상이며 다른 장비가
  실행 불가능하다는 뜻이나 시스템 전체 노드 목록이 아니다.
- 화면은 전체 노드 관측과 서비스별 후보 판단을 연결하는 방향으로 확장한다. `실행 중`,
  `실행 가능`, `검증 필요`, `실행 불가/사유`를 근거에 따라 구분하고, 이 표현 개선이 실제 UI에
  모두 반영됐다고 앞서 설명하지 않는다. 미검증은 불가능과 다르며 실행 검증은 성능 검증과 다르다.
- Kubernetes 예약 차감 자원, Prometheus 실제 CPU·메모리·GPU·온도, 서비스별 처리율·지연을
  구분한다. 미수집·오래된 지표를 0 또는 정상으로 표시하지 않는다.

## 구현 규칙

- 물리 inventory/state/telemetry/command 권위는 EdgeX, KubeEdge는 node/workload 관리다. legacy mapper를 병행 plane이나 fallback으로 쓰지 않는다.
- 광역 network probe·자동 등록·임의 command/hostPath를 추가하지 않는다. 물리 write command·actuator와 미승인 runtime migration/offloading은 비활성이다. 승인된 RuntimeService 실행 범위는 위 절과 프로젝트 범위 문서를 따른다.
- EdgeX 운영 배포는 `edgex/k8s/kustomization.yaml`과 Argo CD `edgex-telemetry`를 따른다. 공통 실행 제어기는 `edge-orch/runtime-operator/k8s/`·`platform-runtime`, 대시보드는 Argo CD `edge-orch-state-aggregator`가 소유한다. 발견 후보나 설계 문서를 실제 연동 성공으로 보고하지 않는다.

디바이스·telemetry·배포·상태·연결 복구를 구현·변경·설명하거나 운영을 진단할 때 [.instruction-guides/implementation-policy.md](.instruction-guides/implementation-policy.md)를 읽고 따른다. 같은 작업에서 이미 확인했고 변경되지 않았다면 재사용한다.

## Legacy / Archive Boundary

아래 경로와 주제는 현재 PoC 구현 경로가 아니라 과거 실험, 참조, 보관 자료로 본다.

- `edge-orch/workflow_executor/`: 과거 workflow 실행/orchestration 실험
- `edge-orch/workflow_reporter/`: 과거 stage event reporting 실험
- `edge-orch/placement_engine/`: 과거 placement/offloading/replanning 실험
- `workflow/`: 과거 workflow/event/scenario manifest
- `docs/archive/*`: 과거 통합 기록, 연구 초안, legacy orchestration 자료
- 위 경로의 legacy orchestration, dynamic offloading, runtime replanning 실험과 미승격 agent-assisted planning 자료. 현재 승인된 `runtime-operator/`는 이 legacy 경계에 포함하지 않는다.

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

## 개발 상황 기록과 인수인계

- [현재 구현 상태](docs/현재-구현-상태.md)를 개발 진행의 첫 진입점으로 사용한다. 사용자의
  추가 요청 없이 작업 중 주기적으로 최신화한다. 과거 날짜의 장비 상태를 현재 상태로 재사용하지 않는다.
- 갱신 시점은 의미 있는 구현 단계 완료, 검증 결과 확정, 배포·롤백, 요구·설계·우선순위 변경,
  작업 종료 또는 인수인계 직전이다. 긴 작업은 진행 중 약 30분마다 기록 갱신 필요 여부를
  확인한다. 세션 밖의 예약 작업이 아니라 현재 진행 중인 작업의 체크포인트 규칙이다.
- 기록에는 확인 날짜·현재 목표·완료/진행/보류·검증 근거·커밋/배포 여부·남은 문제·다음 작업을
  적는다. 진행 중에는 미완료를 그대로 표시하고 추정·계획을 완료로 바꾸지 않는다.
- 작업 방식·승인된 범위·책임 경계가 바뀌면 관련 AGENTS.md를 함께 갱신한다. 현재 정책 문서와
  설계안은 해당 계약이 달라졌을 때 수정한다. 새로 확인된 내용이 없는 단순 조회·설명은
  날짜만 바꾸거나 중복 기록을 추가하지 않는다.
- 수정한 공개 문서의 HTML·검색 색인은 기존 생성기로 필요한 범위를 갱신한다. 소스 수정,
  로컬 생성, Git 반영, 실제 웹 배포를 구분하며 자동 기록 규칙을 추가 배포 권한으로 해석하지 않는다.
- [전체 AI 서비스 자동 배치 설계안](docs/전체-AI-서비스-자동-배치-설계안.md)은 목표·단계·인수
  기준을 담는다. 상세 시험·응답·이미지 근거는 `edge-orch/runtime-operator/results/<날짜-주제>/`
  에 보관한다. 최근 실행 근거는 [범용 모델 연결 검증](edge-orch/runtime-operator/results/2026-09-15-generic-model/README.md)이다.
- AGENTS.md에는 지속 적용할 작업 규칙과 현재 범위 경계를 두며 일일 로그·전체 시험 결과를
  복제하지 않는다. Semantica에는 결정·이유·미해결 과제와 원본 근거의 위치를 저장한다.

## Semantica 영속 기억

- 중요한 작업 시작 시 관련 결정·미해결 위험을 조회한다. 같은 범위에서 이미 확인한 내용은 재사용하고, 범위·계약 변경이나 충돌이 생기면 다시 조회한다.
- 종료 전 새로 확정된 요구·결정·근거·검증·남은 위험만 기록한다. 새 영속 정보가 없으면 쓰지 않는다. 작업 방식 개선은 관찰 로그, UI 토큰은 디자인 문서에 두며 전문을 중복 저장하지 않는다.
- 비밀·개인정보·대화 전문·임시 추론·미검증 주장은 저장하지 않는다. 도구를 사용할 수 없으면 로컬 기록을 남기고 그 한계를 알린다.
