# 현재 데모 경로 문서 작성 계획

## 목표

다음 작업은 `docs/현재-데모-경로.md`를 작성하는 것이다.

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에서 디바이스가 등록되고, telemetry가 들어오고, mapper와 InfluxDB/state-aggregator/dashboard로 이어지는 현재 데모 경로를 한국어로 정리한다.

이 작업은 전체 PoC 구현 과정 중 하나를 문서화하는 것이며, 특정 경로를 “제일 중요한 것”으로 표현하지 않는다.

## 현재 맥락

이미 정리된 기준 문서는 다음이다.

- `docs/프로젝트-범위.md`
  - 현재 PoC 범위와 제외 범위 정의
- `docs/저장소-구조.md`
  - 레포 디렉터리 역할 분류
- `docs/단계별-추진계획.md`
  - 현재 산출물과 단계별 작업 방향 정리
- `docs/물리-디바이스-상태-정책.md`
  - DeviceStatus와 raw telemetry 분리 정책
- `docs/대시보드-판단-정책.md`
  - dashboard의 상태 판단 기준
- `docs/프로젝트-배경.md`
  - 프로젝트 배경과 테스트베드 기준

현재 문서 작성 기준은 다음이다.

- 문서 본문은 한국어로 작성한다.
- 파일명, API path, 환경변수, Kubernetes resource 이름은 원문을 유지한다.
- workflow/offloading/agent-assisted planning은 현재 연구 방향의 후속 고도화로 표현하지 않는다.
- 해당 계열은 현재 데모 경로에서 제외된 과거 실험/보관 경로로만 다룬다.
- 현재 PoC는 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화, 실공장 기반 PoC, 현장 적용성, 생산성 향상 효과 중심으로 설명한다.

## 작성할 파일

- `docs/현재-데모-경로.md`

작성 후 연결할 파일:

- `docs/문서-안내.md`

## 제안 목차

`docs/현재-데모-경로.md`는 다음 구조로 작성한다.

```markdown
# Current Demo Path

## 목적

## 한 줄 요약

## 전체 흐름

## 구성 요소

### Device / DeviceModel

### MQTT topic

### 테스트 publisher

### mqttvirtual mapper

### DeviceStatus snapshot

### InfluxDB telemetry data-plane

### state-aggregator

### dashboard

## Jetson 경로

## Raspberry Pi 경로

## data-plane / status-plane 분리

## dashboard 상태 판단 기준

## degraded 상태가 나오는 대표 원인

## 현재 데모 경로에서 제외하는 것

## 관련 문서
```

## 포함할 핵심 내용

### 1. 전체 흐름

현재 데모 경로는 다음처럼 설명한다.

```text
physical / virtual device
  -> MQTT telemetry / command topic
  -> mqttvirtual mapper
  -> KubeEdge DeviceStatus snapshot
  -> InfluxDB raw telemetry data-plane
  -> state-aggregator
  -> dashboard / service demo view
```

단, 이 흐름은 전체 PoC 구현 과정 중 하나로 표현한다.

### 2. Device 등록 경로

포함할 내용:

- KubeEdge `DeviceModel` / `Device`는 현재 사전 등록 방식으로 운영한다.
- Jetson 디바이스는 `etri-dev0001-jetorn`에 할당한다.
- Raspberry Pi 디바이스는 `etri-dev0002-raspi5`에 할당한다.
- 등록 manifest 생성/관리 경로는 `edge-device/`를 기준으로 설명한다.

주의:

- 이 등록 경로를 프로젝트의 유일한 핵심으로 표현하지 않는다.
- “현재 데모를 구성하는 구현 경로 중 하나”로 표현한다.

### 3. MQTT topic 경로

포함할 topic:

```text
factory/devices/{device-name}/telemetry
factory/devices/{device-name}/command
factory/devices/{device-name}/heartbeat
```

설명 기준:

- `telemetry`: 디바이스 raw telemetry 입력 topic
- `command`: 제어/명령 topic
- `heartbeat`: 테스트 publisher 보조 heartbeat
- `heartbeat`는 KubeEdge Device manifest에 직접 연결하지 않는다고 명시한다.

### 4. 테스트 publisher 경로

포함할 파일:

- `mappers/script/test_device.py`

포함할 내용:

- 테스트 publisher는 실행한 서버의 local mosquitto `127.0.0.1:1883`로 publish한다.
- `DEVICE_PLAN=jetson`, `DEVICE_PLAN=rpi`, `DEVICE_PLAN=all` 같은 실행 기준을 문서화한다.
- `DEVICE_FILTER`를 사용해 일부 device만 publish할 수 있다는 점을 설명한다.
- command topic subscribe를 통해 `sampling_interval` 같은 설정을 반영할 수 있음을 설명한다.

### 5. mapper 경로

포함할 경로:

- `mappers/mqttvirtual/`
- `mappers/mqttvirtual/driver/driver.go`
- `mappers/mqttvirtual/resource/deployment.yaml`
- `mappers/mqttvirtual/resource/configmap.yaml`

포함할 내용:

- mapper는 MQTT broker에 연결한다.
- device telemetry topic을 subscribe한다.
- command topic으로 명령을 publish한다.
- KubeEdge DMI와 연동해 Device/DeviceStatus 계층과 연결된다.
- mapper pod의 Running 여부는 dashboard 판단의 입력 중 하나다.

### 6. DeviceStatus와 telemetry 분리

반드시 반영할 정책:

- raw telemetry 값을 DeviceStatus에 올리지 않는다.
- raw telemetry는 MQTT/InfluxDB data-plane으로 처리한다.
- DeviceStatus는 저빈도 운영 snapshot으로 제한한다.
- DeviceStatus에는 health/severity/alarm/power/mode/sampling_interval 같은 운영 상태 중심 값을 둔다.

참조 문서:

- `docs/물리-디바이스-상태-정책.md`

### 7. state-aggregator 경로

포함할 경로:

- `edge-orch/state-aggregator/`

포함할 API:

```text
GET /state/nodes
GET /state/devices
GET /state/dashboard
GET /state/summary
GET /metrics
```

포함할 내용:

- Kubernetes node 상태를 읽는다.
- KubeEdge Device / DeviceStatus를 읽는다.
- mapper pod Running 여부를 반영한다.
- InfluxDB latest telemetry freshness를 반영한다.
- Prometheus node metric을 보조 지표로 사용한다.
- dashboard에서 사용할 통합 상태를 만든다.

### 8. dashboard 상태 판단 기준

반드시 반영할 정책:

- `status.state=online`만으로 healthy 판단하지 않는다.
- DeviceStatus freshness와 telemetry freshness를 분리한다.
- mapper heartbeat freshness도 별도 입력으로 본다.
- fresh telemetry 또는 fresh DeviceStatus가 없으면 degraded로 보일 수 있다.

참조 문서:

- `docs/대시보드-판단-정책.md`

### 9. degraded 상태 의미

문서에 설명할 대표 원인:

- Device는 등록되어 있지만 live status가 unknown인 경우
- mapper는 Running이지만 InfluxDB에 fresh telemetry가 없는 경우
- DeviceStatus snapshot이 오래된 경우
- telemetry publisher가 실행되지 않았거나 local mosquitto로 publish되지 않은 경우
- node 또는 mapper 상태가 dashboard 기준과 맞지 않는 경우

주의:

- degraded는 반드시 시스템 전체 실패를 의미하지 않는다고 설명한다.
- “등록/mapper/API는 있으나 운영 가시화 판단에 필요한 fresh signal이 부족한 상태”로 설명한다.

### 10. 현재 데모 경로에서 제외하는 것

명시적으로 제외할 것:

- `edge-orch/workflow_executor/` 중심 동적 workflow 실행
- `edge-orch/workflow_reporter/` 중심 stage event pipeline
- `edge-orch/placement_engine/` 중심 자동 배치/재배치
- cost model 기반 runtime offloading 판단
- agent-assisted planning layer
- LLM이 전체 플랫폼 제어를 수행하는 구조
- 완전 자율형 orchestration

표현 원칙:

- 위 항목을 “후속 고도화” 또는 “다음 단계 핵심”으로 표현하지 않는다.
- 현재 연구 방향과 데모 경로에서는 제외된 과거 경로 또는 보관 경로로만 설명한다.

## `docs/문서-안내.md` 수정 계획

`docs/현재-데모-경로.md` 작성 후 `docs/문서-안내.md`의 Active Guides에 다음 항목을 추가한다.

```markdown
- `현재-데모-경로.md`: 현재 디바이스/MQTT/mapper/telemetry/state-aggregator/dashboard 연결 경로
```

권장 순서:

1. `프로젝트-범위.md`
2. `저장소-구조.md`
3. `프로젝트-배경.md`
4. `현재-데모-경로.md`
5. `물리-디바이스-상태-정책.md`
6. `대시보드-판단-정책.md`
7. `단계별-추진계획.md`

## 검증 계획

문서 작성 후 다음을 확인한다.

1. `docs/현재-데모-경로.md`가 한국어 본문으로 작성됐는지 확인한다.
2. `docs/문서-안내.md`에 새 문서가 Active Guides로 연결됐는지 확인한다.
3. 다음 표현이 부적절하게 남아 있지 않은지 확인한다.
   - `후속 고도화`
   - `완전 자율형`
   - `LLM이 전체 제어`
   - `동적 워크플로우 전체 구현 완료`
   - `agent-assisted planning을 다음 단계 핵심으로 추진`
4. raw telemetry를 DeviceStatus에 올리는 것처럼 설명하지 않았는지 확인한다.
5. `status.state=online`만으로 healthy 판단한다고 설명하지 않았는지 확인한다.
6. device/mapper/dashboard 경로를 “제일 중요한 것”으로 표현하지 않았는지 확인한다.
7. `traefik/gemma-ingressroute.yaml`은 건드리지 않았는지 확인한다.

## 예상 변경 파일

이번 실행 단계에서 변경할 파일:

- `docs/현재-데모-경로.md`
- `docs/문서-안내.md`

이번 실행 단계에서 건드리지 않을 파일:

- `traefik/gemma-ingressroute.yaml`
- `edge-orch/workflow_executor/`
- `edge-orch/workflow_reporter/`
- `edge-orch/placement_engine/`
- `workflow/`
- state-aggregator 코드 파일 전체

## 테스트 계획

이번 단계는 문서 작성이므로 코드 테스트는 필수는 아니다.

다만 나중에 state-aggregator 코드 변경이 생기면 다음 명령으로 검증한다.

```bash
cd /home/etri/jinuk/edge-orch/state-aggregator
PYTHONPATH=. .venv/bin/pytest -q tests
```

현재 기준 통과 상태는 다음으로 파악되어 있다.

```text
17 passed
```

## 위험 요소

1. 현재 데모 경로를 너무 구현 세부사항 중심으로 설명할 수 있다.
   - 대응: 서비스 데모와 운영 가시화 관점에서 설명한다.

2. workflow/offloading/agent-assisted planning 표현이 다시 future work처럼 들어갈 수 있다.
   - 대응: 제외 항목으로만 작성하고 후속 계획으로 표현하지 않는다.

3. DeviceStatus와 telemetry data-plane 경계가 흐려질 수 있다.
   - 대응: `docs/물리-디바이스-상태-정책.md` 기준을 그대로 따른다.

4. dashboard healthy/degraded 판단이 단순화될 수 있다.
   - 대응: `docs/대시보드-판단-정책.md` 기준을 그대로 따른다.

## 열린 질문

이번 `docs/현재-데모-경로.md` 작성에는 큰 추가 확인이 필요하지 않다.

다만 다음 문서인 `docs/서비스-데모-시나리오.md` 작성 전에는 대표 서비스 데모 주제를 확정해야 한다.

후보:

- 설비 상태 모니터링
- 진동 이상 감지
- actuator command loop
- visual inspection
- Gemma 기반 현장 지원 서비스
- 기타

## 다음 단계

사용자가 실행을 요청하면 다음 순서로 진행한다.

1. `docs/현재-데모-경로.md` 작성
2. `docs/문서-안내.md` Active Guides에 연결
3. 작성 파일 읽어서 검증
4. `git diff -- docs/현재-데모-경로.md docs/문서-안내.md | cat`으로 변경 내용 확인
5. 결과 요약
