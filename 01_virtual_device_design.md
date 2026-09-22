# 혼합 디바이스 관리 및 서버측 가상 실행환경 설계서

> 문서 ID: VD-DESIGN-001  
> 버전: 1.0 / 작성일: 2026-09-18  
> 상태: 개발 기준안. 운영 배포 및 공식 평가조건 승인 전.  
> 적용 저장소: `dsa04156/edge-ai-workspace`  
> 확인 기준: `main` / `2926ac7ae21bd72c7d70f57f09e7109e2c124086`  
> 개발 지시문: 같은 폴더의 `02_codex_implementation_prompt.md`

## 0. 한 페이지 요약

### 무엇을 만드는가

Jetson에서 실행 중인 AI 서비스가 서버에서 실행될 때, 그 **서버측 실행환경을 하나의 가상 디바이스로 등록하고 실제 실행체, 자원, 이용 서비스, 상태 및 제어 이력을 연결하는 기능**을 만든다.

실제 실행체는 기존 Kubernetes Pod다. Pod와 다른 가상화 기술을 새로 발명한다는 뜻이 아니다. 이 문서에서 가상 디바이스는 **과제용 관리 단위**이며, 이 관리 단위만 추가해서 하드웨어 에뮬레이션까지 구현했다고 주장하지 않는다.

```text
물리 Jetson                           엣지 AI 서버
┌──────────────────┐                 ┌───────────────────────────┐
│ 기존 AI 서비스 Pod│ -- 요청 전환 --> │ 서버측 AI 서비스 Pod       │
└──────────────────┘                 │   └─ vd-001과 실행 관계 연결│
          │                          └───────────────────────────┘
          └──────── 기존 Runtime Operator가 양쪽 실행을 제어 ─────┘

NEXUS의 통합 관리 화면
  물리 노드 / 물리 센서 / 가상 디바이스를 구분하여 표시
  각각의 원본 정보와 관측 트윈을 연결
  등록, 실제 실행, 자원 할당, 사용량, 제어 결과를 분리
```

### 이번 설계에서 고정할 결정

| 항목 | 결정 |
|---|---|
| 실행 기술 | 기존 Kubernetes/KubeEdge, Deployment/Pod, 기존 Runtime Operator 재사용 |
| 가상 디바이스 등록 | 전용 EdgeX Device/Profile 및 Virtual Device Service 추가 |
| 실행 제어 | Runtime Operator만 해당 실행체를 생성, 전환, 정리 |
| 트윈 | 원본 상태를 결합하는 관측 모델. AI 실행체가 아니며 제어의 원본 저장소도 아님 |
| 새 VirtualDevice CRD | 이번 버전에는 추가하지 않음. 기존 RuntimeService의 선택적 확장 사용 |
| KVM/KubeVirt/가상 EdgeCore | 이번 개발 범위에 추가하지 않음. 계획서가 이 기술들을 금지한다는 뜻은 아님 |
| 100개 | 물리와 가상 관리 대상의 규모. 100개 Pod 상시 실행으로 바꾸지 않음 |
| 실장비 에뮬레이션 | 별도 명세와 검증 항목. 관리 기능과 오프로딩 완료로 대체하지 않음 |

### 첫 번째 완료 장면

`vd-001`을 EdgeX에 등록한다. 실제 Jetson의 서비스가 서버로 전환되면 `vd-001`의 실행 상태, 서버 Pod, 실제 자원 및 처리 요청이 함께 표시된다. 로컬로 복귀하면 서버 자원 반환을 확인한다. 서버 실행체가 없어져도 등록 정보와 실행 이력은 남는다. **일련의 과정에서 기존 센서 수집과 서비스 API는 유지된다.**

---

## 1. 근거, 용어 및 범위

### 1.1 근거 수준

이 문서는 다음을 구분한다.

- **[계획서]** 연구개발계획서의 실제 항목과 표현.
- **[현재 코드]** 위 기준 커밋에서 확인한 내용. 현재 클러스터에서의 실행 성공을 뜻하지 않는다.
- **[설계]** 이번 개발을 위해 선택한 구현 방식과 API. 기존 코드에 이미 있는 기능으로 취급하지 않는다.
- **[승인 필요]** 공식 시험 산정 또는 에뮬레이션 범위처럼 문서만으로 확정할 수 없는 부분.

`100개 관리`는 사용자가 지정한 2차년도 목표로 채택한다. 확인한 계획서 본문 169쪽의 성능표는 단계 최종 목표 `1,000개`를 기재한다. 이 표를 2차년도 `100개`의 직접 근거로 인용하지 않는다. 본 설계에서는 사용자의 연차 목표와 계획서의 지표 정의를 함께 적용한다. [U1][P1]

### 1.2 계획서 요구사항 추적

| 요구 ID | 항목 / 담당 범위 | 계획서 내용 | 설계 대응 / 완료 주장 경계 |
|---|---|---|---|
| REQ-01 | 2차년도 2-1 / ETRI | 배치, 이동, 오프로딩, 부하 경감 및 자동복구 | 기존 Operator를 가상 디바이스와 연계. 임의 서비스 전체의 무중단 복구까지 주장하지 않음 |
| REQ-02 | 2차년도 2-3 / ETRI | 등록, 탐색, 메타데이터, 개방형 API | 전용 EdgeX Device Service, 등록 및 관측 API |
| REQ-03 | 2차년도 3-1 / ETRI | 가상 AI 가속기 에뮬레이션 엔진 | 별도 에뮬레이션 명세와 검증을 요구. 본 관리 연동만으로 완료하지 않음 |
| REQ-04 | 2차년도 3-1 / ETRI | 물리/가상 동시 실행 및 다중 가상 디바이스 병렬 실행 | 일부 가상 디바이스의 실제 병렬 기능 실행 시험 |
| REQ-05 | 2차년도 3-2 / KPST | 컨테이너 단위 가상 디바이스 및 통신 인터페이스 | 컨테이너 실행과 EdgeX 연동. 기관 간 인터페이스 협의 필요 |
| REQ-06 | 2차년도 3-3 / ETRI, KPST | 자원 가상화 인터페이스와 자원 활용 최소/최대 프로파일 | 프로파일 연결, 지원되는 자원 할당 및 관측 |
| REQ-07 | 2차년도 3-4 / KPST | 상태 기반 스케줄링 및 분산/병렬 실행 | 기존 Operator 상태와 실행 관계 연결 |
| REQ-08 | 2차년도 위탁 2-1 / 경북대 | 물리 디바이스와 매핑되는 가상 디바이스 생성/배포 및 스토리지 증강 | 매핑 계약, 저장소 확장 지점. 동적 볼륨 증강/축소는 별도 검증 |
| REQ-09 | 성능지표 / 단일노드 | 단일 노드에 배포된 트윈 엔진이 관리 가능한 물리/가상 디바이스 수 | 100개 규모 관리 시험 및 산정 근거 원장 |

근거: 계획서 본문 36, 53~58, 169쪽. 1차년도 본문 45쪽에는 API 추상화와 I/O, 연산, 통신 시뮬레이션 설계가 포함된다. 이를 특정 Jetson 전체 또는 CUDA API 전체의 에뮬레이션 명세로 확대하지 않는다. [P1]

### 1.3 용어

| 용어 | 이 문서에서의 의미 |
|---|---|
| 물리 센서/source | Arduino, Sense HAT, PLC, 카메라 및 실제 연결 endpoint |
| 물리 컴퓨팅 노드 | Jetson, Raspberry Pi, 서버 등 실제 워크로드 실행 장비 |
| EdgeX Device | 등록 및 장치 인터페이스 관리 객체. 물리 장비와 항상 1:1은 아님 |
| 가상 디바이스 / VD | 서버측 실행환경을 디바이스 단위로 등록하고 연결 및 제어하는 본 설계의 논리 객체 |
| RuntimeService | 서비스의 실행 계약과 배치 및 전환 정책을 관리하는 기존 사용자 정의 리소스 |
| 서버 실행 슬롯 | RuntimeService의 서버측 실행 대상에 대응하는 논리 구획. Kubernetes 기본 객체가 아니며 자원 선예약을 뜻하지 않음 |
| Runtime | 현재 실제 실행체. 일반 모드는 Deployment/Pod, resident 모드는 명시적으로 인계받은 기존 worker |
| Device Twin | 장치 원본 정보와 실제 상태를 결합한 관측 모델 |
| 오프로딩 | 서비스의 작업 처리 위치를 변경하는 동작. 이번에는 새 요청의 경로 전환이 기본 |

**분명히 제외할 설명:** VD가 생겼다고 Jetson의 `nvidia-smi`에 서버 GPU가 나타나는 것은 아니다. 서버 RAM이 Jetson의 로컬 RAM으로 붙지도 않는다. CPU/GPU requests와 HTTP 추론 호출을 하드웨어 에뮬레이터라고 설명하지 않는다.

### 1.4 개발 범위

포함: 등록 및 바인딩, EdgeX 연동, 가상 실행환경용 관측 트윈, 기존 Operator 연계, 서버측 활성화 및 안전한 비활성화, 자원 프로파일과 근거 연결, 대시보드, 단계별 시험 및 증거 산출.

포함하지 않음: Jetson 보드 전체 복제, CUDA/PCIe 원격 장치 제공, 새 하이퍼바이저, 가상 EdgeCore 대량 배포, 새로운 오프로딩 알고리즘, 임의 manifest 실행, 실제 공장 서비스 2종의 모델 개발 완료, 전체 과제의 일괄 완료 판정.

---

## 2. 현재 구현과 변경 지점

기준 커밋 이후 로컬 수정이 있을 수 있다. 개발자는 작업 시작 시 현재 브랜치, HEAD, 변경 파일을 확인하고 본 문서와 차이를 기록한다. 문서 기준으로 작업 트리를 되돌리지 않는다.

| 확인한 경로 | 현재 확인 내용 | 변경 방향 |
|---|---|---|
| `AGENTS.md` | EdgeX는 물리 장치의 원본, KubeEdge는 노드와 워크로드 관리. 퇴역 경로 구분 | 기존 경계를 보존하고 신규 VD 범위 명시 [R1] |
| `app/virtual_resource_registry.py` | Git 파일 기반 AugmentationResource/DeviceAugmentation. runtimeRef는 Deployment 중심 | 기존 schemaVersion 1 유지, 새 연결 모델은 명시적 v2로 추가 [R2] |
| `app/virtual_device_control.py` | `vd-demo-001`, Iris 모델, 이미지와 namespace 고정. SQLite 작업 기록 | 기존 데모 보존. 새 VD는 Operator 명령으로 연결 [R3] |
| `app/device_twins.py` | `physical_device_id`가 있는 대상을 읽기 전용 트윈으로 구성 | 기존 API 보존, virtual 타입의 별도 관측 모델 추가 [R4] |
| `runtime_operator/contract.py` | 실행 변형, 자원 requests/limits, 검증값, 정책, suspended. 미정의 필드 금지 | 새 선택적 계약, CRD 생성기 및 검증을 함께 수정 [R5] |
| `runtime_operator/api.py` | `/services/{name}/invoke`, 요청 ID, 결과 원장, 전송 후 무조건 재시도하지 않는 처리 | 기존 데이터 API 유지. 관리용 API는 별도 인증 경계로 추가 [R6] |
| 공통 서비스 오케스트레이션 문서 | gateway와 Operator가 같은 Pod. 새 요청 전환과 drain, resident 반환 차이 설명 | 분리된 HA gateway로 오해하지 않음 [R7] |
| `edge-orch/virtual-device-runtime/` | 이 경로는 기준 커밋 조회에서 404 | 소스가 있다고 가정하지 않음. 로컬/알려진 작업 브랜치의 실제 존재부터 확인 [R8] |

표의 `app/`는 `edge-orch/state-aggregator/app/`, `runtime_operator/`는 `edge-orch/runtime-operator/runtime_operator/`를 뜻한다.

과거 `docs/superpowers/` 설계가 현재 코드와 충돌하면 과거 문서를 근거로 퇴역 경로를 되살리지 않는다. 기존 `physical-vd:*` 화면 표현을 실행형 VD로 자동 승격하거나 별도 디바이스 수로 합산하지 않는다.

---

## 3. 목표 아키텍처

제공 개념도의 물리 대상과 가상 대상 각각의 트윈을 유지하되, 트윈을 실행 컨테이너로 해석하지 않는다. 원 그림의 선과 아이콘만으로 세부 API나 1:1 매핑을 확정하지 않고 아래 구현 계약을 별도로 둔다. [P2]

### 3.1 관리 경로

```text
NEXUS
  ├─ 조회 ──> State Aggregator ──> 원본별 reader / 관측 트윈
  │                                  ├─ EdgeX: 등록, 센서 상태
  │                                  ├─ Kubernetes: Node/Pod 상태
  │                                  └─ Runtime Operator: 실행/전환/반환 상태
  │
  └─ 등록/제어 ──> Virtual Device Facade [Aggregator 내부]
                         ├─ 승인된 Catalog 검증 및 등록 작업 원장
                         ├─ EdgeX Core Metadata: Device/Profile 등록
                         └─ EdgeX Core Command
                                  ↓
                         Virtual Device Service [신규, 공통 1개]
                                  ↓ 인증된 내부 관리 API
                         기존 Runtime Operator [확장]
                                  ↓ 유일한 실행 변경 주체
                         Kubernetes API
                           ├─ Jetson 실행체
                           └─ 서버 실행체 ──> vd-001과 연결
```

### 3.2 AI 데이터 경로

```text
클라이언트 / 승인된 입력 연계
              ↓
기존 runtime-gateway
     ├─ 현재 target=local  ──> Jetson AI Pod
     └─ 현재 target=server ──> VD에 연결된 서버 AI Pod
```

AI 요청, 영상 원본, 대형 텐서를 EdgeX Metadata 또는 Device Twin으로 중계하지 않는다. 현재 RTSP 입력 경계도 유지한다. 등록과 제어를 EdgeX로 통일하는 것과 모든 연산 데이터를 EdgeX로 보내는 것은 다른 문제다. [R1]

### 3.3 최소 배치

- 기존 중앙 EdgeX Core는 유지한다. 가상 디바이스마다 EdgeX Core를 복제하지 않는다.
- 신규 Virtual Device Service는 여러 VD를 담당하는 하나의 공통 서비스로 시작한다.
- 신규 DS는 별도 시험 namespace와 별도 배포 진입점을 사용한다. 기존 물리 Device Service 배포를 변경하지 않는다.
- Runtime Operator는 기존 실행 namespace를 계속 담당한다. 격리 시험용 Operator를 추가할 경우 관리 namespace가 겹치면 안 된다.
- Aggregator는 기존 서버 프로세스를 확장한다. VD마다 Agent/관리 Pod를 추가하지 않는다.
- 장비 이름, IP 및 이동 순서는 코드에 고정하지 않고 승인된 프로파일과 기존 서비스 탐색 설정으로 연결한다.

---

## 4. 상태 소유권과 데이터 모델

### 4.1 한 정보에는 하나의 쓰기 책임자만 둔다

| 정보 | 쓰기 책임 / 원본 | 다른 구성요소의 역할 |
|---|---|---|
| 승인된 이미지, 모델, 프로파일 | Git Catalog | 검증 및 등록 입력으로 사용 |
| 실제 등록된 Device/Profile | EdgeX Core Metadata | 읽기 및 승인된 등록 workflow를 통한 변경 |
| 물리 센서 데이터/상태 | 기존 EdgeX 경로 | 기존 정책대로 조회 |
| VD와 실행 대상의 확정 연결 | 등록 작업으로 검증된 binding, RuntimeService의 선택적 VD 연결 | EdgeX에는 연결 참조, 트윈에는 관측 결과 노출 |
| 실행 목표/전환 정책 | RuntimeService 및 Operator의 영속 관리 작업 | DS/Facade가 직접 Pod 상태로 덮어쓰지 않음 |
| Pod의 실제 상태 | Kubernetes API | UID와 소유 관계를 검증하여 조회 |
| 모델 준비, 처리 중 요청 | worker + 기존 gateway/Operator | 프로파일 값으로 대신 추정하지 않음 |
| 관리 요청 영수증 | Facade의 등록/요청 원장 | 외부 작업 접수와 전달 상태 기록 |
| 실행 작업의 최종 결과 | Operator 작업 원장 | Facade/EdgeX는 이 결과를 조회하여 전달 |
| 관측 트윈 | 원본별 reader의 결합 결과 | 원본을 대체하는 제어 DB로 사용하지 않음 |

Git Catalog는 승인된 정적 입력이다. 등록 후 사용자가 누른 제어 결과를 Git의 초기값으로 계속 되돌리지 않는다. EdgeX 등록 상태와 Runtime의 실행 상태가 다르면 `불일치/확인 불가`를 보여주며 임의로 한쪽을 정상으로 맞추지 않는다.

### 4.2 연결의 기본 단위

**첫 버전: 가상 디바이스 1개 ↔ RuntimeService 1개의 서버 실행 슬롯 1개.**

한 RuntimeService는 로컬 실행과 서버 실행을 함께 제어한다. 여기에 동일한 실행을 제어하는 또 다른 RuntimeService를 자동 생성하지 않는다. 동일 서비스의 서버 후보 GPU가 여러 개 있어도 후보 개수를 VD 수로 세지 않는다. local/server 구분은 승인된 역할과 배치 계약으로 결정하며 Jetson, AGX, Spark 같은 제품 이름만으로 역할을 추정하지 않는다.

한 물리 노드는 여러 서비스와 VD에 연결될 수 있다. 그러나 같은 `(RuntimeService UID, server slot)`을 이름만 다르게 100번 등록하는 것은 금지한다. 하나의 VD가 전환 중 old/new Pod 두 개를 갖는 경우에도 VD 수는 하나다.

### 4.3 Catalog 예시

아래는 **신규 논리 계약 예시**이며 `kubectl apply`용 YAML이 아니다. 기존 schemaVersion 1 파일에 그대로 넣지 않는다.

```yaml
schemaVersion: 2
virtualDevices:
  - id: vd-001
    deviceClass: virtual-compute
    interfaceProfileRef: virtual-compute-v1
    resourceProfileRef: server-cpu-test-v1
    executionMode: real
    physicalRef:
      kind: EdgeNode
      name: etri-dev0001-jetorn
    runtimeRef:
      kind: RuntimeService
      namespace: platform-runtime
      name: reviewed-service-a
      slot: server
```

UID는 배포 전에 Git에서 임의 작성하지 않는다. 등록 workflow에서 실제 리소스를 조회한 후 저장한다. 같은 이름의 서비스나 노드가 재생성되면 UID 변경을 감지하고 재바인딩을 요구한다. 이를 이전 장치와 자동으로 동일 취급하지 않는다.

`physicalRef.kind`는 `EdgeNode`와 `PhysicalSource`를 구분한다. Node 이름을 EdgeX Device 이름으로 가정하지 않는다. 물리 매핑이 없는 시험 fixture는 미매핑 상태를 명시하고 물리 연계 검증으로 집계하지 않는다.

### 4.4 EdgeX 매핑

전용 Device Service 이름과 전용 DeviceProfile을 사용한다. 예: `device-virtual-runtime`, `virtual-compute-v1`. 실제 필드 배치는 저장소가 사용하는 EdgeX SDK 모델로 검증한다.

- Device: VD의 등록과 장치 인터페이스 연결을 표현한다.
- DeviceProfile: 읽을 상태와 승인된 제어 명령의 데이터 계약을 표현한다.
- `labels` 또는 지원되는 `protocols` 필드: virtual 유형, catalog revision, runtime 참조를 명시한다.
- `kind`, `runtime` 같은 임의 최상위 필드를 EdgeX 기본 필드라고 가정하지 않는다.
- EdgeX의 `adminState`와 `operatingState`에 `DRAINING` 같은 사용자 상태를 직접 넣지 않는다. 실행 상태는 별도 resource 또는 관측 응답에 둔다.
- EdgeX에 저장한 마지막 실행 상태는 원본 관측 시각과 함께 제공한다. 오래된 Event는 현재 정상의 근거가 아니다.

### 4.5 RuntimeService 확장

새 선택적 계약을 예를 들어 `spec.virtualDevice`로 추가한다. 정확한 이름은 이 문서를 따른 구현에서 schema와 함께 확정한다.

```text
virtualDevice:
  id
  slot = server
  bindingGeneration
  mode = automatic | hold | disabled
```

`mode`의 의미는 6절에 정의한다. 이 확장이 없는 기존 RuntimeService는 기존 동작을 그대로 유지해야 한다. Pydantic 계약만 수정하지 말고 CRD schema 생성기, validation, 상태 모델 및 테스트를 함께 수정한다. 현재 계약은 미정의 필드를 거부한다. [R5]

등록 완료 후 실행 연결의 기준은 RuntimeService의 VD binding이다. 등록 원장의 claim은 중간 단계 예약과 감사용이며 별도 실행 권위가 아니다. Operator도 동일 `(service UID, slot)`의 중복을 거부해야 한다.

실제 연결에는 RuntimeService UID, EdgeX Device의 원본 ID, 물리 참조 UID 및 `bindingGeneration`을 사용한다. 이름/라벨만 일치한다고 다른 실행체를 가져오지 않는다.

---

## 5. 등록, 변경 및 삭제

### 5.1 등록 workflow

1. 승인된 `catalogRef + catalogRevision`을 받는다. 임의 이미지, command, hostPath 또는 원격 URL을 등록 입력으로 받지 않는다.
2. 프로파일, 실제 RuntimeService, 물리 참조 및 아키텍처 적합성을 검사한다.
3. VD ID와 `(RuntimeService UID, slot)`의 중복 바인딩을 차단하고 등록 작업을 영속 기록한다.
4. 전용 EdgeX DeviceProfile/Device를 등록하고 원본 API에서 다시 읽어 실제 등록을 확인한다.
5. RuntimeService에 선택적 VD 연결을 조건부 반영한다. resourceVersion 충돌 또는 UID 변경 시 재조회한다.
6. 양쪽 참조를 확인한 후 `BOUND`로 완료한다. 이 시점에 AI Pod가 떠 있어야 하는 것은 아니다.

이미 실행 중인 서비스에 연결하면 기존 실행을 유지한다. 대량 시험을 위해 **새 RuntimeService 정의까지 생성하는 경우에는 기본값을 `spec.suspended: true`로 생성**한다. 서버가 automatic이어도 서비스 자체가 기본 활성 상태이면 로컬 Pod가 먼저 생길 수 있으므로, 서버 VD만 정지시키는 설정으로 대량 실행을 막았다고 가정하지 않는다. 일부 기능 시험 때 서비스 재개는 명시적 시험 단계로 수행하고, VD activate가 suspended를 우회하지 않도록 유지한다.

EdgeX와 Kubernetes 사이에는 하나의 DB transaction이 없으므로 단계별 처리와 재조정이 필요하다. 중간 실패 시 `REGISTERING/BINDING_ERROR`와 성공한 단계를 남긴다. 같은 operation ID로 복구하되 기존 장치나 남의 리소스를 삭제하는 보상 동작은 하지 않는다.

### 5.2 변경

기능과 자원 프로파일의 변경은 승인된 Catalog revision을 사용한다. 실행 중인 VD는 새 revision의 후보를 준비하고 기존 요청을 정리한 뒤 전환한다. 메타데이터만 바꿔 실제 자원 적용이 끝난 것처럼 표시하지 않는다.

같은 프로파일은 여러 VD가 참조할 수 있다. 개별 자원 한도와 실제 사용량은 별도로 관측한다. 프로파일 1개의 실측 성능을 100개 병렬 실행 성능으로 확대하지 않는다.

### 5.3 삭제

등록 삭제와 실행 중지를 분리한다. `disable` 완료 및 서버 실행체 반환을 확인한 후 연결을 해제하고 EdgeX 등록을 삭제한다. 감사 이력은 보존 정책에 따라 남긴다.

EdgeX 원본이 외부에서 삭제된 경우 실행체를 즉시 강제 종료하지 않는다. `registration_missing`으로 신규 관리 요청을 막고, Operator의 기존 안전한 요청 처리 경로를 보존한 상태에서 재등록 또는 안전한 종료를 요구한다.

---

## 6. 실행 상태 및 제어 의미

### 6.1 상태를 세 축으로 나눈다

| 축 | 값 | 의미 |
|---|---|---|
| 등록/연결 | REGISTERING, UNBOUND, BOUND, BINDING_ERROR, DELETING | 관리 대상으로 연결됐는지 |
| 실행 | STOPPED, PREPARING, READY, SERVING, DRAINING, ERROR | 서버측 실행체가 무엇을 하는지 |
| 관측 | FRESH, STALE, UNAVAILABLE | 위 상태를 현재 확인할 수 있는지 |

`UNKNOWN`을 실행 실패나 정상 정지와 섞지 않는다. 마지막 실행 상태가 `STOPPED`라도 관측이 오래됐으면 현재 정지로 단정하지 않는다.

`STOPPED`는 권위 있는 조회에서 서버측 활성/준비/반환 실행체가 없고 필요한 반환 조건까지 확인된 상태다. resident worker의 Pod가 남는 경우에는 `모델 비활성 / 예약 유지`를 별도 표시한다.

### 6.2 사용자 명령

| 명령 | 목표 모드 | 의미 |
|---|---|---|
| `activate` | hold | 적합한 서버 실행체를 준비하고 서비스의 새 요청을 서버로 전환하여 유지 |
| `setAutomatic` | automatic | 기존 오프로딩 정책으로 복귀. 필요할 때만 서버 실행체를 사용 |
| `disable` | disabled | 서버 슬롯 사용을 막고, 현재 서버가 Serving이면 안전한 로컬 복귀 후 반환 |
| 서비스 전체 suspend | 기존 suspended | 기존 기능 유지. VD 제어 명령과 다름 |

`activate`는 단순 선기동만 하는 명령이 아니다. 서버 실행으로 전환한다. 미리 준비만 해 두는 `prewarm`은 이번 버전에 넣지 않는다. 사용자 버튼에는 이 영향을 분명히 표시한다.

서비스가 이미 suspended이면 VD의 `activate`가 임의로 서비스를 재개하지 않는다. `hold`라도 장애 및 안전 제한보다 우선하지 않는다. 서버 실패 시 가능한 기존 안전 복구를 적용하고 요청한 목표가 충족되지 않았음을 기록한다.

### 6.3 안전한 서버 비활성화

```text
서버 VD 사용 중지 요청
  → 동일 서비스의 다른 관리 작업과 충돌 검사
  → 로컬에서 서비스가 계속 가능한지 검사
  → 로컬 실행체 준비 및 readiness 확인
  → 새 요청을 로컬로 전환
  → 서버측 기존 요청 drain
  → 서버 실행체 정리 및 반환 확인
  → disabled 목표 적용 완료
```

로컬 후보가 없거나 준비에 실패하면 `BLOCKED`로 끝내고 기존 서버의 정상 요청 처리를 유지한다. 비활성화 완료라고 기록하지 않는다. 요청 중에는 `requestedMode`와 `effectiveMode`를 구분하고 안전한 전환이 끝난 뒤 목표를 확정한다.

**VD 중지를 `RuntimeService.suspended=true`로 구현하지 않는다.** 후자는 서비스 전체를 중지하는 기존 동작이기 때문이다. [R7]

### 6.4 요청 처리의 경계

기존 gateway가 새 요청의 현재 target을 선택한다. 전달된 요청은 원래 worker에서 처리한다. 이미 전달한 요청의 결과를 잃으면 `UNKNOWN`을 기록하고 새로운 worker에 자동 재전송하지 않는다. 이는 exactly-once 실행 보장이 아니다. [R6]

상태를 가진 AI 서비스는 모델 버전, 입력 처리 위치, 저장소와 결과 기록 방식을 별도 계약으로 정해야 한다. 이를 만족하지 않으면 해당 서비스는 이번 전환 대상에서 제외한다. 실행 메모리, KV cache, 파일 열린 상태를 자동 이전한다고 주장하지 않는다.

---

## 7. API 계약

아래 신규 API와 상태값은 설계 제안이다. 실제 OpenAPI 및 EdgeX SDK 계약시험으로 확정한다.

### 7.1 외부 관리 API

| API | 용도 | 제약 |
|---|---|---|
| `GET /api/virtual-devices` | 목록 및 summary | pagination, 부분 실패, 원본 시각 포함 |
| `GET /api/virtual-devices/{id}` | 상세 | 등록/연결/실행/관측 상태 분리 |
| `POST /api/virtual-devices/registrations` | 승인된 Catalog 항목 등록 | catalogRef/revision과 operation ID만 수용 |
| `POST /api/virtual-devices/{id}/actions` | activate, disable, setAutomatic | 인증 및 bindingGeneration 검사 |
| `GET /api/virtual-devices/{id}/operations/{operationId}` | 진행 및 최종 결과 | 다른 VD의 작업에 접근 금지 |
| `POST /api/virtual-devices/{id}/deregistrations` | 안전한 등록 삭제 | 실행 및 반환 완료 확인 후 처리 |

기존 v1 `vd-demo-001`의 `start/stop/infer` 요청은 기존 경로에서 호환 유지한다. 새 Operator 바인딩 대상은 새 action enum을 사용하고 대상 타입별로 분기한다. 하나의 실행체에 두 제어 방식을 함께 허용하지 않는다.

새 관리 요청 예:

```json
{
  "action": "activate",
  "expectedBindingGeneration": 3
}
```

`Idempotency-Key`와 인증은 header로 전달한다. Facade는 요청을 영속 저장한 뒤 `202 Accepted`와 operation ID를 반환한다. HTTP 202는 실행 완료가 아니다.

```json
{
  "operationId": "example-operation-id",
  "deviceId": "vd-001",
  "state": "ACCEPTED",
  "requestedMode": "hold",
  "effectiveMode": "automatic"
}
```

### 7.2 작업 원장과 중복 방지

명령 경로는 `Facade → Core Command → Virtual Device Service → Operator` 하나로 고정한다. Facade가 동시에 Operator를 직접 호출하는 우회 경로를 추가하지 않는다.

동일 operation ID를 모든 구간에서 전달한다. 최소 키는 `(deviceId, bindingGeneration, operationId)`이고 payload fingerprint를 저장한다. 같은 키와 다른 payload는 409로 거부한다. Operator는 service UID를 함께 검증한다.

EdgeX SDK가 사용자 header를 그대로 전달한다고 가정하지 않는다. EdgeX 명령의 지원되는 typed resource에 제한된 command envelope를 인코딩하고 SDK로 왕복 시험한다. envelope에는 action, operation ID, device ID, binding generation 및 검증 가능한 요청 주체 정보를 넣는다. 외부 사용자가 넣은 임의 principal 문자열을 신뢰하지 않는다.

서비스 간 인증정보는 Secret 참조로 관리한다. 현 테스트용 공유 토큰을 사용하더라도 실제 제어용 scope를 분리하고 고정 데모 토큰을 범용 제어 권한으로 확대하지 않는다.

Facade는 외부 요청 접수/전달 원장, Operator는 실행 결과 원장을 가진다. 완료 여부의 원본은 Operator다. 응답 유실 시 operation ID로 조회하고, 완료 상태를 `ACCEPTED`로 되돌리지 않는다.

### 7.3 작업 상태

`ACCEPTED → VALIDATING → APPLYING → SUCCEEDED`가 정상 경로다.

대안 종료: `REJECTED`(실행 전 거부), `BLOCKED`(안전한 실행 조건 미충족), `FAILED`(확인된 실행 실패), `UNKNOWN`(요청 전달 후 결과 불명). `UNKNOWN`을 성공 또는 실패로 자동 치환하지 않는다. 상태 재조회로 근거를 얻으면 근거와 함께 확정한다.

### 7.4 기존 AI 데이터 API

`POST /services/{name}/invoke`와 `X-Request-ID`는 기존 계약을 보존한다. `X-Runtime-Service-Uid` 검사도 유지한다. [R6]

기존 모델 응답 body에 VD 정보를 강제로 끼워 넣지 않는다. header 또는 별도 실행 원장에 다음을 추가한다.

```text
requestId, runtimeServiceUid, targetRevision, executionRole,
virtualDeviceId(서버 실행일 때만), workerUid, outcome
```

로컬 실행 결과에 서버 VD가 처리했다고 기록하지 않는다. 진단 요청이 필요한 경우 승인된 fixture와 고정 payload만 허용하고 production 요청과 원장을 구분한다.

---

## 8. 자원, 프로파일 및 GPU

### 8.1 자원 관측의 네 가지 구분

| 구분 | 의미 |
|---|---|
| 필요 자원 | Catalog 및 실행 변형이 선언한 requests/limits |
| 실제 적용 자원 | Kubernetes와 검증된 가속기 backend에 적용된 설정 |
| 실사용량 | Prometheus/DCGM/worker가 관측한 값 |
| 반환 결과 | 모델 해제, Pod 종료, GPU 예약 반환을 각각 확인한 결과 |

등록만 된 VD는 CPU/GPU 실행 자원을 선점하지 않는다. Registry, EdgeX 객체 및 이력 저장의 관리 비용은 남는다. 프로파일 값을 실제 사용량으로 표시하지 않는다.

### 8.2 재사용 가능한 성능 프로파일

서비스/모델 digest, 실행 이미지, 아키텍처, 장비 유형, backend, 입력 특성, concurrency, 전력 모드 등 측정 조건을 함께 저장한다. 처리량과 p95에는 측정 시각과 evidence 경로를 연결한다.

동일 조건의 VD는 하나의 프로파일을 참조할 수 있다. 물리 서버의 경합과 동시 실행 수가 달라졌다면 공유 프로파일은 사전 참고값일 뿐 실제 성능 보장이 아니다. 조건이 맞지 않으면 `UNQUALIFIED`로 표시하고 기존 성능 기반 후보 선택에서 제외하거나 별도 검증한다.

### 8.3 GPU 사용

HAMi나 기존 device plugin 등 **현 클러스터에서 지원이 확인된 backend**만 사용한다. GPU 메모리 수치를 적는 것만으로 분할이나 격리가 된 것으로 처리하지 않는다. backend 미지원 시 해당 자원 프로파일을 거부하고 이유를 반환한다.

모든 Jetson, Spark, 서버 GPU가 같은 공유 방식이나 같은 image를 지원한다고 가정하지 않는다. 확인 전에는 CPU fixture로 관리 기능을 검증하고, GPU 기능은 별도 호환성 시험을 통과한 조합에서만 활성화한다.

일반 실행체와 resident 실행체의 자원 반환을 구분한다. 현재 resident 경로는 모델 해제 후 Pod 및 GPU 예약을 유지할 수 있다. 이를 `전체 자원 반환`으로 표시하지 않는다. [R7]

### 8.4 스토리지

선택적 PVC 참조와 출력 저장 위치를 계약에 둘 수 있다. 그러나 기존 Operator가 generic PVC 실행을 지원한다고 가정하지 않는다. volume mount, 소유권 및 데이터 보존 정책은 backend 확장과 함께 시험한다.

볼륨 확대/축소는 승인된 CSI와 실제 지원 조건을 확인한 후 별도 구현한다. 특히 임의 PVC 용량 감소, 기존 데이터 삭제 또는 다른 서비스 PVC 인계는 자동으로 수행하지 않는다. 위탁 항목 전체 완료를 본 관리 기능의 산출물로 대체하지 않는다. [P1]

---

## 9. 관측, 트윈 및 대시보드

### 9.1 기존 물리 트윈 보존

기존 `ObservedDeviceTwin.physical_device_id`를 가상 디바이스 ID로 채우지 않는다. 기존 물리 API와 집계는 그대로 두고 가상 실행환경 관측 모델을 추가한 뒤 통합 화면에서 union한다. 가상 타입에는 EdgeX 등록 상태, binding 및 Runtime 관측 근거를 명시한다. [R4]

### 9.2 집계

화면 상단의 기본 카드는 다음을 분리한다.

```text
물리 관리 대상 | 가상 등록 대상 | 바인딩 검증됨 | 가상 실행 중 | 관측 확인 불가
```

서로 다른 축의 수치를 하나의 합계처럼 더하지 않는다. 예를 들어 `바인딩 검증됨`과 `실행 중`은 겹칠 수 있다. 물리 Node의 Ready와 센서의 정상 수집도 같은 상태로 처리하지 않는다.

전체 데이터가 확보되지 않았으면 정확한 합계 대신 `확인된 수 / 미확인 대상 수`를 표시한다. 실패한 reader의 기존 cached count를 최신 정상 합계로 쓰지 않는다.

### 9.3 상세 화면

등록 ID, 유형, 프로파일, 연결된 물리 대상, RuntimeService 및 UID, 현재 local/server 실행 위치, VD 실행 상태, 실제 Pod 및 worker UID, 자원 요구/적용/사용/반환, 최근 요청 결과, 마지막 관측 시각, 관리 작업 이력을 표시한다.

서비스가 로컬에서 정상 동작하고 서버 VD가 정지된 상황을 정상 시나리오로 표현한다. 기존 `physical-vd:*` 조회용 표현은 설명을 명확히 바꾸거나 별도 영역으로 유지하며 실행형 VD 수에는 넣지 않는다.

### 9.4 수집 방식

namespace/label 기준의 Kubernetes 일괄 조회와 ID별 매핑을 우선한다. worker 조회는 공통 HTTP client, timeout, 제한된 동시성으로 수행한다. 사용자가 화면을 여러 개 열어도 100개를 매번 새로 순차 조회하지 않는다.

내부 시험 기본값 제안: 수집 5초, freshness 15초, HTTP 동시 조회 10개. 이 값은 공식 목표가 아니며 측정 후 조정한다. 기존 reader의 freshness 계약은 호환성을 확인하기 전까지 일괄 변경하지 않는다.

관리 명령은 새 관측과 UID를 다시 검증한다. 오래된 대시보드 cache만 보고 실행을 바꾸지 않는다. CPU/RAM 사용량은 실행체가 없을 때 `해당 없음`, 관측 실패일 때 `확인 불가`로 구분한다.

---

## 10. 신뢰성, 보안 및 운영 경계

### 10.1 실행 소유권

같은 workload에는 제어기 하나만 둔다. 새 VD 연결 전에 기존 데모 제어기, 전용 오프로딩 제어기 및 resident 인계 상태를 점검한다. 인계되지 않은 실행체는 새 Operator가 제어하지 않는다.

RuntimeService UID/ownerReferences/실행 revision을 함께 확인한다. 이름이 같은 다른 Pod에 명령하거나 라벨만 같은 orphan Pod를 정상 실행체로 세지 않는다.

### 10.2 인증과 네트워크

조회와 쓰기 권한을 구분한다. 새 Operator 관리 endpoint는 클러스터 내부라는 이유만으로 무인증으로 공개하지 않는다. 승인된 DS/Facade 경로와 인증된 요청만 수용한다. 브라우저가 Operator 관리 API를 직접 호출하지 않는다.

새 DS에는 Kubernetes Pod/Deployment 변경 권한을 주지 않는다. Core Command를 통한 승인된 명령 변환만 맡긴다. NetworkPolicy는 실제 CNI의 적용 여부를 시험하고, 미지원 환경에서는 정책 파일 존재를 격리 완료로 표시하지 않는다.

Secret, token, 원시 센서 credential, 불필요한 inference payload를 Metadata 또는 로그에 저장하지 않는다. 이미지 digest, 경로, enum, payload 크기, timeout 및 batch 크기는 allowlist/상한으로 제한한다.

### 10.3 요청 충돌과 재시작

관리 작업은 service UID별로 직렬화한다. 서로 다른 VD는 제한된 동시성으로 처리할 수 있다. 등록 전체를 장시간 하나의 파일 잠금으로 묶지 않는다.

현재 단일 Operator/SQLite 구성을 재사용하되 다중 replica 안전성을 주장하지 않는다. HA가 필요하면 리더 선출, fencing 및 원장 저장소를 별도 설계해야 한다. 재시작 시 진행 작업과 실제 리소스를 대조하고 응답이 불명인 inference는 재실행하지 않는다.

### 10.4 GitOps

정적 image/프로파일과 동적 실행 목표의 쓰기 책임을 분리한다. 적용된 Argo CD 설정이 동적 mode나 Operator 소유 replicas를 원래 값으로 되돌리지 않는지 시험한다.

필요한 ignore 경로는 해당 시험 Application의 실제 필드로 한정하고 동기화 동작까지 검증한다. 전체 namespace에 무차별 diff 무시를 적용하지 않는다. GitOps가 제어하는 기존 운영 정의를 개발 중 임의 변경하지 않는다.

### 10.5 롤백

feature flag를 끄면 기존 물리 조회와 서비스 호출은 남는다. 새 등록을 차단한 후 VD별 안전한 비활성화 및 연결 해제를 수행한다. 이전 제어기 복원은 새 제어기의 소유권 반환을 확인한 뒤 진행한다.

원장 schema는 additive migration을 우선하고 기존 작업 이력을 삭제하지 않는다. 시험 객체 정리는 batch ID, namespace, owner UID가 일치하는 대상에 한정한다. 광역 label delete 또는 전체 namespace 삭제를 기본 정리 명령으로 제공하지 않는다.

---

## 11. 100개 관리 시험과 산정

### 11.1 지표를 구분한다

```text
N_registered : 현재 등록된 고유 관리 대상 수
N_bound      : 실행/물리 참조가 검증된 대상 수
N_observable : 시험 조건에서 상태를 정상 확인한 대상 수
N_controllable: 정해진 시험에서 지원 제어가 확인된 대상 수
N_running    : 현재 실제로 실행 중인 가상 디바이스 수
N_qualified  : 승인된 평가규칙을 만족한 대상 수
```

이 값들을 동일하다고 가정하지 않는다. `N_qualified`는 승인된 판정 규칙이 없으면 `미정`으로 둔다. 대시보드 자체가 등록 수만 보고 `과제 100개 달성`을 선언하지 않는다.

### 11.2 집계 원칙

- 물리 장비는 고유 원본 identity 기준으로 집계한다. 한 Arduino의 기능별 EdgeX Device와 트윈을 모두 별도 물리 장비로 더하지 않는다.
- 컴퓨팅 노드와 그 위 센서의 산정 범주는 시험 명세에 명시한다. Node 수와 EdgeX Device 수를 그대로 더하지 않는다.
- 가상 디바이스는 독립 등록과 지원 제어, 실행 바인딩 및 검증 증거를 가진 대상을 관리한다. 같은 backend를 복제한 별칭은 독립성 근거가 없으면 제외한다.
- Pod 재시작, rollout의 중복 실행체, 후보 실행체, `physical-vd:*`, observation twin은 새로운 VD 수로 세지 않는다.
- 정지한 VD도 관리 모델에는 남는다. 공식 성능지표에 정지 대상을 포함할 수 있는지는 시험기관 합의 항목이다.

계획서의 정의는 단일 노드에 배포된 트윈 엔진의 관리 가능 수이며, 평가방법은 연동 대상 수를 늘리며 안정적인 운영을 확인하는 방식이다. **100개 동시 추론을 자동 요구하지도 않고, 동시 연동이나 상태 확인이 불필요하다고 단정하지도 않는다.** [P1]

### 11.3 제안하는 내부 시험

수량: 1 → 10 → 30 → 60 → 물리/가상 합계 100. 다음 수량으로 올라갈 조건을 결과 원장으로 남긴다.

관리 시험은 등록 대상 전체를 유지한 상태에서 조회, 연결 무결성, 상태 확인 및 원장 보존을 검증한다. 가상 대상의 기능 검증은 동시 실행 상한을 명시하고 순차/소규모 병렬로 진행한다. 서로 다른 실제 VD 3개 이상을 동시에 실행하여 병렬 기능을 확인하는 것을 초기 내부 gate로 제안한다. 3개는 공식 연차 목표 수치가 아니다.

제안 기본 운영 시험 30분, 전체 관리 조회 갱신 5초. 환경 CPU/RAM, 관리 엔진 node, actual parallelism, 요청량, 응답 지연, 실패 및 확인 불가 수를 기록한다. 고정 합격 latency와 공식 시험 시간은 시험기관과 별도로 확정한다.

부하 한계, OOM 위험, 기존 서비스 영향이 보이면 자동 다음 단계 확장을 중단한다. 미실행 시험을 통과로 만들지 않는다.

---

## 12. 에뮬레이션 개발 항목의 별도 경계

**관리 객체 + 일반 GPU Pod + 추론 API는 ‘가상 AI 가속기 에뮬레이션 엔진’의 충분한 완료 근거가 아니다.** REQ-03은 별도 작업 패키지로 남긴다. [P1]

첫 구현에 다음 백엔드 구분을 둔다.

| executionMode | 용도 | 표시 및 주장 |
|---|---|---|
| `real` | CPU/GPU에서 실제 AI 연산 수행 | 실제 실행, 실측 성능 |
| `test-fixture` | 관리/전환 경로용 합성 입력과 제어 가능한 응답 | 합성 시험. 현장 실증이나 장치 에뮬레이션 아님 |
| `emulated` | 승인된 인터페이스와 동작을 재현하는 후속 backend | 명세, 범위, 참조 장치, 검증 결과가 있을 때만 활성화 |

개발자는 `prepare / readiness / invoke / drain / release / observe` 등 현 Operator와 맞는 adapter 경계를 정의하되, fixture를 만든 것만으로 `emulated` 기능 완료를 표시하지 않는다.

REQ-03의 명세에서 결정할 항목: 재현 대상 인터페이스, 데이터 형식, 오류 의미, 참조 실행 결과, 재현할 timing/자원 조건, 허용 오차와 검증 절차. 이것이 확정되지 않은 동안에도 등록/관측/실행 연동 개발은 계속할 수 있다. 다만 전체 3-1 항목 완료는 보류한다.

---

## 13. 구현 순서와 파일 변경안

경로 중 `신규 제안`은 현재 존재한다고 확인한 파일이 아니다. 실제 구조와 충돌하면 같은 책임을 기존 적합 모듈에 배치하고 변경 사유를 남긴다.

| 단계 | 작업 | 주요 경로 / 완료 기준 |
|---|---|---|
| M0 | 기준선 조사, 계약 확정, 범위 문서 갱신 | 현재 HEAD/dirty 상태, 기존 시험 결과, 누락 소스, owner 및 runtime 계약 기록 |
| M1 | v2 등록/바인딩 모델과 원장 | `virtual_resource_registry.py`, 신규 `virtual_device_registration.py`, schema 및 migration tests |
| M2 | Operator 서버 슬롯 제어 | `runtime_operator/contract.py`, `controller.py`, `api.py`, `journal.py`, CRD 생성기 |
| M3 | EdgeX 전용 DS 연동 | 신규 `edgex/device-virtual-runtime/`, SDK 기반 Profile/command/event 계약시험 |
| M4 | 조회와 트윈 및 NEXUS | `virtual_resources.py`, `device_twins.py` 또는 별도 virtual twin builder, 기존 static 화면 |
| M5 | 1개 연계 및 100개 관리 검증 도구 | 승인형 Catalog 생성기, fixture, 증거 수집 및 안전 정리 도구 |
| M6 | 실클러스터 검증/운영 승격 | 별도 승인된 배포, 실제 요청 전환, drain, 자원 반환, rollback |

M0~M5의 로컬 코드와 테스트는 기본 개발 범위다. 실클러스터 apply, 실제 부하/장애 주입, 운영 image 변경은 M6에서 별도 승인을 받는다. 승인 대기는 해당 작업에만 적용하고 독립적인 로컬 개발까지 중단하지 않는다.

원본 runtime 디렉터리가 없으면 로컬과 알려진 브랜치를 읽기 전용으로 확인한다. 없을 경우 기존 공통 RuntimeService 계약에 맞는 명시적 CPU fixture를 새로 구현할 수 있다. 이를 과거 Iris runtime의 복원본이나 이미 운영한 기능으로 설명하지 않는다.

---

## 14. 검증 항목 및 수용 기준

| 시험 ID | 검증 | 기대 결과 |
|---|---|---|
| T01 | 기존 schemaVersion 1 로딩 | 기존 데모 정의와 동작 유지 |
| T02 | v2 schema / 잘못된 참조 | 미정의 필드, 잘못된 참조, 중복 ID 거부 |
| T03 | 동일 서버 슬롯 중복 claim | 이름을 바꿔도 중복 바인딩 거부 |
| T04 | 등록 중 EdgeX/Kubernetes 부분 실패 | 부분 상태 기록, 같은 operation ID로 재조정, 타 객체 삭제 없음 |
| T05 | 미인증/잘못된 scope/다른 VD의 요청 | 제어 및 이력 접근 차단 |
| T06 | 같은 ID 같은 payload / 다른 payload | 기존 결과 반환 / 충돌 거부 |
| T07 | VD 계약 없는 RuntimeService | 기존 실행 동작과 API 호환 유지 |
| T08 | activate | 서버 준비 전 기존 요청 유지, 준비 후 새 요청 전환 |
| T09 | disable 로컬 준비 성공 | 로컬 전환, 서버 drain 및 반환 후 완료 |
| T10 | disable 로컬 후보 없음/준비 실패 | BLOCKED, 기존 서버 서비스 유지 |
| T11 | 서비스 suspended 상태의 activate | 서비스 임의 재개 없음 |
| T12 | worker 응답 유실/프로세스 재시작 | UNKNOWN 보존, 전달된 추론 재전송 없음 |
| T13 | Node/RuntimeService UID 변경 | 이전 identity와 혼동하지 않고 재바인딩 요구 |
| T14 | rollout/old-new 실행체 공존 | VD 1개 유지, 각 실행체와 반환 대상 별도 관측 |
| T15 | EdgeX 등록 삭제/reader 실패 | 새 제어 차단 또는 확인 불가, 기존 데이터 경로 불필요 중단 없음 |
| T16 | resident 모델 해제 | 모델 반환과 GPU 예약 유지 사실 분리 |
| T17 | 프로파일 조건 불일치/미지원 GPU backend | 후보 제외 또는 명시적 미검증, 지원 완료 표시 없음 |
| T18 | physical-vd 표현/센서 fan-out | 관리 수 중복 산정 없음 |
| T19 | NEXUS의 일부 reader 실패 | 최신 정상으로 위장하지 않고 원본 시각과 부분 실패 표시 |
| T20 | 100개 관리 대상 + 제한된 실행 동시성 | 관리와 실행 수 분리, 개별 검증 증거 보존 |
| T21 | 서로 다른 VD의 병렬 실제 기능 호출 | 각 VD identity와 결과, 간섭 및 실패 범위 확인 |
| T22 | EdgeX command envelope 왕복 | 동일 operation ID, action, binding generation 및 인증 범위 보존 |
| T23 | GitOps 동기화와 동적 목표 | 동기화가 임의 실행/정지 또는 소유권 충돌을 유발하지 않음 |
| T24 | 롤백 | 기존 센서, 서비스 API, 원장 유지 및 제어 소유권 정상 반환 |

수용 수준을 `로컬 단위시험`, `계약/통합시험`, `승인된 실클러스터 시험`, `공식 평가`로 분리한다. 모의 100개 응답만으로 실제 100개 관리 성공이나 공식 지표 달성을 주장하지 않는다.

### 산출할 검증 묶음

```text
run-metadata.json     # 실제 commit, 시간, 환경, 테스트 범위, image digest
inventory.json       # 고유 대상, 원본, 매핑, 판정 상태
operations.jsonl     # 등록/제어 작업 단계 및 결과
requests.jsonl       # 작업 ID, 실제 실행 대상, 결과 상태
metrics.csv          # 실제로 수집한 성능/자원 값
summary.md           # 실행한 시험, 실패, 미실행, 제한, 다음 조치
```

위 파일은 시험을 실행한 뒤 실제 관측으로 생성한다. 예시나 빈 파일을 증거라고 제출하지 않는다. 민감한 token 및 원시 개인정보는 제외한다.

---

## 15. 완료 정의와 남는 승인 사항

### 관리/실행 연동 기능의 완료

승인된 Catalog에서 등록한 VD가 EdgeX 원본 조회로 확인되고, RuntimeService의 서버 실행 슬롯과 고유하게 연결된다. 실제 오프로딩 및 반환의 상태와 처리 증거가 NEXUS에서 추적되며, 기존 물리 장치/서비스 경로가 유지된다. 100개 규모의 관리 도구와 실제 수행한 시험 결과를 제공한다.

### 이 문서만으로 확정하지 않는 사항

1. 정지 VD의 공식 산정 포함 여부, 단일노드 시험의 실제 배치 조건, 연동/관측/제어 부하와 합격 기준.
2. 가상 AI 가속기 에뮬레이션의 대상 및 API, 동작 재현 범위와 수용 오차.
3. 실제 GPU/NPU 공유 및 스토리지 증강/축소의 장비별 지원과 권한.
4. KPST/경북대 구현물과의 최종 인터페이스 및 산출물 책임 분담.

문서에 이 항목들이 남는다고 관리 기능 개발을 멈출 필요는 없다. 해당 항목의 완료를 사실과 다르게 선언하지 않는 것이 원칙이다.

---

## 16. 출처 및 확인 범위

아래 출처는 계획서 요구사항과 현재 코드 사실을 위한 것이다. 신규 API, 상태 기계, 소유권 규칙 및 단계별 gate는 본 문서의 설계 결정이다.

| ID | 출처 / 확인 위치 |
|---|---|
| U1 | 본 대화에서 사용자가 지정한 2차년도 관리 대상 100개, 100개 동시 실행으로 해석하지 말라는 요구, 제공 아키텍처에 맞춘 설계 요청 |
| P1 | `(2차년도협약용) 연구개발계획서-엣지 컴퓨팅 시스템을 위한 대규모 혼합 디바이스 제어·관리 플랫폼 개발_0415.pdf`: 본문 36쪽(PDF 45), 45쪽(PDF 54), 53~58쪽(PDF 62~67), 169쪽(PDF 178) |
| P2 | `시스템아키텍처소개.pdf` 4쪽 및 사용자가 다시 첨부한 동일 계열 개념도. 물리/가상 대상 각각의 트윈과 서버자원 추가 할당, 오프로딩을 표현 |
| R1 | `AGENTS.md`, 기준 커밋에서 1~175행 확인 |
| R2 | `edge-orch/state-aggregator/app/virtual_resource_registry.py`, 전체 확인 |
| R3 | `edge-orch/state-aggregator/app/virtual_device_control.py`, 1~125행 확인 |
| R4 | `edge-orch/state-aggregator/app/device_twins.py`, 전체 확인 |
| R5 | `edge-orch/runtime-operator/runtime_operator/contract.py`, 전체 확인 |
| R6 | `edge-orch/runtime-operator/runtime_operator/api.py`, 전체 확인 |
| R7 | `docs/공통-서비스-Kubernetes-오케스트레이션.md`, 1~150행 확인 |
| R8 | 기준 커밋의 `edge-orch/virtual-device-runtime/` directory 조회가 404. 다른 branch/로컬/운영 image의 부재까지 증명하지는 않음 |

저장소: `https://github.com/dsa04156/edge-ai-workspace`  
기준 커밋: `2926ac7ae21bd72c7d70f57f09e7109e2c124086`

이 문서는 운영 클러스터 조회, 코드 변경, 테스트 실행 또는 배포를 수행한 결과 보고서가 아니다.
