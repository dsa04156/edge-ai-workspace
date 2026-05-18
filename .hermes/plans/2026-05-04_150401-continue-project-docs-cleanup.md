# 프로젝트 문서 정리 계속 진행 계획

> **Hermes 참고:** 이 문서는 계획 전용 문서다. 사용자가 명시적으로 실행을 요청하기 전에는 아래 단계를 실제 구현하지 않는다.

## 목표

현재까지 진행한 범위 정리 작업을 이어서, 현재 데모 경로와 관련 문서들을 한국어로 정리한다.

이번 정리의 핵심은 다음이다.

- 현재 PoC 범위와 제외 범위를 분명히 한다.
- workflow/offloading/agent-assisted planning 계열을 “후속 고도화”로 표현하지 않는다.
- 해당 계열은 현재 연구 방향에서 제외된 과거 검토/실험 또는 보관 자료로만 다룬다.
- 현재 문서는 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화 중심으로 작성한다.
- 프로젝트 문서는 기본적으로 한국어로 작성한다.

## 현재 상황

이미 완료한 정리 작업은 다음과 같다.

1. `docs/scope.md` 작성
   - 현재 PoC 범위를 정의했다.
   - 현재 구현 과정에 포함되는 컴포넌트를 정리했다.
   - workflow/offloading/agent-assisted planning 계열을 현재 연구 방향에서 제외한다고 명시했다.

2. `docs/README.md` 수정
   - `scope.md`를 Active Guides에 추가했다.
   - 이후 `repo-structure.md`도 Active Guides에 추가했다.
   - `roadmap.md` 설명에서 동적 offloading / agent-assisted planning을 후속 계획처럼 보이게 하는 표현을 제거했다.

3. `docs/roadmap.md` 재작성
   - 기존 “후속 고도화” 표현을 제거했다.
   - 현재 구현 방향을 다음 흐름으로 정리했다.
     - device
     - MQTT
     - mapper
     - DeviceStatus / InfluxDB
     - state-aggregator
     - dashboard
   - 현재 범위에서 제외하는 경로를 별도 섹션으로 명시했다.

4. `docs/repo-structure.md` 작성
   - 레포 디렉터리를 다음 기준으로 분류했다.
     - 현재 범위
     - 현재 범위 보조
     - 제외/보관
     - 외부/참조
     - 정리 검토
   - `edge-orch/workflow_executor/`, `edge-orch/workflow_reporter/`, `edge-orch/placement_engine/`, `workflow/`는 현재 연구 방향의 후속 계획이 아니라 제외/보관 또는 검토 대상으로 분류했다.

이 계획 작성 직전 기준 변경 상태는 다음과 같았다.

```text
M docs/README.md
M docs/roadmap.md
?? docs/repo-structure.md
?? docs/scope.md
?? traefik/gemma-ingressroute.yaml
```

주의:

- `traefik/gemma-ingressroute.yaml`은 이번 정리 작업 이전부터 untracked 상태였으며, 사용자 확인 없이 포함하거나 수정하지 않는다.

## 진행 원칙

1. 문서는 한국어로 작성한다.
2. 문서마다 목적을 좁게 잡는다.
3. 코드 이동/삭제보다 문서 기준 정리를 먼저 한다.
4. 현재 범위와 제외 범위를 섞지 않는다.
5. workflow/offloading/agent-assisted planning 계열을 후속 고도화로 표현하지 않는다.
6. 현재 구현 경로는 서비스 데모와 운영 가시화의 한 구현 과정으로 표현한다.
7. “제일 중요한 것”처럼 단정하지 않고 “현재 PoC를 구성하는 구현 경로 중 하나”로 표현한다.

## 다음 작성 순서

권장 순서는 다음과 같다.

1. `docs/current-demo-path.md`
2. `docs/device-service-binding.md`
3. `docs/service-demo-scenario.md`
4. `docs/dashboard-information-structure.md`
5. `docs/ops/runbook-current-demo.md`
6. 필요 시 archive/excluded 경로 안내 문서 보강

## 단계별 계획

### 1단계: `docs/current-demo-path.md` 작성

목적:

현재 PoC에서 디바이스, MQTT, mapper, telemetry 저장, DeviceStatus, state-aggregator, dashboard가 어떤 경로로 연결되는지 설명한다.

생성할 파일:

- `docs/current-demo-path.md`

권장 목차:

```markdown
# Current Demo Path

## 목적

현재 PoC에서 디바이스, telemetry, mapper, 상태 통합, dashboard가 어떤 경로로 연결되는지 설명한다.

## 한 줄 요약

physical / virtual device -> MQTT -> mqttvirtual mapper -> DeviceStatus snapshot + InfluxDB telemetry -> state-aggregator -> dashboard

## 전체 흐름

[text diagram]

## Device 등록 경로

- DeviceModel / Device 사전 등록
- Jetson nodeName 매핑
- Raspberry Pi nodeName 매핑

## MQTT topic 경로

- factory/devices/{device-name}/telemetry
- factory/devices/{device-name}/command
- factory/devices/{device-name}/heartbeat

## 테스트 publisher 경로

- `mappers/script/test_device.py`
- `DEVICE_PLAN=jetson`
- `DEVICE_PLAN=rpi`
- `DEVICE_FILTER=...`

## mapper 경로

- `mappers/mqttvirtual/`
- telemetry topic subscribe
- command topic publish
- DMI / DeviceStatus 연동

## data-plane / status-plane 분리

- DeviceStatus: 저빈도 운영 snapshot
- InfluxDB: raw telemetry data-plane

## state-aggregator 경로

- KubeEdge Device / DeviceStatus
- InfluxDB latest telemetry
- Prometheus node state
- mapper pod 상태

## dashboard 경로

- `/state/devices`
- `/state/dashboard`
- freshness 기반 device status 판단

## 정상/비정상 판단

- healthy
- degraded
- unavailable
- `status.state=online`만으로 healthy 판단하지 않는 이유

## 현재 주의점

- 모든 device가 degraded로 보일 수 있는 이유
- fresh telemetry / fresh DeviceStatus가 dashboard 판단 근거라는 점
```

검증:

- dynamic offloading, placement, agent-assisted planning을 후속 계획처럼 표현하지 않는다.
- `docs/scope.md`, `docs/device-status-policy.md`, `docs/dashboard-policy.md`와 충돌하지 않는다.
- 문서 전체를 한국어로 작성한다. 단, 파일명, API path, 환경변수, Kubernetes resource 이름은 원문을 유지한다.

### 2단계: `docs/README.md`에 `current-demo-path.md` 연결

목적:

새 문서를 문서 진입점에서 찾을 수 있게 한다.

수정할 파일:

- `docs/README.md`

추가할 항목 예시:

```markdown
- `current-demo-path.md`: 현재 디바이스/MQTT/mapper/telemetry/state-aggregator/dashboard 연결 경로
```

권장 Active Guides 순서:

1. `scope.md`
2. `repo-structure.md`
3. `project-context.md`
4. `current-demo-path.md`
5. `device-status-policy.md`
6. `dashboard-policy.md`
7. `roadmap.md`

검증:

- `docs/README.md`를 읽어서 링크 설명이 현재 방향과 맞는지 확인한다.

### 3단계: `docs/device-service-binding.md` 작성

목적:

현재 PoC에서 디바이스와 서비스가 어떻게 연결되는지 운영/대시보드 관점에서 정의한다.
workflow/offloading 경로를 바인딩 모델로 쓰지 않는다.

생성할 파일:

- `docs/device-service-binding.md`

권장 목차:

```markdown
# Device-Service Binding

## 목적

디바이스가 어떤 서비스 데모와 연결되는지 운영/대시보드 관점에서 설명한다.

## 바인딩 원칙

- Device CR이 존재한다.
- Device가 특정 node에 할당된다.
- Device가 telemetry 또는 운영 snapshot을 제공한다.
- 서비스가 해당 device data를 사용하거나 관련 상태를 가진다.
- dashboard에서 이 관계를 볼 수 있다.

## 바인딩 필드

- device name
- device type
- nodeName
- service name
- service role
- input/output relation
- telemetry topic
- command topic
- dashboard display group
- KPI relation

## 바인딩 예시 표

| Device | Node | Service | Role | Data | Dashboard view |
|---|---|---|---|---|---|

## 제외하는 바인딩 방식

workflow_executor, placement_engine, dynamic offloading을 현재 바인딩 모델로 사용하지 않는다.
```

검증:

- 디바이스-서비스 관계를 직접적인 운영 관계로 설명한다.
- workflow scheduling 또는 offloading처럼 보이지 않게 한다.
- 문서는 한국어로 작성한다.

### 4단계: `docs/service-demo-scenario.md` 작성

목적:

현재 PoC에서 보여줄 서비스 데모 1종의 운영 시나리오를 정의한다.

생성할 파일:

- `docs/service-demo-scenario.md`

권장 목차:

```markdown
# Service Demo Scenario

## 목적

현재 PoC에서 보여줄 서비스 데모 1종의 운영 시나리오를 정의한다.

## 시나리오 개요

- 현장 문제
- 사용 디바이스
- 서비스 동작
- 관측 데이터
- 운영자 화면
- 생산성 향상 효과

## 구성 요소

- Jetson device
- Raspberry Pi device
- x86 server service
- state-aggregator
- dashboard

## 데모 흐름

1. Device가 사전 등록된다.
2. Device telemetry가 발행된다.
3. mapper가 telemetry를 수신한다.
4. raw telemetry가 InfluxDB에 저장된다.
5. DeviceStatus snapshot이 갱신된다.
6. state-aggregator가 상태를 통합한다.
7. dashboard가 서비스/디바이스 상태를 보여준다.
8. KPI를 통해 생산성 향상 효과를 설명한다.

## KPI 후보

- device live ratio
- telemetry freshness ratio
- service-device binding count
- operator focus count
- 이상 탐지/대응 시간, 필요 시

## 범위에서 제외하는 것

- 자동 workflow migration
- dynamic offloading
- agent-driven control
```

열린 질문:

- 서비스 데모의 정확한 주제와 이름은 사용자 확인이 필요할 수 있다.
  예: 설비 상태 모니터링, 진동 이상 감지, actuator command loop, visual inspection, Gemma 기반 서비스 등.

검증:

- 서비스 데모, 디바이스-서비스 연결 구조, 운영 가시화 중심으로 유지한다.
- 문서는 한국어로 작성한다.

### 5단계: `docs/dashboard-information-structure.md` 작성

목적:

대시보드가 어떤 정보를 보여줘야 하는지 운영 관점에서 정의한다.

생성할 파일:

- `docs/dashboard-information-structure.md`

권장 목차:

```markdown
# Dashboard Information Structure

## 목적

대시보드가 어떤 정보를 보여줘야 하는지 운영 관점에서 정의한다.

## 최상위 영역

- node overview
- device overview
- service binding overview
- telemetry freshness
- DeviceStatus freshness
- KPI panel
- operator focus / issue list

## API source mapping

| UI field | API/source | Meaning |
|---|---|---|

## Device status 해석

`docs/dashboard-policy.md` 기준을 따른다.

## KPI 해석

- registered_device_count
- operational_device_count
- live_device_count
- telemetry_device_count
- service-bound count

## naming 주의점

현재 API/UI에 `workflow_bound_device_count` 같은 이름이 남아 있다면, 현재 연구 방향에서는 workflow orchestration이 아니라 service binding 의미로 정리하거나 추후 rename을 검토한다.
```

검증:

- `docs/dashboard-policy.md`와 충돌하지 않는다.
- 아직 코드를 수정하지 않는다.
- 문서는 한국어로 작성한다.

### 6단계: `docs/ops/runbook-current-demo.md` 작성

목적:

현재 데모 경로를 실행하고 점검하는 절차를 정리한다.

생성할 파일:

- `docs/ops/runbook-current-demo.md`

권장 목차:

```markdown
# Current Demo Runbook

## 목적

현재 데모 경로를 실행하고 점검하는 절차를 정리한다.

## 사전 조건

- Kubernetes nodes Ready
- KubeEdge cloudcore Running
- Jetson/RPi edge mosquitto Running
- Jetson/RPi mqttvirtual mapper Running
- InfluxDB Running
- state-aggregator Running

## 점검 명령

- kubectl get nodes -o wide
- kubectl get pods -A -o wide
- kubectl get devices.devices.kubeedge.io -A
- kubectl get devicestatuses.devices.kubeedge.io -A

## Publisher 실행

- Jetson 경로
- Raspberry Pi 경로
- 단일 device filter

## API 점검

- /state/devices
- /state/dashboard

## Troubleshooting

- Device는 등록됐지만 degraded인 경우
- mapper는 Running이지만 InfluxDB telemetry가 없는 경우
- DeviceStatus가 stale인 경우
- node unavailable인 경우
```

검증:

- 파괴적 명령을 포함하지 않는다.
- 현재 정책과 맞는 실행/점검 명령만 포함한다.
- 문서는 한국어로 작성한다.

### 7단계: workflow 용어가 남아 있는 API/UI naming 검토

목적:

현재 연구 방향에서 제외된 workflow/offloading 의미가 API/UI 이름에 남아 있는지 확인한다.

나중에 검토할 파일:

- `edge-orch/state-aggregator/app/models.py`
- `edge-orch/state-aggregator/app/service.py`
- `edge-orch/state-aggregator/app/static/dashboard.js`
- `edge-orch/state-aggregator/tests/test_api.py`

가능한 이슈:

- `workflow_bound_device_count` 같은 이름이 현재 방향과 맞지 않을 수 있다.
- `service_connected`는 유지 가능하지만, 의미를 service binding으로 명확히 해야 한다.

원칙:

- 즉시 rename하지 않는다.
- 먼저 `docs/dashboard-information-structure.md`에 naming 주의점으로 기록한다.
- 실제 API/UI rename은 사용자 승인 후 별도 작업으로 진행한다.

## 변경 가능 파일

문서 파일:

- `docs/README.md`
- `docs/current-demo-path.md`
- `docs/device-service-binding.md`
- `docs/service-demo-scenario.md`
- `docs/dashboard-information-structure.md`
- `docs/ops/runbook-current-demo.md`

이미 변경된 파일:

- `docs/scope.md`
- `docs/repo-structure.md`
- `docs/roadmap.md`
- `docs/README.md`

사용자 승인 후 나중에 검토할 수 있는 코드 파일:

- `edge-orch/state-aggregator/app/models.py`
- `edge-orch/state-aggregator/app/service.py`
- `edge-orch/state-aggregator/app/static/dashboard.js`
- `edge-orch/state-aggregator/tests/test_api.py`

## 검증 방법

문서-only 단계 검증:

1. 생성한 markdown 파일을 읽어서 내용과 형식을 확인한다.
2. 다음 표현이 후속 계획처럼 남아 있는지 검색한다.
   - `후속 고도화`
   - `dynamic offloading`
   - `agent-assisted planning`
   - `완전 자율형`
   - `LLM이 전체 제어`
3. 제외 경로가 future work처럼 설명되지 않는지 확인한다.
4. `docs/README.md`에 active guide 링크가 빠지지 않았는지 확인한다.
5. 문서 본문이 한국어 중심으로 작성됐는지 확인한다.
   - 파일명, API path, 환경변수, Kubernetes resource 이름은 원문 유지 가능.

나중에 코드 변경이 생길 경우 검증:

```bash
cd /home/etri/jinuk/edge-orch/state-aggregator
PYTHONPATH=. .venv/bin/pytest -q tests
```

현재 기준 예상 결과:

```text
17 passed
```

## 위험 요소와 대응

1. 서비스 데모가 아직 정확히 확정되지 않은 상태에서 문서가 과도하게 구체화될 수 있다.
   - 대응: `service-demo-scenario.md`는 확정 항목과 후보 항목을 분리해서 작성한다.

2. 기존 API/UI에 workflow 용어가 남아 있어 현재 방향과 충돌할 수 있다.
   - 대응: 먼저 문서에 naming 주의점으로 기록하고, rename은 별도 승인 후 진행한다.

3. 제외/보관 경로가 레포 안에 그대로 있어 새 작업자가 혼동할 수 있다.
   - 대응: `repo-structure.md`와 이후 archive index에서 분류를 명확히 한다.

4. `docs/roadmap.md`에서 과거 연구 목표가 사라져 기존 보고 자료와 연결이 약해질 수 있다.
   - 대응: 필요하면 active roadmap이 아니라 archive note로 과거 방향 전환 사유를 남긴다.

5. `traefik/gemma-ingressroute.yaml`이 실수로 commit에 포함될 수 있다.
   - 대응: 사용자 확인 전에는 이번 문서 정리 commit에 포함하지 않는다.

## 열린 질문

1. 첫 번째 서비스 데모의 정확한 주제는 무엇인가?
   - 설비 상태 모니터링
   - 진동 이상 감지
   - actuator command loop
   - visual inspection
   - Gemma 기반 서비스
   - 기타

2. `workflow_bound_device_count`를 나중에 `service_bound_device_count`로 rename할지?

3. 제외된 코드 디렉터리를 현재 위치에 두고 README 경고만 추가할지, 나중에 archive 하위로 이동할지?

4. `edge-orch/gemma/`는 현재 서비스 데모 경로에 포함되는가, 아니면 별도 실험인가?

5. workflow/offloading/agent-assisted planning을 대체하는 새 연구 방향의 이름과 핵심 표현은 무엇인가?

## commit 묶음 제안

실행 단계에서 commit한다면 다음처럼 나눌 수 있다.

1. `docs: define project scope and repo structure`
   - `docs/scope.md`
   - `docs/repo-structure.md`
   - `docs/README.md`
   - `docs/roadmap.md`

2. `docs: document current demo path`
   - `docs/current-demo-path.md`
   - `docs/README.md`

3. `docs: define device-service binding and demo scenario`
   - `docs/device-service-binding.md`
   - `docs/service-demo-scenario.md`
   - `docs/README.md`

4. `docs: define dashboard information structure and demo runbook`
   - `docs/dashboard-information-structure.md`
   - `docs/ops/runbook-current-demo.md`
   - `docs/README.md`

주의:

- `traefik/gemma-ingressroute.yaml`은 사용자 확인 전에는 포함하지 않는다.
