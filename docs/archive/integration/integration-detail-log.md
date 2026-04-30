# 통합문서

이 문서는 저장소 전반의 핵심 문서를 한 번에 읽을 수 있도록 정리한 통합 참조본이다.
기존 원본 문서를 대체하지 않으며, 개요부터 구현 우선순위와 논문 전략까지 한 흐름으로 파악하는 데 목적이 있다.

## 0. 빠른 요약

- 프로젝트 성격: 이기종 혼합 디바이스 엣지 AI를 위한 런타임 오케스트레이션
- 핵심 방법: 워크플로우를 stage 단위로 분해하고, runtime 상태 기반으로 배치/오프로딩/재계획 수행
- 현재 강점: 상태 수집(State Aggregator), GitOps/CI 파이프라인, heuristic 배치 엔진
- 현재 병목: 20개 병렬 가상 디바이스 구간에서 `mqttvirtual` 매퍼 안정성
- 다음 우선순위: 실 워크플로우 1개 E2E 통합 -> handoff 정교화 -> overload/burst 재계획 고도화

원본 문서:
- `AGENTS.md`
- `docs/archive/legacy-orchestration/system-overview.md`
- `docs/archive/legacy-orchestration/architecture.md`
- `docs/research/research-topics.md`
- `docs/research/paper-strategy.md`
- `docs/research/venue-strategy.md`
- `docs/research/evaluation-plan.md`
- `docs/research/writing-checklist.md`
- `docs/troubleshooting-network.md`

---

## 1. 프로젝트 정체성

이 저장소는 KubeEdge/Kubernetes 기반의 혼합 디바이스 엣지 AI 환경을 위한 런타임 오케스트레이션 시스템을 다룬다.

대상 환경:
- x86 제어/클라우드 서버
- x86 워커 서버
- Jetson 엣지 AI 디바이스
- Raspberry Pi 5 엣지 디바이스

핵심 목표:
- AI 서비스를 워크플로우 단계로 분해한다.
- 노드 상태와 워크플로우 실행 상태를 관측한다.
- 단계별 배치, 마이그레이션, 오프로딩을 동적으로 수행한다.
- 필요한 경우에만 보조적인 agent-assisted replanning을 추가한다.

이 시스템은 다음이 아니다.
- 범용 Kubernetes 스케줄러
- full agentic AI operating system
- Prometheus/Grafana 대체 시스템
- observability platform 중심 논문

이 시스템의 지향점은 다음과 같다.
- workflow-aware
- state-aware
- heterogeneity-aware
- dynamic offloading 중심
- mixed-device edge AI workflow 중심

---

## 2. 프로젝트의 핵심 문제

실제 엣지 환경은 강한 이기종성을 가진다.

- 아키텍처가 다르다: `amd64`, `arm64`
- 가속기 구성과 성능이 다르다
- 메모리 용량과 연산 능력이 다르다
- 네트워크 상태가 다르다
- 단계별 병목 위치가 계속 달라진다

이 때문에 다음 문제가 생긴다.

- 정적 배치는 금방 비효율적이 된다.
- 특정 노드만 병목이 되고 다른 노드는 쉬게 된다.
- CPU/메모리만 보는 단순 규칙으로는 실제 서비스 지연을 설명하기 어렵다.
- AI 서비스를 하나의 단일 단위로 취급하면 세밀한 오프로딩이 어렵다.

따라서 서비스는 다음과 같은 단계로 분해해 다뤄야 한다.

- capture
- preprocess
- inference
- postprocess
- result delivery

핵심 질문:
- 어떤 단계는 소스 디바이스 근처에 둬야 하는가
- 어떤 단계는 Jetson으로 보내야 하는가
- 어떤 단계는 서버로 보내야 하는가
- 언제 재배치해야 하는가
- 과부하, 버스트, SLA 위험에서 어떤 정책이 필요한가

---

## 3. 연구 북극성과 논문 중심축

핵심 논문 중심 문장은 다음과 같다.

**이기종 혼합 디바이스 엣지 AI 워크플로우를 위한 런타임 오케스트레이션**

논문 구조는 다음 축으로 설명한다.
1. workflow-stage decomposition
2. runtime state collection and normalization
3. stage-level placement / replanning / offloading
4. real mixed-device testbed validation

헤드라인 기여:
- runtime orchestration system
- stage-level dynamic placement and replanning
- mixed-device workflow execution under heterogeneous runtime conditions

부차적 기여:
- decision explanation
- 선택적 agent-assisted replanning
- burst/overload 상황용 planning layer

헤드라인에서 피해야 할 것:
- LLM autonomy
- generic AI agent control
- RL-first control logic
- eBPF telemetry 중심 논문화
- full edge-cloud observability platform 주장

---

## 4. 현재 구현 상태와 다음 우선순위

### 현재까지 완료된 큰 축
1. State Aggregator 및 Monitoring
   - Prometheus 메트릭과 workflow event를 수집하는 중심 허브 구현
   - 노드/워크플로우 정규화 상태 제공
2. GitOps 및 배포 자동화
   - ArgoCD 연동
   - ArgoCD Image Updater 연동
3. CI/CD
   - GitHub Actions multi-arch build
   - self-hosted runner 연동
4. Workflow Executor 개선
   - SQLite 기반 이력 저장
   - dynamic Job의 `image_pull_policy: Always`
5. Heuristic Placement Engine
   - 이기종 환경용 weighted score 기반 배치 로직

### 즉시 다음 단계
1. 실제 AI 워크플로우 1개를 강하게 연결
2. 단계 간 데이터 전달 경로 정리
3. live node-state 기반 runtime replanning 강화

### 구현 우선순위
1. `state_aggregator`
2. `workflow_reporter`
3. `placement_engine`
4. one real workflow integration
5. handoff/data-passing layer
6. replanning under overload/burst
7. optional agent-assisted planning layer

### 4.1 가상 디바이스 PoC 진행 상태

KubeEdge 기반 mixed-device 제어·관리 플랫폼의 디바이스 계층 검증을 위해, `2026-04` 기준으로 MQTT 기반 가상 디바이스 PoC를 별도 진행했다.

목표:
- 물리/가상 혼합 디바이스 관리 구조 검증
- DeviceTwin 기반 상태 반영 검증
- 컨테이너 단위 가상 디바이스 개발 및 병렬 실행 구조 검증

현재 PoC 설계:
- 가상 디바이스 종류 3개
  - `env`: `temperature`, `humidity`
  - `vib`: `vibration`, `alarm`
  - `act`: `power`, `mode`
- 총 20개 인스턴스
  - `env-device-01` ~ `env-device-08`
  - `vib-device-01` ~ `vib-device-06`
  - `act-device-01` ~ `act-device-06`
- 구현 방식
  - 공통 컨테이너 이미지 1개
  - `StatefulSet` 3개
  - `DeviceModel` 3개
  - `Device` 20개

실행 구조:
- edge node의 MQTT broker를 사용한다.
- 컨테이너는 `HOST_IP:1883` 으로 edge broker에 연결한다.
- topic 규칙은 `factory/devices/<device_id>/telemetry`, `factory/devices/<device_id>/command` 로 고정한다.
- Pod 이름 ordinal을 이용해 `device_id` 를 계산한다.

현재 확인된 것:
- `virtual-device` 이미지를 `192.168.0.56:5000/virtual-device:latest` 로 빌드/배포할 수 있다.
- edge node(`etri-dev0001-jetorn`) 에서 가상 디바이스 Pod가 실제로 MQTT telemetry를 발행한다.
- `mqttvirtual` mapper를 통해 `temp-device-01` 단일 PoC는 `DeviceStatus` 기준 reported 값 반영까지 검증했다.
- `cloudcore` 의 `devicestatuses.devices.kubeedge.io` RBAC 부족 문제를 수정해 `DeviceStatus` CR 생성 경로를 복구했다.

현재 남은 병목:
- 20개 병렬 가상 디바이스에서는 `mqttvirtual` mapper가 불안정하다.
- 관찰된 주요 증상:
  - `broken pipe`
  - `use of closed network connection`
  - `deviceModel ... not found`
  - `dial unix /etc/kubeedge/mqttvirtual.sock: connect: connection refused`
- 현재 분석상 병목은 KubeEdge 자체보다 `mqttvirtual` 매퍼 구현 구조에 가깝다.
  - 디바이스별 MQTT client 생성
  - 초기 desired write 시도
  - subscribe/publish 경로의 연결 충돌 가능성

현재 해석(요약):
- 현재 PoC는 "가상 디바이스 컨테이너 병렬 실행" 과 "단일 디바이스 DeviceStatus 반영" 까지는 검증되었다.
- "20개 병렬 인스턴스의 안정적 DeviceTwin 반영" 은 mapper 구조 개선이 필요한 다음 단계다.

### 4.2 `mqttvirtual` DeviceStatus 안정화 정책

`2026-04-24` 기준으로 `mqttvirtual` mapper와 가상 디바이스 구성을 DeviceStatus 부하를 줄이는 방향으로 재정리했다.

배경:
- `ReportDeviceStates` 경로에서 다음 rate limit 오류가 관찰되었다.
  - `fail to report device states because of too many request`
- 이 오류는 `DeviceStatus.status.twins.reported` 값 자체보다, 각 디바이스의 online/offline/unknown 같은 device state를 너무 자주 또는 동시에 보고하는 문제에 가깝다.
- 따라서 DeviceStatus를 raw telemetry 저장소로 쓰지 않고, 운영자가 볼 요약 상태만 올리는 방향으로 정리한다.

적용 원칙:
1. DeviceStatus 보고 대상 allowlist를 축소한다.
2. `vibration`, `temperature`, `humidity` 같은 raw value는 DeviceStatus에서 제거한다.
3. `last_seen`은 timestamp 원문이 아니라 `health` 상태로 축약한다.
4. `alarm`은 즉시 raw boolean으로 올리지 않고 debounce/hysteresis 후 `severity`, `alarm_latched`로 축약한다.
5. raw telemetry는 `pushMethod.mqtt` 또는 별도 MQTT/DB consumer 경로로 저장한다.
6. `ReportDeviceStatus`는 상태 전이 또는 저빈도 flush 중심으로 수행한다.
7. `ReportDeviceStates`는 병렬 PoC 안정화 단계에서는 기본적으로 끈다.

현재 로컬 반영:
- `mappers/mqttvirtual/device/device.go`
  - DeviceStatus twin reported allowlist를 `health`, `severity`, `alarm_latched`, `power`, `mode`, `sampling_interval` 중심으로 제한했다.
  - raw telemetry key는 allowlist에서 제외했다.
- `edge-device/models/`
  - `virtual-env-model`: `health`, `sampling_interval`을 대표 상태로 둔다.
  - `virtual-vib-model`: `severity`, `alarm_latched`, `health`, `sampling_interval`을 대표 상태로 둔다.
  - `virtual-act-model`: `power`, `mode`, `health`, `sampling_interval`을 대표 상태로 둔다.
- `edge-device/scripts/generate_devices.py`
  - 20개 Device manifest 생성 시 raw telemetry는 `reportToCloud: false`로 둔다.
  - 대표 상태만 `reportToCloud: true`로 둔다.
  - 각 Device의 `status.reportToCloud`는 `false`로 둔다.
- `edge-device/scripts/deploy.sh`
  - apply 이후 status subresource도 `reportToCloud: false`, `reportCycle: 60000`으로 patch한다.
- `mappers/script/test_device.py`
  - MQTT payload에는 raw telemetry와 요약 상태를 함께 발행한다.
  - vibration raw 값은 유지하되, debounce/hysteresis를 거쳐 `severity`, `alarm_latched`, `health`를 생성한다.

권장 DeviceStatus 의미:
- `health`: `ok` / `degraded` / `offline` / `unknown`
- `severity`: `normal` / `warning` / `critical`
- `alarm_latched`: `true` / `false`
- `power`: `on` / `off`
- `mode`: `auto` / `manual` / `idle`
- `sampling_interval`: command/desired 반영 여부 확인용 저빈도 상태

이 구성의 목적:
- KubeEdge DeviceStatus는 운영 상태 요약과 디바이스-서비스 연결 가시화에 사용한다.
- 센서 원문 데이터는 별도 data plane으로 흘려 서비스 입력, KPI 계산, DB 저장에 사용한다.
- 20개 병렬 디바이스에서 edgecore/cloudcore의 DeviceStatus 요청 rate limit에 걸리지 않도록 한다.

---

## 5. 시스템 구성요소

### 5.1 `state_aggregator`
역할:
- Prometheus에서 노드 메트릭 수집
- workflow/stage event 수신
- 정규화 상태 생성
- 경량 API 제공

제약:
- Python 구현
- FastAPI 선호
- Kubernetes Deployment
- 서버 노드 우선 배치
- 최신 상태는 메모리 유지
- raw event는 JSONL 저장
- 초기 버전에서 Redis/Postgres 같은 복잡한 DB는 도입하지 않음

### 5.2 `workflow_reporter`
역할:
- workflow/stage 실행 이벤트 발생
- `stage_start`, `stage_end`, `migration_event`, `workflow_end`, `failure_event` 전송

제약:
- Python helper/module 우선
- HTTP POST로 aggregator에 전달
- 이벤트 스키마는 작고 명시적으로 유지

### 5.3 `placement_engine`
역할:
- 단계별 placement, migration, offloading 판단
- node profile, runtime state, stage metadata를 결합한 의사결정 수행

제약:
- Python module 우선
- heuristic / weighted score 기반 시작
- machine-readable decision reason 반환
- 초기에는 RL/LLM 제어 금지

### 5.4 `agent_assisted_planner`
역할:
- 후순위, 선택적 계층
- 정상 상태가 아니라 replanning이 필요한 상황에서만 개입

---

## 6. 노드와 역할

### 서버 1
- hostname: `etri-ser0001-CG0MSB`
- role: `cloud_server`
- arch: `amd64`
- preferred for:
  - heavy inference
  - centralized state aggregation
  - placement engine
  - planner candidate

### 서버 2
- hostname: `etri-ser0002-CGNMSB`
- role: `cloud_worker`
- arch: `amd64`
- preferred for:
  - heavy inference
  - large-scale preprocessing
  - redundant execution capacity

### Jetson
- hostname: `etri-dev0001-jetorn`
- role: `edge_ai_device`
- arch: `arm64`
- preferred for:
  - edge inference
  - preprocess
  - latency-sensitive stages

### Raspberry Pi 5
- hostname: `etri-dev0002-raspi5`
- role: `edge_light_device`
- arch: `arm64`
- preferred for:
  - capture
  - lightweight preprocess
  - sensor ingestion
  - lightweight postprocess

---

## 7. 노드 실측 사양

아래 표는 `2026-04-10` 기준으로 직접 확인한 실측 사양이다.
확인 방식은 서버 1 로컬 명령과 `kubectl get node`, `kubectl debug node/... -- chroot /host ...`를 사용했다.

| 노드 | hostname | OS | CPU | 코어/스레드 | RAM | GPU/NPU | 비고 |
|---|---|---|---|---|---|---|---|
| 서버 1 | `etri-ser0001-CG0MSB` | `Ubuntu 24.04.3 LTS` | `12th Gen Intel(R) Core(TM) i9-12900KS` | 16코어 / 24스레드 | 약 `125 GiB` | `NVIDIA GeForce RTX 5060 Ti` (`8151 MiB`, driver `580.126.09`) | `nvidia.com/gpu=1`, 메인 제어/추론 서버 |
| 서버 2 | `etri-ser0002-CGNMSB` | `Ubuntu 24.04.4 LTS` | `Intel(R) Core(TM) Ultra 9 285` | 24코어 / 24스레드 | 약 `30 GiB` | `NVIDIA GeForce RTX 5080` (`16303 MiB`, driver `580.126.09`) | `nvidia.com/gpu=1`, Kubernetes GPU 노출 정상화 완료 |
| Jetson | `etri-dev0001-jetorn` | `Ubuntu 22.04.5 LTS` | `Cortex-A78AE` | 6코어 / 6스레드 | 약 `7.4 GiB` | `NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super` 내장 GPU | `nvidia-l4t 36.4.7` 확인 |
| Raspberry Pi 5 | `etri-dev0002-raspi5` | `Debian GNU/Linux 13 (trixie)` | `Cortex-A76` | 4코어 / 4스레드 | 약 `15 GiB` | 전용 AI 가속기 없음, GPU 모델 미확인 | 보드 모델 `Raspberry Pi 5 Model B Rev 1.1` 확인 |

추가 메모:
- 서버 1과 서버 2 모두 현재 Kubernetes에서 `nvidia.com/gpu=1`로 노출된다.
- 서버 2는 예전 GPU Operator 잔재를 정리한 뒤, 최소 `device plugin` 경로로 GPU 노출을 복구했다.
- Jetson과 Raspberry Pi는 ARM 계열 edge 장비이며, 실제 테스트베드 이기종성을 보여주는 핵심 노드다.

---

## 8. 기술 원칙

### 모니터링
재사용 대상:
- Prometheus
- Grafana
- node-exporter

원칙:
- 기본 노드 모니터링을 새로 만들지 않는다.
- Prometheus를 node-level raw metric source로 사용한다.
- `node_monitor.py` 같은 별도 host-level 수집 경로를 기본 경로로 두지 않는다.

### 상태 모델
분리해야 하는 상태:
- raw metrics
- normalized node state
- workflow execution state
- placement decision

### 배치 로직
초기 방식:
- heuristic / weighted scoring
- explicit node capability profile
- decision reason output

하지 말 것:
- RL-first control
- LLM-first scheduling
- black-box policy learning

### 데이터 전달
권장 계층:
- same-node hot path: local ephemeral storage
- cross-node artifact handoff: shared artifact store such as MinIO
- workflow/state handoff: Redis or equivalent fast state layer

원칙:
- Redis를 bulk artifact store로 사용하지 않는다.

---

## 9. API, 이벤트, 메트릭

### `state_aggregator` 필수 API
- `POST /workflow-event`
- `GET /state/nodes`
- `GET /state/node/{hostname}`
- `GET /state/workflows`
- `GET /state/workflow/{workflow_id}`
- `GET /state/summary`

### `workflow_reporter` 필수 이벤트
- `stage_start`
- `stage_end`
- `migration_event`
- `workflow_end`
- `failure_event`

### Prometheus 최소 질의
- node health via `up`
- CPU utilization
- memory usage ratio
- load average
- network receive/transmit rate

추가 원칙:
- `instance -> hostname` 매핑 파일을 명시적으로 유지한다.

---

## 10. 상위 수준 아키텍처 흐름

### 입력 경로
1. Prometheus / node-exporter가 raw node metric 제공
2. workflow_reporter가 workflow/stage event 전송

### 상태화 경로
3. state_aggregator가 metric과 event를 결합
4. normalized state와 workflow state를 생성

### 제어 경로
5. placement_engine이 placement/replanning 판단
6. 필요 시 executor가 새로운 배치 실행
7. 급격한 상황에서만 optional planning layer 개입

요약 루프:

`monitor -> normalize -> place -> execute -> feedback -> replan`

---

## 11. 정규화 상태 모델

### 노드 수준 상태 예시
- `compute_pressure`: `low` / `medium` / `high`
- `memory_pressure`: `low` / `medium` / `high`
- `network_pressure`: `low` / `medium` / `high`
- `node_health`: `healthy` / `degraded` / `unavailable`

### 워크플로우 수준 상태 예시
- `workflow_urgency`
- `sla_risk`
- `placement_stability`

### 노드 capability profile 예시 필드
- `hostname`
- `node_type`
- `arch`
- `compute_class`
- `memory_class`
- `accelerator_type`
- `runtime_role`
- `preferred_workload`
- `risky_workload`

---

## 12. 초기 배치 규칙 예시

- heavy inference는 서버 우선
- 데이터 소스 인접 stage는 Raspberry Pi 우선
- GPU-required stage는 서버 또는 Jetson만 허용
- memory pressure가 높은 노드에는 heavy stage를 새로 주지 않음
- unavailable node는 절대 선택하지 않음
- overload 시 sibling edge redistribution 또는 cloud offloading을 검토

예시 비용 함수:

`Cost(stage, node) = compute_delay + transfer_cost + memory_pressure + migration_penalty`

---

## 13. 논문 전략

### 가장 중요한 원칙
논문의 중심은 runtime orchestration 하나로 모은다.

동시에 메인으로 올리면 안 되는 것:
- agent-assisted planning
- RL scheduling
- eBPF telemetry
- distributed data middleware
- generic orchestration platform

### 리뷰어가 가져가야 하는 한 문장
실제 mixed-device edge AI 환경에서 워크플로우 단계를 이기종 노드에 동적으로 배치하고, 런타임 변화에 따라 재계획하는 시스템을 제시한다.

### 범위를 줄일 때 유지할 것
- workflow DAG / ordered stage
- stage-level dynamic offloading
- node capability profile
- normalized runtime state
- runtime replanning
- 실제 mixed-device testbed

### 미루거나 자를 것
- full agentic control plane 주장
- telemetry 자체를 메인 주제로 삼는 방향
- broad digital-twin 서사
- 얕은 다수 워크플로우

### 권장 핵심 기여 3개
1. mixed-device edge AI workflow용 runtime orchestration architecture
2. heterogeneity-aware stage-level placement and replanning
3. x86 + Jetson + Raspberry Pi 기반 실제 평가

선택적 4번째:
- burst/overload 상황용 제한적 agent-assisted replanning

---

## 14. 투고처 전략

### 가장 적합한 venue 해석
이 연구는 다음으로 읽혀야 한다.
- edge systems
- runtime orchestration
- heterogeneous resource management
- workflow-stage placement and offloading

다음으로 읽히면 안 된다.
- generic AI agents
- telemetry portability
- pure networking
- generic cloud management
- observability platform

### 적합한 순위
학회:
1. SEC
2. Middleware
3. SoCC
4. NSDI

저널:
1. FGCS
2. IEEE Access
3. IEEE Internet of Things Journal

### 추천 경로
- conference-first: `SEC -> Middleware -> FGCS/IEEE Access`
- publication-probability-first: `IEEE Access -> FGCS`

### 선택 기준
- edge AI workflow orchestration이 가장 강하면 `SEC`
- runtime control plane과 architecture가 가장 강하면 `Middleware`
- 더 넓은 설명과 평가가 필요하면 `FGCS`
- 채택 확률 우선이면 `IEEE Access`

원칙:
- 먼저 venue를 정하고 기여를 비틀지 않는다.
- 먼저 논문의 실제 중심을 고정한다.

---

## 15. 평가 계획

### 핵심 질문
이기종성 인지형 runtime orchestration이 정적 배치와 단순 heuristic보다 실제 런타임 변화에서 더 나은가?

### 테스트베드
- x86 cloud/control node
- x86 worker node
- Jetson edge node
- Raspberry Pi edge node

### 주력 워크플로우
하나를 깊게 판다.

권장:
- 스마트팩토리 비전 파이프라인

권장 stage:
1. capture
2. preprocess
3. inference
4. postprocess
5. result delivery

### baseline
1. 정적 배치
2. 단순 heuristic 배치
3. stage-level runtime orchestration
4. stage-level runtime orchestration + replanning
5. optional planning layer는 충분히 성숙할 때만 추가

### 시나리오
- 정상 부하
- 버스트 부하
- 지속 과부하
- transfer-stress
- node degradation / partial unavailability

### 필수 지표
- end-to-end latency
- p95 / p99 latency
- makespan
- workflow completion time
- CPU utilization
- memory pressure
- network throughput
- placement decision latency
- migration / reassignment count
- failed or unstable placement
- orchestration overhead

### 필수 ablation
- heterogeneity awareness 없음
- stage decomposition 없음
- replanning 없음
- transfer-cost term 없음
- memory-pressure term 없음

### 최소 publishable evidence
1. 정적 배치는 충분하지 않다.
2. stage-level orchestration이 도움이 된다.
3. heterogeneity-aware placement가 도움이 된다.
4. runtime replanning이 도움이 된다.
5. overhead가 허용 가능하다.

---

## 16. 논문 작성 체크리스트

### 문제 정의
- 문제를 한 문장으로 분명히 썼는가
- 왜 정적 배치가 실패하는지 설명했는가
- 왜 이기종성이 중요한지 설명했는가
- 왜 stage-level orchestration이 필요한지 설명했는가

### 기여 통제
- 메인 기여가 3개로 정리되어 있는가
- runtime orchestration이 중심인가
- agent-assisted planning이 부차적인가
- telemetry, RL, 기타 부가 주제가 중심에서 내려가 있는가

### 시스템 명확성
- 아키텍처가 명확한가
- monitoring / control / data path가 분리되었는가
- placement/replanning loop가 분명한가
- 노드 역할과 workflow stage가 명시적인가

### 평가 품질
- 실제 mixed-device testbed가 있는가
- 강한 실제 workflow가 있는가
- baseline이 충분한가
- overload/burst 시나리오가 있는가
- orchestration overhead를 측정했는가
- ablation study가 있는가

### claim 통제
- 모든 claim이 실험으로 뒷받침되는가
- marketing 문장을 피했는가
- `full agentic system` 같은 표현을 피했는가
- Kubernetes나 Prometheus 대체를 주장하지 않는가

### 최종 sanity check
- 리뷰어가 한 문장으로 요약해도 내가 의도한 문장과 같은가
- novelty line이 정확히 하나인가
- optional feature를 빼도 논문이 강하게 서는가

---

## 17. 운영 및 문서 원칙

코드와 문서를 다룰 때의 기본 원칙:
- read first, change later
- working path를 불필요하게 깨지 않는다
- publishability를 올리지 않는 scope 확장은 피한다
- 제안이나 변경은 main paper story를 강화하는 방향이어야 한다
- novelty sprawl이 생기면 더 좁고 강한 쪽을 선택한다

코딩 원칙:
- 컴포넌트는 작고 테스트 가능하게 유지
- explicit schema 선호
- placement logic은 decision reason을 반환
- raw metrics와 normalized state 분리
- monitoring path와 control path 분리
- data plane과 control/state plane 분리
- broad refactor보다 small delta 선호

### 새 노드 조인 체크
새 노드를 클러스터에 붙인 뒤에는 아래 프리플라이트 스크립트로 상태를 먼저 확인한다.

- [scripts/check-worker-node-join.sh](/home/etri/jinuk/edge-orch/scripts/check-worker-node-join.sh)
- [docs/ops/node-join-check.md](/home/etri/jinuk/docs/ops/node-join-check.md)
- [scripts/check-edgecore-node.sh](/home/etri/jinuk/edge-orch/scripts/check-edgecore-node.sh)
- [docs/ops/edge-node-join-check.md](/home/etri/jinuk/docs/ops/edge-node-join-check.md)
- [scripts/check-pod-connectivity.sh](/home/etri/jinuk/edge-orch/scripts/check-pod-connectivity.sh)
- [docs/ops/pod-connectivity-check.md](/home/etri/jinuk/docs/ops/pod-connectivity-check.md)

예시:

```bash
bash scripts/check-worker-node-join.sh etri-ser0002-cgnmsb
```

GPU까지 확인하려면:

```bash
bash scripts/check-worker-node-join.sh --check-gpu etri-ser0002-cgnmsb
```

edgecore 노드는 전용 스크립트 사용:

```bash
bash scripts/check-edgecore-node.sh etri-dev0001-jetorn
```

실제 same-node / cross-node 파드 간 통신은 별도 스크립트로 확인:

```bash
bash scripts/check-pod-connectivity.sh etri-ser0002-cgnmsb etri-ser0001-cg0msb
```

이 스크립트는 다음 항목을 한 번에 본다.

- 노드 `Ready`
- `kube-dns` 서비스/엔드포인트
- 해당 노드의 `kube-proxy`
- 해당 노드의 `edgemesh-agent`
- host와 pod 내부의 DNS 해석
- `br_netfilter`, `xt_physdev`
- `bridge-nf-call-iptables`, `ip_forward`
- 기본값에서는 공통 네트워크/서비스 체크만 수행
- `--check-gpu` 옵션일 때 NVIDIA 노드의 `/dev/nvidia*`, `nvidia.com/gpu`, GPU smoke pod까지 확인
- edge node는 `check-edgecore-node.sh`로 `edgecore`, `cloudcore`, `edgemesh` 경로를 별도로 확인
- 실제 파드 간 통신은 `check-pod-connectivity.sh`로 same-node / cross-node를 별도 검증

이 체크는 우리가 실제로 겪었던 조인 후 문제를 빠르게 잡기 위해 추가했다.
- DNS VIP timeout
- EdgeMesh DNS 프록시 이상
- `kube-proxy`의 `iptables-restore` 실패
- 커널 모듈/브리지 설정 누락
- GPU 노드의 Kubernetes 미노출 상태

---

## 18. 네트워크/클러스터 트러블슈팅 기록

새 워커 노드 `etri-ser0002-cgnmsb` 추가 후 다음 문제가 있었다.

증상:
- Kubernetes API 서버 연결 실패
- cluster-wide DNS failure
- EdgeMesh `peer id mismatch`
- `physdev match missing`로 인한 `iptables` 설치 실패

핵심 원인:
1. CoreDNS가 미구성 새 노드에 먼저 올라간 순환 의존성
2. EdgeMesh relay peer ID 불일치
3. `br_netfilter`, `xt_physdev` 등 호스트 커널 설정 미비

복구 절차:
1. CoreDNS를 안정적인 control-plane 노드에 pin
2. `edgemesh-agent-cfg`에서 relay 정보 수정 후 agent 재시작
3. 호스트에 필요한 kernel module 및 sysctl 적용

예방 수칙:
- DNS, Registry 같은 핵심 인프라는 안정 노드에 고정
- 노드 provisioning 시 `br_netfilter` 포함
- relay 서버 변경 후 Peer ID 재확인

---

## 19. 최종 요약

이 저장소의 중심은 mixed-device edge AI workflow를 위한 runtime orchestration system이다.
가장 중요한 것은 다음 세 가지다.

1. 상태를 제대로 수집하고 정규화하는 것
2. 단계 수준 배치와 재계획을 이기종성 인지형으로 수행하는 것
3. 실제 mixed-device testbed에서 강한 평가로 증명하는 것

agent-assisted planning, telemetry, RL, data middleware는 모두 부가 축이다.
이 문서를 기준으로 읽으면 프로젝트 개요, 구현 방향, 논문 framing, venue 전략, 평가 계획, 작성 체크리스트, 운영 이슈를 한 번에 따라갈 수 있다.

---

## 20. 구축 진행 중 이슈 현황 (2026-04-20)

이 절은 실험 구축 과정에서 발생한 KubeEdge DeviceTwin 반영 이슈를 기록한다.
핵심은 MQTT 수신 문제가 아니라 edgecore ↔ mapper 동기화 경로 문제를 코드/로그 기반으로 분리하는 것이다.

### 20.1 현재 실험 환경

- Control/Cloud Plane: `192.168.0.56`
- Jetson Edge Node: `192.168.0.3`
- Raspberry Pi 5 Edge Node: `192.168.0.4`
- Kubernetes + KubeEdge + Flannel + EdgeMesh 기반 mixed-device 클러스터

### 20.2 관측된 현상 (사실)

- `mqttvirtual` 매퍼의 등록 자체는 성공 로그가 확인되었다.
- Jetson에서 MQTT telemetry 수신 로그(예: temperature, sampling_interval 값 읽기)가 확인되었다.
- Kubernetes의 DeviceModel/Device CR은 존재한다.
- 그러나 `kubectl get device temp-device-01 -n default -o json | jq '.status, .status.twins'` 결과가 지속적으로 `null` 이다.
- edgecore 측에서 다음 에러가 반복되었다.
   - `Update twin rejected due to the device default/temp-device-01 is not existed`
   - `can not find device default/temp-device-01 from device muxs`

### 20.3 이미 배제된 항목

- 과거 `mqtt connect failed: ... missing address` 는 오래된 바이너리/소스 이슈로 정리되었고, 현재 핵심 병목이 아니다.
- `common.ProtocolCustomized` 문자열 자체는 우선순위 낮은 원인으로 판단한다(해당 필드가 핵심 처리 경로에서 직접 사용되지 않는 코드 경로 확인).

### 20.4 현재 원인 가설

1. edgecore에서 mapper gRPC `RegisterDevice` / `UpdateDevice` 호출이 기대대로 들어오지 않는다.
2. 호출은 들어오지만 mapper 내부 `deviceMuxs` 등록/유지에 실패한다.
3. `namespace/name` 기반 리소스 키와 mapper 내부 키가 특정 시점에 불일치한다.

### 20.5 2026-04-20 코드 계측 반영 내역

다음 계층에 추적 로그를 추가해 호출 유무와 cache 상태를 직접 구분할 수 있도록 했다.

1. gRPC 서버 계층 (`mapper-framework/pkg/grpcserver/device.go`)
- `RegisterDevice`
   - start 로그(`deviceID`, `modelID` 포함)
   - cache hit/miss 분기 로그
   - `UpdateDev` 호출 후 post-check(`GetDevice`) 성공/실패 로그
- `UpdateDevice`
   - start 로그
   - post-check 성공/실패 로그
- `RemoveDevice`
   - start/성공/실패 로그
- `CreateDeviceModel`, `UpdateDeviceModel`
   - start/성공 로그

2. mapper 내부 디바이스 lifecycle 계층 (`mqttvirtual/device/device.go`)
- `UpdateDev`
   - 시작 시점 `hasDevice`, `hasMux`, `devices/muxs` 크기 로그
   - old device stop 실패 상세 로그
   - 완료 시점 map 크기 로그
- `RemoveDevice`
   - 시작 시점 map 상태 로그
   - `device not found` 명시 에러 처리
   - 성공 후 `deviceMuxs` 정리 로그
- `stopDev`
   - mux miss 시점 cache 상태 로그

검증:
- `mapper-framework`: `go test ./pkg/grpcserver/...` 통과
- `mqttvirtual`: `go test ./device/... ./cmd/...` 통과

### 20.6 다음 실행 순서 (매퍼 재빌드 전제)

1. Jetson에서 최신 `mqttvirtual` 바이너리 재빌드/교체
2. mapper 실행 직후 gRPC start/post-check 로그 확인
3. edgecore 로그와 mapper 로그를 동일 시간축으로 대조
4. `temp-device-01` 기준으로 다음 시퀀스를 확인
    - `RegisterDevice start`
    - `RegisterDevice post-check success/fail`
    - `UpdateDevice post-check success/fail`
    - edgecore의 `Update twin rejected ...` 발생 시각

### 20.7 판정 기준

- `RegisterDevice` 로그 자체가 없으면: edgecore → mapper 호출 경로 문제 우선
- `RegisterDevice`는 있으나 post-check 실패면: mapper 내부 등록/유지 로직 문제 우선
- post-check 성공 후 곧바로 mux miss가 나면: lifecycle 중간의 삭제/불일치 경로 추적 필요

### 20.8 본 과제와의 연결성

이 이슈는 단순 디바이스 연결 문제가 아니라, 다음 상위 목표와 직접 연결된다.

- 실시간 AI 서비스용 고신뢰 데이터/상태 경로 확보
- mixed-device 환경의 안정적 디바이스 추상화
- 오프로딩/워크플로우 의사결정의 신뢰 가능한 입력 상태 보장

즉, DeviceTwin 반영 경로의 안정화는 상위 오케스트레이션 실험의 선결 조건이다.

### 20.9 컨트롤플레인 ↔ 매퍼 통신 확인 절차

핵심은 다음 두 경로를 분리해서 보는 것이다.

- 매퍼 → edgecore: `MapperRegister`, `ReportDeviceStatus` 가 `/etc/kubeedge/dmi.sock` 으로 들어가는가
- edgecore → 매퍼: `RegisterDevice`, `UpdateDevice`, `CreateDeviceModel` 이 mapper UDS 로 호출되는가

코드 기준 근거:

- mapper framework client 는 `common.edgecore_sock` 로 edgecore DMI 서버에 접속한다.
- 기본 경로는 `/etc/kubeedge/dmi.sock` 이다.
- mapper 는 자기 자신의 gRPC 서버를 `grpc_server.socket_path` 에 연다.
- edgecore 는 mapper register 시 전달받은 `MapperInfo.Address` 를 이용해 mapper 로 역호출한다.

Jetson edge node 에서 우선 확인할 항목:

1. 소켓 파일 존재 여부

```bash
sudo ls -l /etc/kubeedge/dmi.sock
sudo ls -l /etc/kubeedge/*.sock
```

2. mapper 설정값 확인

```bash
grep -nE 'socket_path|edgecore_sock|protocol|name' /path/to/mqttvirtual/config.yaml
```

정상 기대값:

- `edgecore_sock: /etc/kubeedge/dmi.sock`
- `socket_path: /etc/kubeedge/mqttvirtual.sock` 또는 mapper 실행값과 동일한 경로
- `protocol: mqttvirtual`

3. mapper 기동 직후 등록 로그 확인

```bash
/path/to/mqttvirtual --config-file /path/to/config.yaml -v=4
```

정상 기대 로그:

- `Mapper will register to edgecore`
- `Mapper register finished`
- `uds socket path: /etc/kubeedge/mqttvirtual.sock`

4. edgecore 로그에서 mapper 등록과 역호출 확인

```bash
sudo journalctl -u edgecore -f | grep -E 'mapper|dmi|temp-device-01|RegisterDevice|UpdateDevice|DeviceModel'
```

5. mapper 로그에서 역호출 수신 확인

```bash
grep -E 'RegisterDevice|UpdateDevice|CreateDeviceModel|post-check|deviceMuxs|RemoveDevice' /path/to/mqttvirtual.log
```

6. control plane CR 상태 확인

```bash
kubectl get devicemodel virtual-temp-model -n default -o yaml
kubectl get device temp-device-01 -n default -o yaml
kubectl get devicestatus temp-device-01 -n default -o yaml
```

판정:

- `Mapper register finished` 가 있고 `ReportDeviceStatus` 도 성공하는데 `RegisterDevice` 로그가 mapper 에 전혀 없으면
  edgecore → mapper 역호출 경로 문제다.
- mapper 로그에 `dial unix /etc/kubeedge/mqttvirtual.sock: connect: connection refused` 가 보이면
  mapper gRPC 서버가 안 떴거나 `socket_path` 가 edgecore 가 알고 있는 주소와 다르다.
- mapper 에 `RegisterDevice start` 는 찍히는데 `post-check fail` 이면
  control plane 통신은 살아 있고 mapper 내부 cache/lifecycle 문제다.
- `CreateDeviceModel` 로그 없이 `deviceModel ... not found` 가 반복되면
  edgecore 가 model 동기화를 mapper 까지 밀어주지 못했거나 mapper 초기화 순서가 꼬인 것이다.

가장 짧은 결론 규칙:

- MQTT telemetry 로그만으로는 control plane 연동 확인이 되지 않는다.
- `MapperRegister` 성공은 매퍼 → edgecore 단방향 확인일 뿐이다.
- `RegisterDevice` 또는 `CreateDeviceModel` 수신 로그가 실제로 찍혀야 control plane ↔ mapper 통신 확인 완료로 본다.

### 20.10 원인 확정 및 해결 결과 (2026-04-20)

최종적으로 확인된 것은 다음과 같다.

- `temp-device-01` 기준 `DeviceStatus.status.twins.reported` 값이 실제로 갱신되었다.
- 따라서 현재는 `Mapper -> edgecore DeviceTwin -> DeviceStatus CR` 반영 경로가 정상 동작한다.
- `v1beta1` 기준으로는 `Device` 본문보다 `DeviceStatus` CR이 핵심 확인 대상이다.

확정된 주요 원인:

1. `DeviceModel`의 `spec.protocol` 누락
- 초기 `virtual-temp-model`에는 `spec.protocol: mqttvirtual` 이 없었다.
- 이 상태에서는 edgecore가 `CreateDeviceModel` 호출 시 protocol 기준 DMI client를 찾지 못해 model 동기화가 실패했다.
- 실제 edgecore 로그에서 `add device model virtual-temp-model failed with err: fail to get dmi client of protocol` 가 확인되었다.

2. `collectCycle` / `reportCycle` 단위 오해
- 실험 초기에 `5000000000` 값을 넣어 5초라고 가정했지만, mapper framework는 이를 `time.Millisecond * value` 로 해석한다.
- 결과적으로 `5000000000ms` 는 약 57.8일이 되어, twin report ticker가 사실상 돌지 않았다.
- 이 상태에서는 MQTT payload는 수신되어도 `ReportDeviceStatus` 호출이 일어나지 않아 `DeviceStatus.status.twins` 가 비어 있었다.

3. edgecore DMI rate limit
- 주기를 과도하게 짧게 하면 edgecore DMI 서버의 limiter에 걸린다.
- 현재 코드 기준 limiter는 `rate.NewLimiter(rate.Every(1000*time.Millisecond), 100)` 이다.
- 따라서 지속 구간에서는 대략 초당 1 request 수준을 넘기면 `fail to report device status because of too many request` 가 발생할 수 있다.

현재 정리된 동작 해석:

- MQTT broker 연결: 정상
- mapper의 `GetDeviceData`: 정상
- `devicetwin.go` 의 `Get temp-device-01 : ...` 로그: 정상
- `ReportDeviceStatus` 후 `DeviceStatus.status.twins.reported` 반영: 정상

이번 PoC에서 정리된 구현 판단:

- 현재 가상 센서 디바이스(`temperature`, `humidity`, `vibration`, `alarm`, `power`, `mode`, `sampling_interval`)는 `stream` 보다 `non-stream` / twin-status 경로가 맞다.
- 이 값들은 연속 미디어 스트림이 아니라 scalar 상태값이므로 `DeviceStatus.status.twins.reported` 기반 반영이 연구 목적과도 잘 맞는다.
- `stream` 타입은 카메라 프레임, 영상, 오디오, raw waveform 같은 연속 대용량 데이터용으로 별도 구분하는 것이 적절하다.

현재 반영된 로컬 매퍼 설정:

- `config.yaml`
  - `grpc_server.socket_path: /etc/kubeedge/mqttvirtual.sock`
  - `common.protocol: mqttvirtual`
  - `common.edgecore_sock: /etc/kubeedge/dmi.sock`
- `driver/devicetype.go`
  - `broker`, `subTopic`, `pubTopic`, `clientID`, `username`, `password`, `qos`, `jsonKey` 반영
- `driver/driver.go`
  - MQTT connect / subscribe
  - payload cache(`LatestValues`)
  - `GetDeviceData` / `DeviceDataWrite` / `StopDevice` / `GetDeviceStates` 구현

현재 실험 판단:

- 단일 가상 센서 디바이스 기준으로는 mapper 연동과 DeviceStatus reported 값 반영이 확인되었다.
- 남은 과제는 다중 디바이스 병렬 상황에서의 안정성, 그리고 polling 중심 구조를 event-driven twin synchronization 으로 개선할지 여부다.

### 20.11 후속 수정: event-driven 시도와 빌드/배포 이슈 정리 (2026-04-21)

단일 디바이스 PoC가 확인된 뒤, mapper의 twin report 경로를 polling 중심에서 event-driven 방향으로 실험했다.

목표:

- MQTT payload 수신 직후 `DeviceStatus.status.twins.reported` 반영 지연을 줄인다.
- property별 polling 요청 대신 변경 이벤트 기반 보고로 전환한다.

핵심 변경:

1. `driver` 계층
- MQTT callback 에서 `LatestValues` 캐시 갱신만 하지 않고 `Events` 채널로 payload 변경 이벤트를 전달하도록 수정했다.

2. `device` 계층
- `devicetwin.go`
  - 기존 `PushToEdgeCore()` 내부 로직을 `BuildReportedTwins()` helper 로 분리했다.
- `device.go`
  - `runEventTwinReporter()` 를 추가했다.
  - MQTT 이벤트를 250ms debounce window 로 모은 뒤, 여러 property를 하나의 `ReportDeviceStatus` 요청으로 묶어 보내도록 변경했다.

구조 비교:

- 기존
  - MQTT 수신
  - cache 저장
  - property별 ticker polling
  - property별 개별 `ReportDeviceStatus`
- 변경 후
  - MQTT 수신
  - cache 저장
  - 이벤트 채널 전달
  - 250ms coalescing
  - 변경된 twin들을 묶어 1회 `ReportDeviceStatus`

실험 중 확인된 점:

- MQTT receive 는 즉시 들어오지만, `DeviceStatus` CR 반영은 여전히 체감상 느릴 수 있었다.
- 이로부터 mapper 앞단보다 `edgecore devicetwin -> metamanager -> CR write` 경로의 propagation latency 가능성을 더 강하게 의심하게 되었다.

후속 조치:

- cloudcore `deviceController.load.updateDeviceStatusWorkers` 값을 `1 -> 8` 로 상향했다.
- 실험 중 실수로 삭제된 `kubeedge/cloudcore` ConfigMap 은 실행 중이던 `cloudcore` pod 내부의 `/etc/kubeedge/config/cloudcore.yaml` 를 추출해 동일 내용으로 복구했다.

추가로 확인된 빌드 문제:

1. 모듈 경로 불일치
- Jetson 실제 소스 모듈명은 `github.com/kubeedge/mqttvirtual` 이었는데, 템플릿 일부 import 가 `github.com/kubeedge/Template/...` 를 그대로 사용하고 있었다.
- 이 때문에 `go build` 시 `no required module provides package github.com/kubeedge/Template/...` 오류가 발생했다.
- 소스 전체 import 를 `github.com/kubeedge/mqttvirtual/...` 로 치환해 해결했다.

2. `stream` 전용 파일이 non-stream 빌드에 섞이는 문제
- `handler.go`, `img.go`, `video.go` 가 build tag 없이 함께 컴파일되어 `goav` / FFmpeg 계열 의존성이 non-stream 빌드에도 끌려왔다.
- 다음 build tag 를 추가해 분리했다.
  - `handler.go`, `img.go`, `video.go`: `//go:build stream`
  - `handler_nostream.go`: `//go:build !stream`
- 그 결과, 센서 디바이스용 non-stream 빌드에서는 `CGO_ENABLED=0 go build -o mqttvirtual-arm64 ./cmd` 경로가 가능해졌다.

현재 해석:

- 지금 PoC는 `stream` 실험이 아니라 non-stream 센서 상태값 동기화 실험이다.
- `temperature`, `humidity`, `vibration`, `alarm`, `power`, `mode`, `sampling_interval` 는 연속 미디어 스트림이 아니라 scalar 상태값이므로 twin/status 기반이 맞다.
- event-driven 이라는 것은 `stream` 전환이 아니라, non-stream 값을 polling 대신 이벤트 기반으로 보고한다는 뜻이다.

현재 판단:

- mapper 계층은 event-driven 시도와 non-stream 빌드 분리를 통해 다음 단계 실험을 수행할 준비가 되었다.
- 남은 핵심 과제는 edgecore propagation latency 를 계측하고, 그 위에서 20개 병렬 디바이스 실험으로 확장하는 것이다.

실행 기준 경로:

- 수정된 `mqttvirtual` 소스의 기준 위치는 `/home/etri/jinuk/mappers/mqttvirtual` 이다.
- 이후 새 edge node 에서도 이 경로의 소스를 가져와 빌드하는 것을 기본 절차로 삼는다.

non-stream 빌드:

```bash
cd /home/etri/jinuk/mappers/mqttvirtual
CGO_ENABLED=0 go build -o mqttvirtual-arm64 ./cmd
```

기존 프로세스 종료:

```bash
pkill -f 'mqttvirtual-arm64 --config-file ./config.yaml' || true
```

foreground 실행:

```bash
cd /home/etri/jinuk/mappers/mqttvirtual
sudo ./mqttvirtual-arm64 --config-file ./config.yaml --v 4
```

로그 저장 실행:

```bash
cd /home/etri/jinuk/mappers/mqttvirtual
sudo ./mqttvirtual-arm64 --config-file ./config.yaml --v 4 2>&1 | tee mapper.log
```

background 실행:

```bash
cd /home/etri/jinuk/mappers/mqttvirtual
nohup sudo ./mqttvirtual-arm64 --config-file ./config.yaml --v 4 > mapper.log 2>&1 &
```

실행 후 확인:

```bash
tail -f /home/etri/jinuk/mappers/mqttvirtual/mapper.log
kubectl get devicestatus temp-device-01 -n default -w
```

### 20.12 telemetry 와 DeviceStatus 분리 원칙 정리 (2026-04-21)

추가 실험 과정에서, 모든 센서값을 `DeviceStatus` 로 즉시 반영하는 방식은 구조적으로 과하다는 점을 확인했다.

핵심 판단:

- `DeviceStatus` 는 플랫폼이 관리해야 하는 대표 상태값에 사용하는 것이 맞다.
- 센서에서 계속 올라오는 실시간 측정값은 별도 telemetry / event 경로로 다루는 것이 맞다.
- 즉 telemetry 와 device status 는 같은 레벨로 처리하지 않는다.

정리된 기준:

1. `DeviceStatus` 로 유지할 값
- `alarm`
- `power`
- device connectivity state

2. telemetry 로만 유지할 값
- `temperature`
- `humidity`
- `vibration`
- `sampling_interval`
- `mode`

이 기준에 맞춘 현재 반영:

- `edge-device/scripts/generate_devices.py`
  - `status_keys` 를 따로 두고, 해당 key 만 `reportToCloud: true` 로 생성
- `edge-device/temp-device.yaml`
  - `temperature`: `reportToCloud: false`
  - `sampling_interval`: `reportToCloud: false`
- `mappers/mqttvirtual/device/device.go`
  - `deviceStatusPropertyAllowlist` 를 추가해 대표 상태값만 `ReportDeviceStatus` 대상으로 제한

현재 모델별 적용 해석:

- `env`
  - telemetry: `temperature`, `humidity`
  - status: 없음
- `vib`
  - telemetry: `vibration`
  - status: `alarm`
- `act`
  - telemetry: `mode`, `sampling_interval`
  - status: `power`

이 결정의 의미:

- 센서 실시간 측정값을 Kubernetes/KubeEdge control-plane 상태 저장소에 과도하게 쓰지 않는다.
- control-plane 부담과 propagation latency 를 줄인다.
- 이후 20개 디바이스 병렬 실험에서도 `DeviceStatus` 는 대표 상태 중심으로 유지하고, 실시간 측정값은 telemetry 경로로 관측하는 구조를 기본 원칙으로 삼는다.

### 20.13 최종 DeviceStatus 보고 정책 조정 (2026-04-21)

초기 event-driven 시도는 MQTT payload 수신마다 `DeviceStatus` 를 바로 보고하는 형태에 가까웠다.
이 방식은 `temperature`, `humidity`, `vibration` 같은 실측값까지 control-plane 경로에 태우게 되어 `too many request` 문제를 다시 유발했다.

최종적으로 다음 정책으로 정리했다.

핵심 정책:

- 실측 telemetry 값은 `DeviceStatus` 로 즉시 report 하지 않는다.
- `DeviceStatus` 에는 대표 상태값만 유지한다.
- 동일 값은 재보고하지 않는다.
- 즉시 report 는 제거한다.
- `5초` 주기 flush loop 로 묶어서 보고한다.
- property별 최소 보고 간격을 둔다.
- 결과적으로 changed-only + rate-controlled 방식으로 운용한다.

현재 대표 상태 allowlist:

- `alarm`
- `power`

제외되는 실측값:

- `temperature`
- `humidity`
- `vibration`
- `sampling_interval`
- `mode`

코드 반영:

- `mappers/mqttvirtual/device/device.go`
  - `eventTwinFlushInterval = 5 * time.Second`
  - `minDeviceStatusReportInterval = 30 * time.Second`
  - `deviceStatusPropertyAllowlist` 추가
  - `runEventTwinReporter()` 에서 즉시 전송 제거
  - `pending` 이벤트를 모아 5초마다 flush
  - `lastReported` 비교를 통해 동일 값 재보고 차단
  - `lastReportTime` 비교를 통해 property별 최소 30초 간격 보장
- `edge-device/scripts/generate_devices.py`
  - `env` 는 status 대상 없음
  - `vib` 는 `alarm` 만 status 대상
  - `act` 는 `power` 만 status 대상
- `mappers/script/test_device.py`
  - `sampling_interval` 을 telemetry payload 에서 제거
  - `act` 의 `power` / `mode` 는 매 주기 랜덤 변경이 아니라 낮은 확률로만 변경
- Jetson 실제 실행 소스 `/home/etri/mqttvirtual/device/device.go` 에도 동일 내용 반영

의도한 효과:

- edgecore DMI limiter 충돌 감소
- 불필요한 `DeviceStatus` CR 갱신 감소
- telemetry 와 control-plane status 의 역할 분리
- 20개 디바이스 확장 시에도 representative status 중심의 안정적 반영 구조 유지

현재 전체 정리:

1. 단일 디바이스 경로 검증
- `mqttvirtual` mapper 와 `DeviceStatus.status.twins.reported` 반영 확인

2. 주요 원인 정리
- `DeviceModel.spec.protocol` 누락
- `collectCycle/reportCycle` 단위 오해
- `stream` / `non-stream` 빌드 분리 미비
- 모듈 경로(`Template` -> `mqttvirtual`) 불일치

3. 매퍼 구조 정리
- 수정된 `mqttvirtual` 소스는 `/home/etri/jinuk/mappers/mqttvirtual` 를 기준 경로로 관리
- 새 edge node 에서는 이 소스를 가져와 non-stream 빌드하는 방식으로 재현

4. 현재 설계 결론
- 센서 실측값은 telemetry 경로
- 플랫폼 대표 상태만 `DeviceStatus`
- `DeviceStatus` 보고는 5초 flush + changed-only + 최소 30초 간격

5. 다음 단계
- 20개 디바이스에 대해 대표 상태만 `DeviceStatus` 반영되는지 검증
- telemetry 경로와 status 경로를 분리한 상태로 병렬 안정성 확인

### 20.14 `power` 와 `online/offline` 분리 및 `last_seen` 기반 생존성 판정 (2026-04-22)

추가 정리 과정에서, `power` 값을 device liveness 와 같은 의미로 쓰는 것은 구조적으로 맞지 않다는 점을 확정했다.

핵심 이유:

- 디바이스 전원이 갑자기 꺼지면 `power=off` 메시지를 마지막으로 보내지 못할 수 있다.
- 즉 `power` 는 디바이스 내부 동작 상태일 뿐, 통신 생존성 자체를 대변하지 않는다.
- 비정상 종료나 네트워크 단절은 마지막 telemetry 수신 시각(`last_seen`) 기반으로 판정해야 한다.

최종 해석:

1. `power`
- actuator 의 내부 상태
- 예: on / off
- telemetry 또는 representative twin 값으로 유지 가능

2. `online/offline`
- 디바이스 생존성 상태
- 마지막 telemetry 수신 시각 기준으로 판단

3. `disconnected`
- mapper 와 MQTT broker 연결 자체가 끊긴 상태
- 디바이스 개별 상태와는 다른 계층

코드 반영:

- `mappers/mqttvirtual/driver/devicetype.go`
  - `CustomizedClient` 에 `LastSeenAt`, `HasTelemetry` 추가
  - protocol config 에 `offlineAfterMs` 추가
- `mappers/mqttvirtual/driver/driver.go`
  - telemetry payload 수신 시 `LastSeenAt = time.Now()` 갱신
  - `GetDeviceStates()` 를 아래 기준으로 변경
    - broker 미연결: `disconnected`
    - telemetry 미수신: `unknown`
    - 마지막 telemetry 가 timeout 초과: `offline`
    - timeout 이내 telemetry 존재: `online`
- `edge-device/scripts/generate_devices.py`
  - 각 디바이스 protocol config 에 `offlineAfterMs: 15000` 추가
- `edge-device/devices.yaml`, `edge-device/temp-device.yaml`
  - 생성 결과 기준으로 `offlineAfterMs: 15000` 반영

현재 운영 의미:

- `power=off` 여도 최근 telemetry 가 들어오면 디바이스는 `online`
- 전원이 꺼지거나 비정상 종료되어 telemetry 가 끊기면 `15초` 뒤 `offline`
- mapper 자체가 broker 와 끊기면 `disconnected`

이 결정의 의미:

- control-plane 상태 해석이 더 명확해진다.
- `power` 와 connectivity 를 혼동하지 않는다.
- 비정상 종료 상황을 더 현실적으로 모델링할 수 있다.

### 20.15 Device 운영 대시보드 live 판단 기준을 InfluxDB last_seen으로 전환 (2026-04-28)

`state-aggregator` 기반 디바이스 운영 대시보드에서 기기가 `available/healthy`로 보이지 않는 문제를 점검했다.

초기 증상:

- KubeEdge node와 mapper Pod는 정상 실행 중이었다.
- `mqttvirtual` mapper 로그에서는 MQTT payload 수신과 `GetDeviceData` 반환이 확인되었다.
- CloudCore 로그에서도 `twin/edge_updated` 메시지가 처리되고 있었다.
- 그러나 `state-aggregator`의 `/state/devices`에서는 모든 Device가 live로 판단되지 않았다.

확인된 실제 경로:

```text
MQTT payload
  -> mqttvirtual mapper 수신 및 cache
  -> edgecore DeviceTwin이 mapper에 GetDeviceData 호출
  -> mapper가 최신 값 반환
  -> edgecore가 cloudcore로 twin/edge_updated 전송
  -> cloudcore process successfully
```

문제의 핵심:

- `state-aggregator`는 Kubernetes API의 `devices.devices.kubeedge.io` CR을 읽고 있었다.
- 현재 `Device.status`에는 다음 정도의 값만 남아 있었다.

```yaml
status:
  reportCycle: 60000
  reportToCloud: false
```

- 일부 Raspberry Pi Device는 `status` 자체가 비어 있었다.
- 즉 edge 쪽 telemetry와 twin event는 흐르고 있지만, Kubernetes Device CR status가 raw telemetry 저장소처럼 동작하지 않았다.

정책 재확정:

- KubeEdge `Device` CR은 등록, 노드 할당, 프로토콜, property 같은 최소 메타데이터로 사용한다.
- `DeviceStatus`는 raw telemetry 저장소로 사용하지 않는다.
- raw telemetry는 InfluxDB/data plane으로 저장한다.
- 대시보드의 live 상태는 InfluxDB의 device별 최신 telemetry 수신 시각(`last_seen`)으로 판단한다.

구현 변경:

- `edge-orch/state-aggregator/app/influx.py` 추가
  - InfluxDB `/api/v2/query`를 호출한다.
  - `device_telemetry` bucket의 `virtual_device_telemetry` measurement에서 device별 최신 sample을 조회한다.
  - CSV query 결과를 파싱해 `TelemetrySample(device_id, timestamp, property, value)`로 정규화한다.
- `edge-orch/state-aggregator/app/config.py`
  - `INFLUXDB_URL`
  - `INFLUXDB_ORG`
  - `INFLUXDB_BUCKET`
  - `INFLUXDB_TOKEN`
  - `INFLUXDB_MEASUREMENT`
  - `TELEMETRY_FRESH_SECONDS`
  - `TELEMETRY_QUERY_WINDOW`
  설정을 추가했다.
- `edge-orch/state-aggregator/app/models.py`
  - `DeviceState.telemetry_last_seen`
  - `DeviceState.telemetry_age_seconds`
  - `DeviceState.telemetry_property`
  - `DeviceState.telemetry_value`
  필드를 추가했다.
- `edge-orch/state-aggregator/app/service.py`
  - Device CR status보다 InfluxDB 최신 telemetry를 우선해서 device health를 판단한다.
  - `TELEMETRY_FRESH_SECONDS` 이내 telemetry가 있으면 `healthy`.
  - mapper는 실행 중이지만 InfluxDB telemetry가 없으면 `degraded`.
  - node/mapper가 죽었거나 미할당이면 `unavailable`.
- `edge-orch/state-aggregator/app/static/dashboard.js`
  - device card와 relation view에 `last seen`, 최신 property/value를 표시한다.
- `edge-orch/state-aggregator/k8s/deployment.yaml`
  - InfluxDB 접속 env와 `influxdb-token` secret 참조를 추가했다.

현재 InfluxDB schema:

```text
bucket: device_telemetry
org: edgeai
measurement: virtual_device_telemetry
tags: device_id, device_type, property
field: value
```

예시 query 결과:

```text
device_id       property      _value
env-device-01   humidity      38
env-device-02   humidity      54
vib-device-01   vibration     2.367
```

검증 결과:

```text
registered_device_count: 31
operational_device_count: 31
live_device_count: 14
unavailable_device_count: 0
healthy: 14
degraded: 17
```

현재 live로 판단되는 device:

- `env-device-01` ~ `env-device-08`
- `vib-device-01` ~ `vib-device-06`

현재 degraded로 판단되는 device:

- `act-device-01` ~ `act-device-06`
- `rpi-act-device-01` ~ `rpi-act-device-03`
- `rpi-env-device-01` ~ `rpi-env-device-04`
- `rpi-vib-device-01` ~ `rpi-vib-device-03`
- `temp-device-01`

해석:

- degraded device는 node/mapper 장애가 아니다.
- mapper는 살아 있지만 InfluxDB에 매칭되는 최근 telemetry가 없기 때문에 live로 판단하지 않는다.
- 이 기준이 운영 대시보드에는 더 정확하다.

테스트:

```text
PYTHONPATH=. .venv/bin/pytest tests/test_api.py tests/test_normalizer.py tests/test_storage.py
15 passed
```

관련 커밋:

- `6b49e55 fix: separate device availability from live health`
- `129c5e5 fix: use influx telemetry for device health`
- `9c281bb fix: parse influx query csv results`

### 20.16 Argo CD Image Updater와 state-aggregator digest 고정 (2026-04-28)

`state-aggregator`를 수동 빌드/푸시한 뒤 Argo CD Application에 새 digest를 patch했지만, 일정 시간이 지나면 다른 digest로 되돌아가는 문제가 있었다.

원인:

- `edge-orch-state-aggregator` Application에 Argo CD Image Updater annotation이 있었다.

```yaml
argocd-image-updater.argoproj.io/image-list: state-aggregator=192.168.0.56:5000/state-aggregator:latest
argocd-image-updater.argoproj.io/state-aggregator.update-strategy: digest
argocd-image-updater.argoproj.io/write-back-method: argocd
```

- Image Updater가 `latest` digest를 자체 기준으로 다시 계산하면서, 수동으로 patch한 digest를 덮어썼다.
- 그 결과 새 코드가 배포된 것처럼 보여도 실제 Deployment image가 다른 digest로 바뀌는 상황이 발생했다.

조치:

- `edge-orch-argocd/argocd-apps.yaml`에서 `state-aggregator` Application의 image-updater annotation을 제거했다.
- live Application에서도 해당 annotation을 제거했다.
- 현재 `state-aggregator`는 필요한 경우 Application의 `spec.source.kustomize.images`에 digest를 명시적으로 patch한다.

현재 고정 digest:

```text
192.168.0.56:5000/state-aggregator@sha256:6190c420697698bb005818d02b1bf59a1448c8737eba5ccf36bd70e921bb5a4d
```

관련 커밋:

- `7da5b6b fix: pin state aggregator image updates manually`

운영 원칙:

- `state-aggregator`처럼 현장 검증 중인 컴포넌트는 `latest` 자동 digest 추적보다 명시 digest 고정이 안전하다.
- 새 이미지를 빌드하면 registry push digest를 확인한 뒤 Argo CD Application image override를 함께 갱신한다.
- GitOps 기준 파일과 live Application spec이 어긋나지 않도록, annotation 변경은 Git에도 반영한다.
