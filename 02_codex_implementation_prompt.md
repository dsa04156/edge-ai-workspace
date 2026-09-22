# Codex 개발 지시문 — 가상 디바이스 관리 및 오프로딩 연동

너는 `dsa04156/edge-ai-workspace`의 구현 담당 개발자다. 함께 제공한 `01_virtual_device_design.md`(VD-DESIGN-001 v1.0)를 기준으로 기존 시스템을 확장하라. 계획만 다시 작성하고 끝내지 말고, 저장소 조사 후 로컬 코드, 테스트, 개발 문서까지 구현하라. 운영 배포와 실제 장비 시험은 별도 승인 범위다.

## 1. 목표

기존 EdgeX와 Runtime Operator 사이를 연결하여 서버측 AI 실행환경을 가상 디바이스 단위로 등록하고, 물리 대상, 서비스, 실제 실행체, 자원, 상태 및 제어 이력을 추적한다.

실행체는 일반 Pod다. 새 이름, CRD 또는 상태 API를 만들었다고 하드웨어 가상화나 가속기 에뮬레이션을 구현한 것으로 설명하지 마라. 가상 AI 가속기 에뮬레이션은 설계서 12절의 별도 작업 범위와 완료 기준을 유지하라.

2차년도 규모 목표는 **물리+가상 디바이스 100개 관리**다. **100개 Pod의 상시 실행이나 동시 추론을 필수 조건으로 추가하지 마라.** 반대로 등록 ID 100개만으로 공식 목표 달성을 선언하지 마라. 등록, 바인딩, 관측, 제어 검증, 실제 실행 수를 분리하라.

## 2. 작업 시작

1. 저장소와 하위 경로의 `AGENTS.md`, `docs/프로젝트-범위.md`, `docs/저장소-구조.md`, `docs/현재-구현-상태.md` 및 공통 서비스 오케스트레이션 문서를 읽어라.
2. 현재 branch, HEAD, dirty files와 사용 가능한 테스트 명령을 기록하라. 설계서 확인 기준은 `2926ac7ae21bd72c7d70f57f09e7109e2c124086`이지만 해당 커밋으로 reset/checkout하여 현재 작업을 덮어쓰지 마라.
3. 실제 구현과 문서의 차이를 기록하라. `edge-orch/virtual-device-runtime/`은 기준 커밋 조회에서 404였다. 로컬이나 알려진 작업 브랜치에 소스가 있는지 확인하고, 없으면 기존 코드가 있다고 가정하지 마라.
4. 현재 물리 EdgeX 경로, 관측 트윈, `vd-demo-001`, RuntimeService/Operator/gateway의 책임과 실행 소유자를 확인하라.
5. 신규 개발 범위와 기존 기능 보존 조건을 범위 문서에 명시하라. 기존 운영 성공 기록이나 측정 수치를 수정하지 마라.

사소한 경로 차이와 구현 선택은 설계서의 책임 경계에 맞춰 결정하고 기록하라. 필요한 외부 접근/운영 승인 문제만 차단 항목으로 남기고, 독립적인 로컬 개발은 계속하라.

## 3. 변경할 구조

```text
등록: NEXUS → Facade → 승인 Catalog 검증 → EdgeX Device/Profile 등록
제어: NEXUS → Facade → Core Command → 공통 Virtual Device Service → 기존 Operator
관측: EdgeX + Kubernetes + Operator → Aggregator/가상 관측 트윈 → NEXUS
AI 요청: 기존 runtime-gateway → Jetson 또는 서버 AI 실행체
```

- 전용 EdgeX Device/Profile과 여러 VD를 담당하는 공통 Virtual Device Service를 구현하라. VD마다 Agent/EdgeCore/EdgeX Core를 만들지 마라.
- 새 `VirtualDevice CRD`, KubeVirt, 별도 오프로딩 제어기를 이번 범위에 추가하지 마라.
- 기존 Runtime Operator가 Pod 생성, 준비 확인, 요청 전환, drain 및 반환을 유일하게 담당하도록 하라. Facade/DS는 Pod를 직접 조작하지 않는다.
- 첫 버전의 연결은 `VD 1개 ↔ RuntimeService UID 1개의 서버 슬롯 1개`다. 같은 서버 슬롯을 여러 ID로 중복 등록하지 마라. 로컬/서버 전환마다 새 RuntimeService를 만들지 마라.
- EdgeNode와 PhysicalSource를 구분하라. Node 이름을 EdgeX Device 이름으로 취급하지 마라. UID와 bindingGeneration으로 재생성과 stale 명령을 검출하라.
- 기존 v1 Registry 및 `vd-demo-001` 제어는 호환 유지하라. 새 모델은 명시적 v2로 추가하고, 같은 workload가 두 제어기의 대상이 되지 않도록 하라.

## 4. 구현 순서

### M0: 기준선 및 계약

기존 테스트를 가능한 범위에서 먼저 실행하고 결과를 저장하라. 기존 실패와 신규 실패를 구분하라. `virtual_resource_registry.py`, `virtual_device_control.py`, `virtual_resources.py`, `device_twins.py`, `runtime_operator/contract.py`, `controller.py`, `api.py`, `journal.py`를 확인하라.

### M1: 등록과 바인딩

승인된 Catalog ref/revision만 받는 등록 workflow, v2 schema, 영속 작업 원장과 중복 claim 검사를 구현하라. EdgeX 실제 등록 readback과 RuntimeService 바인딩까지 확인하라. 부분 실패는 단계별 상태로 남기고 같은 operation ID로 복구하라. 임의 이미지/command/hostPath/URL을 허용하지 마라.

등록된 VD의 정의와 실행체를 분리하라. 등록만으로 AI Pod/GPU를 선점하지 않는다. 대량 시험용 새 RuntimeService를 생성하면 기본 `spec.suspended: true`로 두어 로컬 Pod까지 자동 기동되지 않게 하라. 일부 실행 시험에서만 서비스 재개를 명시적으로 수행하고 VD activate로 suspended를 우회하지 마라. 프로파일은 공유할 수 있지만 실행 결과와 사용량은 VD별로 관측한다.

### M2: 기존 Operator 확장

선택적 VD 바인딩과 다음 목표 모드를 추가하라. 계약 모델, CRD schema 생성기, 상태 모델, API 및 tests를 함께 변경하라. 새 필드가 없는 RuntimeService는 기존 동작을 유지해야 한다.

- `activate → hold`: 서버를 준비하고 새 요청을 서버로 전환하여 유지한다. 단순 prewarm으로 구현하지 않는다.
- `setAutomatic → automatic`: 기존 오프로딩 정책으로 복귀한다.
- `disable → disabled`: 서버 사용을 막는다. 현재 서버가 처리 중이면 안전한 로컬 복귀, drain, 반환 뒤 완료한다.

**`disable`을 `RuntimeService.suspended=true`로 구현하지 마라.** 서비스 전체 중지와 VD 중지를 구분하라. 로컬 후보가 없거나 준비에 실패하면 BLOCKED로 남기고 기존 서버 서비스는 유지한다. 서비스가 suspended이면 activate가 임의로 재개하지 않는다.

같은 service UID의 관리 작업을 직렬화하라. 전달 후 결과가 불명인 AI 요청은 UNKNOWN으로 보존하고 다른 worker로 자동 재전송하지 마라. 일반 Pod 반환과 resident 모델 해제/예약 유지의 차이를 실제 상태로 표시하라.

### M3: EdgeX Device Service

기존 저장소의 EdgeX SDK 및 버전 패턴을 재사용하라. `edgex/device-virtual-runtime/`는 신규 경로 제안이며 현재 구조에 맞춰 책임을 유지하면서 배치하라.

Device는 등록 대상, Profile은 상태/명령 계약, DS는 Operator 연결을 담당한다. SDK가 지원하지 않는 최상위 필드나 운영 상태 enum을 임의로 쓰지 마라. 실행 상태와 EdgeX admin/operating 상태를 구분하라.

Core Command를 통과해도 operation ID와 bindingGeneration이 유지되는 제한된 command envelope를 구현하고 왕복 시험하라. header 자동 전달을 가정하지 마라. 신규 Operator 관리 API에는 서비스 간 인증을 추가하고, 고정 데모 권한을 범용 제어 권한으로 확대하지 마라. 다른 VD의 작업 조회와 명령을 차단하라.

### M4: 관측과 NEXUS

기존 물리 트윈 API를 깨지 말고 가상 실행환경용 모델을 추가하라. `physical_device_id`에 가상 ID를 넣지 마라. 등록/연결, 실행, 관측 신선도를 별도 축으로 표현하라.

목록/상세/작업조회 API와 기존 화면을 확장하라. 실제 서버 Pod, RuntimeService UID, 연결 물리 대상, 프로파일, 적용 자원, 사용량, 반환 상태, 요청 결과와 원본 시각을 보여라. 관측 실패를 정지 또는 정상으로 표시하지 마라.

Kubernetes 객체 일괄 조회, 제한된 병렬 worker 조회, cache coalescing과 pagination을 구현하라. 100개를 브라우저마다 순차 조회하지 마라. 실패한 reader의 과거 수치를 최신 정확한 합계로 쓰지 마라.

### M5: 검증 도구와 개발 문서

승인된 Catalog를 1/10/30/60/100 규모로 생성하는 도구, 제한된 실행 동시성의 기능 검증 도구, 증거 수집과 소유권 제한 정리 도구를 구현하라. 기본은 파일 생성/로컬 시험이며 자동 클러스터 apply는 하지 않는다.

원본 runtime 소스가 없으면 기존 공통 HTTP 실행 계약에 맞는 명시적 CPU test fixture를 만들 수 있다. 이를 기존 Iris 소스 복원본, 실공장 모델 또는 가속기 에뮬레이터라고 주장하지 마라.

`real`, `test-fixture`, `emulated` 구분을 유지하라. 승인된 에뮬레이션 명세가 없으면 `emulated`는 비활성화하고 별도 명세/검증 항목으로 남겨라. fixture의 인위적인 지연을 실제 Jetson/GPU의 성능이라고 기록하지 마라.

## 5. 필수 안전 및 호환성 조건

- 기존 Serial/I2C 수집, EdgeX 물리 inventory, 센서 freshness와 서비스 데이터 경로를 보존한다.
- 퇴역 mapper/custom agent 경로를 새로운 기본 경로로 복원하지 않는다.
- AI 원본 데이터는 EdgeX Metadata/트윈으로 중계하지 않는다. 기존 `/services/{name}/invoke`와 응답 body를 보존한다. VD 실행 증거는 header 또는 원장에 추가한다.
- 모델/이미지/아키텍처/입력/동시성 조건이 맞는 프로파일만 재사용한다. 100개 등록은 프로파일 100개를 새로 측정하라는 뜻이 아니다.
- GPU/NPU 공유, PVC 및 CSI 기능은 실제 지원 확인 전까지 미지원/미검증으로 둔다. 임의 PVC 축소나 데이터 삭제를 하지 않는다.
- 새 관리 endpoint는 내부망이라는 이유만으로 무인증으로 열지 않는다. secret을 Git, Metadata, 로그에 기록하지 않는다.
- GitOps 정적 정의와 Operator 동적 필드의 쓰기 책임을 분리하고 충돌 시험을 만든다. 광역 diff 무시나 포괄적 관리자 권한을 주지 않는다.
- 기존 사용자 변경은 보존한다. 강제 reset, 운영 context 변경, live apply/delete, 이미지 push/배포, 실제 부하/장애 주입, 파괴적 정리는 별도 승인 전 수행하지 않는다.

## 6. 완료 기준

설계서 T01~T24를 요구사항-테스트 표로 추적하라. 최소한 다음을 확인해야 한다.

1. v1 호환과 v2 schema, 중복 ID/슬롯, UID 재생성, 등록 부분 실패 및 재조정.
2. 인증, 범위 검사, 동일 operation ID 중복, payload 충돌, EdgeX envelope 왕복.
3. activate, 자동 복귀, 안전한 disable, 로컬 실패 시 서버 유지, suspended 우회 금지.
4. 요청 결과 불명, 제어기 재시작, drain, 일반/resident 자원 반환 구분.
5. 물리 트윈 보존, stale/부분 실패 표시, 동일 backend/트윈/Pod 중복 산정 차단.
6. 100개 관리 모델과 별도의 소규모 실제 병렬 실행을 구분한 검증 도구.

로컬 unit/contract tests 통과를 실클러스터 성공으로 표시하지 마라. 정지 VD의 공식 지표 포함 여부가 미확정이면 `N_qualified`를 미정으로 두고 `N_registered/N_bound/N_observable/N_controllable/N_running`을 따로 제공하라.

## 7. 작업 종료 시 제출

변경 파일 목록, 핵심 계약 및 데이터 흐름, 실제 실행한 명령과 테스트 결과, 기준선 실패와 신규 실패, 미실행/차단 항목, 로컬 재현 방법, 승인 후 배포 및 롤백 절차를 작성하라. 실제 증거가 없는 성능 수치나 통과 결과를 만들지 마라.

최종 결과를 다음 셋으로 구분하라.

- 구현 및 로컬 검증 완료.
- 실클러스터 승인이 필요하여 미실행.
- 에뮬레이션 명세 또는 공식 평가조건 확정이 필요한 별도 항목.

위 범위 안에서 실제 개발을 진행하라. 개념 설명이나 새 아키텍처 제안만 반복하지 마라.
