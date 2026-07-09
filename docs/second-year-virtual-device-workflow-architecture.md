# 2차년도 가상디바이스·디바이스트윈·워크플로우 설계

## 목적

이 문서는 2차년도 협약 방향에 맞춰 현재 PoC를 어떤 구조로 확장할지 정의한다.
기준 문서는 `docs/(2차년도협약용) 연구개발계획서-엣지 컴퓨팅 시스템을 위한 대규모 혼합 디바이스 제어·관리 플랫폼 개발_0415.pdf`다.

이 설계는 기존 `test_device.py` 기반 MQTT 가짜 센서 생성 방식을 가상디바이스의 본류로 보지 않는다.
2차년도 방향의 가상디바이스는 물리 온디바이스와 매핑되는 컨테이너/소프트웨어 인스턴스이며, 디바이스트윈과 워크플로우 오케스트레이션의 관리 대상이다.

## 핵심 정의

| 용어 | 정의 | 현재 PoC와의 관계 |
|---|---|---|
| 물리 온디바이스 | Jetson, Raspberry Pi, 센서, 액추에이터, 카메라처럼 실제 현장에 존재하는 장비 | KubeEdge node/device, MQTT/collector, InfluxDB telemetry의 원천 |
| 가상디바이스 | 물리 온디바이스의 기능, 상태, 자원, 입출력을 엣지 AI 서버 쪽에서 컨테이너/소프트웨어 인스턴스로 표현한 대상 | 물리 장비를 workflow와 오케스트레이션이 다룰 수 있는 관리 단위로 추상화 |
| 디바이스트윈 | 물리/가상디바이스의 현재 상태, capability, resource, I/O, binding 상태를 담는 snapshot | raw telemetry 저장소가 아니라 상태/제어/관리 snapshot |
| AI 서비스 워크플로우 | AI 서비스를 collect, preprocess, inference, postprocess, event, dashboard sink 같은 stage로 분해하고 물리/가상디바이스를 동적으로 연결하는 실행 구조 | 기존 workflow 실험을 그대로 쓰지 않고 2차년도용으로 새로 설계 |
| Input source | workflow stage가 읽을 수 있는 데이터 입력 단위. InfluxDB stream, twin 상태, virtual device API가 될 수 있음 | 가상디바이스의 I/O 중 workflow 입력으로 노출되는 부분 |

## 하지 않는 방식

다음 방식은 2차년도 가상디바이스 설계의 중심으로 쓰지 않는다.

```text
test_device.py
  -> 가짜 온도/진동/health 생성
  -> MQTT publish
  -> mqttvirtual mapper
  -> InfluxDB / DeviceStatus
```

이 방식은 과거 경로 검증이나 legacy 테스트에는 쓸 수 있지만, 협약 방향의 가상디바이스 정의와 다르다.
2차년도 문서와 설계에서는 가상디바이스를 "가짜 센서 publisher"가 아니라 "물리 온디바이스와 매핑되는 소프트웨어 관리 인스턴스"로 표현한다.

## 목표 구조

```text
Physical On-Device Layer
  Jetson / Raspberry Pi / sensor / actuator / camera
  -> telemetry, state, resource, I/O event 생성

Data and State Layer
  InfluxDB      -> raw telemetry stream 저장
  Device Twin   -> 상태/capability/resource/I/O/binding snapshot
  Prometheus    -> node/container resource metric
  Kubernetes    -> container, pod, placement, lifecycle 상태

Device Source Layer
  KubeEdge Device / DeviceStatus
  InfluxDB latest telemetry
  node resource profile
  -> physical_ref, freshness, resource profile, I/O endpoint 상태 제공

Workflow Layer
  AI service workflow builder/runtime
  -> 등록 Device/source와 node resource 후보 선택
  -> stage 구성
  -> input/output 연결
  -> 실행 위치와 자원 요구량 관리

Web Control Layer
  workflow 통합 개발도구
  -> 등록 Device/source 풀
  -> DeviceStatus snapshot / telemetry freshness
  -> workflow canvas
  -> binding/validation/execution plan
```

## 현재 PoC Workflow Source 모델

현재 PoC의 workflow builder는 별도 VirtualDevice registry를 만들지 않는다.
선택 가능한 source는 `state-aggregator`가 Kubernetes/KubeEdge에서 조회한 등록
`Device`와 InfluxDB latest telemetry freshness를 결합한 read-only view다.

```yaml
name: imu-sensehat-gyroscope-01
kind: kubeedge_device
node: etri-dev0003-raspi5
telemetry_status: fresh
telemetry_last_seen_at: "2026-06-12T07:25:27Z"
device_status_fresh: true
overall_status: healthy
properties:
  - gyro_x
  - gyro_y
  - gyro_z
```

현재 PoC에 승격된 최소 API 표면은 `state-aggregator`의 read-only GET API다.
이 단계에서 Kubernetes/KubeEdge에는 물리 `Device`와 workload만 등록된다.

| API | 역할 |
|---|---|
| `GET /state/devices` | 등록 Device, DeviceStatus freshness, telemetry freshness 조회 |
| `GET /state/devices/{device_id}/telemetry` | InfluxDB에서 해당 Device의 window telemetry sample 조회 |
| `GET /state/nodes` | AI HAT 등 노드 부착 resource 후보 판단에 필요한 노드 상태 조회 |

물리 환경 예시는 다음처럼 구분한다.

| 노드 | 장착 장치 | Workflow 역할 |
|---|---|---|
| `etri-dev0002-raspi5` | AI HAT | AI HAT NPU가 붙은 lightweight inference/resource 후보 |
| `etri-dev0003-raspi5` | Sense HAT | 등록 Device telemetry 입력 source |

## 디바이스트윈 모델

디바이스트윈은 raw telemetry stream 전체를 담지 않는다.
디바이스트윈은 workflow와 운영자가 판단할 수 있는 상태 snapshot만 유지한다.

허용하는 대표 필드:

| 영역 | 필드 예시 |
|---|---|
| 상태 | `health`, `availability`, `severity`, `freshness`, `status_last_seen` |
| capability | `inputs`, `outputs`, `operations`, `supported_models` |
| 자원 | `cpu_class`, `memory_class`, `accelerator`, `current_load`, `resource_profile` |
| 입출력 | `telemetry_sources`, `command_endpoints`, `result_outputs` |
| workflow binding | `bound_workflow`, `bound_stage`, `binding_state`, `last_binding_change` |
| 오류 | `last_error_code`, `last_error_message`, `recovery_hint` |

제외하는 필드:

- 고빈도 raw temperature/humidity/vibration/gyro stream 전체
- 이미지 frame 또는 waveform 원본
- 매 event log 전체
- 모델 inference raw result stream 전체

raw 데이터는 InfluxDB 같은 data-plane에 남기고, twin은 상태와 관리 정보를 제공한다.

## 워크플로우와의 관계

AI 서비스 워크플로우는 등록 Device를 stage 입력 source로, 노드 부착 resource를 실행 대상 후보로 사용한다.

```text
AI Service Workflow
  source stage
    -> /state/devices/{device_id}/telemetry
  preprocess stage
    -> gyro feature extraction
  inference stage
    -> anomaly model
  event stage
    -> alert/event output
  dashboard sink
    -> operator view
```

workflow가 동적으로 바꾸는 것은 물리 장비 자체가 아니라 다음 항목이다.

- 어떤 가상디바이스를 어떤 workflow stage에 bind할지
- 어떤 input source를 stage 입력으로 사용할지
- stage를 어느 node/container에서 실행할지
- 가상디바이스 resource profile을 기준으로 실행 가능 여부를 판단할지
- 장애나 stale 상태에서 어떤 대체 가상디바이스로 전환할지

## 30개 가상디바이스 해석

2차년도 목표에서 "30개"는 가짜 센서 30개를 MQTT로 만들었다는 뜻으로 설명하지 않는다.
현재 테스트베드에서는 물리 온디바이스, 센서 기능, telemetry stream, 자원 profile, I/O endpoint를 조합해 30개의 가상디바이스 인스턴스를 구성한다.

예시 구성:

| 분류 | 예시 | 설명 |
|---|---|---|
| 물리 센서 기능 단위 | Sense HAT humidity, pressure, gyro, orientation | 한 물리 장비의 여러 I/O 기능을 가상디바이스로 분리 |
| 물리 디바이스 단위 | Jetson sensor bundle, Raspberry Pi Sense HAT bundle | 여러 stream을 하나의 가상디바이스 capability로 묶음 |
| 자원 profile 단위 | Jetson GPU-lite, Raspberry Pi AI HAT, Raspberry Pi Sense HAT, x86 GPU server | workflow placement와 resource 판단에 쓰는 가상 자원 표현 |
| 서비스 I/O 단위 | anomaly input source, environment input source, actuator state source | workflow stage에서 바로 선택 가능한 입력/출력 단위 |

## 현재 시스템에서 재사용할 것

| 기존 구성 | 재사용 방식 |
|---|---|
| InfluxDB telemetry | 가상디바이스 I/O source와 freshness 판단의 data-plane |
| KubeEdge Device/DeviceStatus | 물리 온디바이스 상태와 일부 twin snapshot의 source |
| Prometheus/Kubernetes 상태 | 가상디바이스 resource profile과 placement 판단의 source |
| state-aggregator | 물리/가상디바이스, twin, workflow 상태를 통합하는 API 후보 |
| dashboard UI 패턴 | 운영 가시화와 issue/freshness 표현 방식 재사용 |

## 새로 설계할 것

| 구성 | 역할 |
|---|---|
| Virtual Device Registry | 물리 ref, capability, resource, I/O, twin schema를 가진 가상디바이스 목록 관리 |
| Virtual Device Runtime | 각 가상디바이스의 API, lifecycle, InfluxDB query, 상태 refresh 담당 |
| Twin Engine | physical/virtual device의 상태 snapshot 생성, binding 상태 관리 |
| Workflow Builder | 사용자가 AI 서비스를 stage 단위로 구성하고 가상디바이스를 연결하는 웹 기반 개발도구 |
| Workflow Runtime | stage 실행, input/output handoff, lifecycle, 장애 처리 담당 |
| Orchestration Policy | 자원 상태와 twin 상태를 기준으로 bind/rebind/placement 판단 |

## 웹페이지 설계 방향

웹페이지는 단순 dashboard가 아니라 "워크플로우 통합 개발도구"로 설계한다.

권장 화면 구조:

| 영역 | 역할 |
|---|---|
| Virtual Device Pool | 30개 가상디바이스의 상태, 물리 매핑, capability, resource, binding 표시 |
| Workflow Canvas | AI service stage와 data flow를 구성 |
| Twin Inspector | 선택한 가상디바이스의 상태, resource, I/O, 오류, bound workflow 확인 |
| Binding Panel | stage와 가상디바이스를 연결/해제하고 대체 후보를 확인 |
| Validation Panel | 누락된 input, stale source, resource 부족, unsupported operation 확인 |
| Execution Plan | 컨테이너 배포/실행 계획, stage placement, I/O endpoint 요약 |

초기 버전은 실제 자동 제어보다 다음을 우선한다.

1. 등록 Device/source 목록을 볼 수 있다.
2. Device가 어떤 물리 온디바이스/데이터 freshness/자원과 연결되는지 확인할 수 있다.
3. 사용자가 AI 서비스 workflow stage를 만들고 등록 Device 또는 노드 resource 후보를 bind할 수 있다.
4. workflow 실행 전 validation 결과를 볼 수 있다.
5. 실행/배포는 명시적 사용자 동작과 검증 단계를 거친다.

## 단계별 진행안

### 1단계: 등록 Device 기반 source pool

현재 초안:

- `state-aggregator`의 `GET /state/devices`: 등록 Device와 freshness를 운영 API로 조회
- `state-aggregator`의 `GET /state/devices/{device_id}/telemetry`: InfluxDB sample 조회
- dashboard workflow UI: 브라우저 상태 안에서 stage graph, device/resource binding, validation, execution plan preview 제공

### 2단계: twin engine

- InfluxDB latest/window query를 통해 I/O freshness 계산
- KubeEdge DeviceStatus와 node metric을 twin snapshot에 병합
- raw telemetry는 twin에 저장하지 않고 source reference와 derived status만 제공

### 3단계: workflow builder

- AI service stage schema 정의
- stage input/output type 정의
- 등록 Device/source bind/release 모델 정의
- workflow validation rule 작성

### 4단계: 웹 UI

- 등록 Device/source pool
- workflow canvas
- DeviceStatus/telemetry inspector
- validation panel
- execution plan preview

### 5단계: runtime/orchestration

- workflow runtime과 container lifecycle 연계
- resource/twin 상태 기반 placement 후보 계산
- 장애/stale 상태에서 rebind/retry 정책 적용
- 결과와 이벤트를 dashboard/twin에 반영

## 표현 원칙

사용할 표현:

- 물리·가상 디바이스 연계
- 디바이스트윈 기반 상태 관리
- 가상디바이스 인스턴스
- AI 서비스 워크플로우
- 컨테이너 기반 워크플로우 통합 개발도구
- 물리 온디바이스와 매핑되는 가상디바이스
- 자원·입출력·상태 기반 오케스트레이션

피할 표현:

- 가상디바이스는 가짜 MQTT publisher라는 표현
- raw telemetry를 디바이스트윈에 직접 저장한다는 표현
- 30개 물리 센서를 이미 확보했다는 표현
- 동적 오케스트레이션이 현재 PoC에서 완성됐다는 표현
- LLM이 전체 제어를 수행한다는 표현

## 현재 PoC와의 경계

현재 PoC 문서는 서비스 데모와 운영 가시화를 중심으로 유지한다.
이 문서는 2차년도 설계 트랙이며, 기존 current demo가 이미 이 기능을 제공한다고 주장하지 않는다.
구현으로 승격할 때는 `docs/scope.md`, `docs/repo-structure.md`, `docs/roadmap.md`에서 현재 범위와 2차년도 설계 범위를 분리해 표시한다.
