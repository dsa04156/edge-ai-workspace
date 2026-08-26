작업명

EdgeX physical-device state + Prometheus node/workload state 통합 허브 구현

목적

EdgeX Core Metadata/Core Data를 물리 디바이스 inventory, state, telemetry의 권위 원본으로 읽고,
Prometheus/node-exporter와 Kubernetes에서 node/workload 상태를 읽으며
workflow/stage 이벤트를 함께 정규화하는 중앙 상태 허브를 구현한다.
KubeEdge는 edge node/workload 관리 정보에만 사용하고 KubeEdge Device/DeviceStatus나
MapperFramework를 physical-device fallback으로 조회하지 않는다.
구현해야 할 것
A. API 서버

Python FastAPI 기반 서버 구현

필수 endpoint:

POST /workflow-event
GET /state/nodes
GET /api/resources
POST /api/placements/select
POST /api/deployments
GET /state/node/{hostname}
GET /state/workflows
GET /state/workflow/{workflow_id}
GET /state/summary

과거 dashboard의 AI Pipeline/Workflow Builder와 샘플 실행 API는 제거했다. 등록된
EdgeX Core Metadata Device는 `GET /state/devices`로 조회하고, Device Profile의 안전한
resource 계약은 `GET /state/device-profiles`, Core Data Event/Reading history는
`GET /state/devices/{device_id}/telemetry`로 확인한다. 대시보드의 새 `서비스 설계`는
`GET /state/services`의 현재 운영 서비스 목록을 상단에 별도로 표시하고, Device/Profile
read-only 계약을 사용해 browser-local 단계 구성, 포트 연결, 타입·배치 validation과
dry-run 실행 계획만 제공한다. 캔버스에는 pan·zoom·fit view·미니맵, 24px grid와
정렬선 snap, `Shift` 축 고정·`Alt` 자유 이동, 접을 수 있는 단계/설정 패널이 있으며
드롭 뒤 viewport를 다시 이동하거나 문서·캔버스의 가로 scrollbar에 의존하지 않는다.
localStorage 밖으로 초안을 저장하지 않고 Kubernetes, EdgeX, command와 workload를
변경하지 않는다. 고정 `sensor-anomaly-demo`는 같은 edge node에서 Device Service Local
Data API를 직접 읽으며 state-aggregator가 데이터 프록시 역할을 하지 않는다.
`예시 불러오기`는 이 고정 데모의 가속도 X/Y/Z → 벡터 크기 → 온라인 이상 점수 →
대시보드 계약을 캔버스에 만들고, 현재 세 축 EdgeX Device가 같은 Jetson에 있으면
읽기 전용 입력과 처리 노드를 자동 바인딩한다. 이는 새 workload를 배포하거나
고정 데모를 실행하는 동작이 아니다.
대시보드의 `디바이스 트윈` 화면은 `GET /state/device-twins`를 사용한다. 이 응답은
실제 물리 디바이스에서 수집되어 EdgeX Metadata와 Core Data에 반영된 관측 상태와
AI 서비스 입력 연결을 N:M `service_bindings`로 보여주며, 가상 하드웨어나
desired/reported 제어 트윈을 뜻하지 않는다. 서비스 정의와 입력 바인딩은 별도 고정
목록이 아니라 Git 기반 `/state/services` 서비스 inventory를 기준으로 합성한다.
현재 대시보드는 workload 생성, 자동 offloading, runtime migration을 수행하지 않는다.

Dashboard의 별도 `Device Management` 화면은 승인된 관리 경로다.

- 화면 제목과 상태·오류·작업 문구는 한국어로 제공하며, 먼저 엣지 노드를 선택한 뒤
  해당 노드의 Runtime, 승인 Adapter, EdgeX Device를 관리한다.
- 노드 후보는 `GET /state/nodes` 관측 결과 중 `node_type=edge_*`인 노드와
  Runtime·Device·승인 hardware binding이 실제로 참조하는 노드로 제한한다. 관계없는
  중앙 `cloud_server` 노드는 디바이스 연결 대상으로 표시하지 않는다.
- 노드 선택은 workload placement와 운영 탐색 범위다. 물리 inventory, state, telemetry,
  command의 권위는 계속 EdgeX이며 Kubernetes Node 상태로 Device availability를 덮어쓰지 않는다.
- 연결 마법사의 target node는 선택한 노드로 고정한다. 기존 Device PATCH는 해당 노드의
  Device를 명시적으로 선택한 뒤에만 활성화한다.
- 등록 1단계는 protocol/Device Service를 먼저 선택하고, 선택 노드의 승인 hardware
  binding과 Device Service 준비 방식을 뒤에서 선택한다. 미검증 protocol은 이유와 함께
  표시하지만 선택할 수 없다.
- Hardware binding의 protocol tuple은 UI가 read-only로 채우고 서버가 다시 대조한다.
  Serial runtime은 복수 승인 `hardwareBindingIds`를 소유할 수 있어 같은 Device Service가
  서로 다른 USB 포트를 처리한다.
- `GET /management/adapter-runtimes`에서 기존 Argo runtime과 Controller runtime의 owner,
  phase, target node와 EdgeX consumer를 조회한다.
- Runtime/Device 통합 validation은 mutation 없이 `REUSE`, `DEPLOY`, `BLOCKED` plan을 만든다.
- 인증된 `POST /management/connections`는 Adapter Controller를 통해 승인 runtime을
  준비한 뒤 EdgeX Profile/Device를 등록하고 first Event까지 추적한다.
- state-aggregator의 일반 read model과 Device Management BFF는 기존 Kubernetes
  workload를 수정하지 않는다. 별도 `/api/deployments` Controller만 전용 namespace에
  신규 Deployment를 생성하며 외부/Argo runtime을 restart/retire하지 않는다.
- raw manifest, 임의 image/hostPath/hostNetwork, 고정 ClusterIP/PodIP, EdgeMesh와 KubeEdge
  Device CRD 변경은 API schema에 없다.

자세한 운영 경계는
`docs/ops/어댑터-런타임-디바이스-연결-관리.md`를 따른다.
B. Prometheus reader

Prometheus HTTP API를 사용해 아래 metric을 주기적으로 읽어오기

node up/down
CPU utilization
logical CPU count
memory usage ratio
load average
network rx/tx rate
C. instance → hostname 매핑

Prometheus instance 값을 논리적 hostname으로 변환하는 설정 파일 사용

예시 파일:
app/config/instance_map.json

형식 예:

{
  "192.168.0.56:9100": {
    "hostname": "etri-ser0001-CG0MSB",
    "node_type": "cloud_server"
  },
  "192.168.0.3:9100": {
    "hostname": "etri-dev0001-jetorn",
    "node_type": "edge_ai_device"
  },
  "192.168.0.4:9100": {
    "hostname": "etri-dev0002-raspi5",
    "node_type": "edge_light_device"
  }
}
D. normalized state 생성

node raw metric을 다음 상태로 변환

`compute_pressure`는 CPU 사용률과 `load average / logical CPU count` 중 큰 값을 사용한다.
CPU 수를 관측하지 못하면 임의의 코어 수를 가정하지 않고 CPU 사용률만 사용한다.

compute_pressure: low / medium / high
memory_pressure: low / medium / high
network_pressure: low / medium / high
node_health: healthy / degraded / unavailable

workflow raw event를 다음 상태로 변환

workflow_urgency
sla_risk
placement_stability
E. 상태 저장

초기 버전은 DB 없이 구현

최신 상태: in-memory dict
원시 이벤트 로그: JSONL 파일 append

저장 파일 예:

data/node_state.jsonl
data/workflow_event.jsonl
입력
1. Prometheus

Prometheus URL은 환경변수로 받기

PROMETHEUS_URL=http://prometheus:9090
2. workflow event

POST /workflow-event 로 JSON 수신

최소 event schema:

event_type
timestamp
workflow_id
stage_id
assigned_node
status
출력
/state/nodes

전체 노드의 최신 normalized state 반환

/api/resources

Placement Engine이 읽을 수 있는 노드별 scheduling snapshot을 반환한다. Kubernetes Node
allocatable에서 노드에 할당된 비종료 Pod requests를 차감해 CPU·memory·확장 accelerator
가용량을 계산하고, 기존 `/state/nodes`의 Prometheus utilization과 health를 별도 관측값으로
결합한다. 응답의 `allocatable`, `requested`, `available`은 계산 근거이며 이 API는
Kubernetes workload를 변경하거나 노드를 예약하지 않는 read-only endpoint다.

/api/placements/select

`namespace`, `service`, `architecture`와 선택 `accelerator`·`acceleratorUnits` 조건을 받아
해당 실행 서비스의 `/state/service-resource-profiles` CPU·memory requests와
`/api/resources` 노드 snapshot을 결합한다. 먼저 schedulable, CPU, memory, architecture,
accelerator 조건을 fail-closed Filter하고, 통과 노드는 배치 후 CPU·memory headroom 60%와
현재 Prometheus CPU·memory idle 40%를 합산한 0~100점으로 Score한다. 결과는 선택 노드,
점수 세부내역, 모든 후보의 `reasonCodes`를 반환하며 workload apply·migration·offloading은
실행하지 않는다.

/api/runtime-recommendations

Git `ServiceDescriptor.runtime_recommendation`이 활성화된 AI 서비스를 지속 감시한다.
Deployment/StatefulSet·Pod·현재 Node 상태, Prometheus 자원 사용량과 observability adapter의
입력 freshness·model readiness·latency·backlog·throughput을 결합한다. 진입 threshold와
회복 threshold를 분리한 hysteresis, pressure/failure/recovery dwell과 recommendation
cooldown을 적용해 다음 상태를 반환한다.

- `NORMAL`: 회복 threshold 안에서 안정적
- `OBSERVING`: 진입·회복 dwell 또는 cooldown 진행 중
- `AUGMENT_RECOMMENDED`: Ready workload의 자원 압력과 서비스 압력이 함께 지속됨
- `REPLACE_RECOMMENDED`: Deployment/Pod/Node 실패가 지속됨
- `BLOCKED`: EdgeX 입력 stale/장애, model 미준비, 관측 누락 또는 적합 후보 없음

증강·대체 판단 시 현재 실행 노드는 Placement 후보에 남지만
`current_node_excluded`로 탈락한다. 나머지 노드는 기존 Filter/Score 규칙으로 재평가하며
최적 노드, 점수와 전체 후보 `reasonCodes`를 반환한다. 최신 판단은
`GET /api/runtime-recommendations/{serviceId}`, 이력은
`GET /api/runtime-recommendations/{serviceId}/history?limit=100`으로 조회한다.

SQLite에는 최신 판단뿐 아니라 pressure/failure latch, 각 dwell·회복 시작시각과 마지막
추천시각을 저장한다. `/app/data`는 PVC이고 Deployment strategy는 `Recreate`이므로 Pod
재시작 뒤에도 timer와 이력이 유지되며 동시에 두 poller가 쓰지 않는다. 이 API는
read-only 추천이며 `/api/deployments`를 호출하거나 traffic 전환·삭제를 수행하지 않는다.

### `/api/runtime-recommendations/{serviceId}/execution-plan`

최신 영속 Runtime Recommendation을 운영자·후속 Controller 검토용 read-only 실행 계획으로
변환한다. 동일 추천의 `observedAt`, workload identity와 선택 node로 결정적인 `planId`와
후보 workload 이름을 만들며, 조회할 때 추천 timer나 판단 이력을 변경하지 않는다.

- `AUGMENT_RECOMMENDED`: `create_candidate → verify_ready → validate_candidate_pre_activation →
  handoff_execution_ownership → verify_active_candidate → distribute_traffic`
- `REPLACE_RECOMMENDED`: `create_candidate → verify_ready → validate_candidate_pre_activation →
  handoff_execution_ownership → verify_active_candidate → switch_traffic →
  verify_switched_traffic → terminate_current`, 실패 보상 `rollback_traffic`과
  `rollback_execution_ownership`
- `NORMAL`·`OBSERVING`: `not_applicable`, 단계 없음
- `BLOCKED` 또는 불완전한 Placement: `blocked`, 단계 없음

각 단계는 `sequence`, `action`, `executionMode`, 대상 node/workload, `dependsOn`, 안정적인 code와
설명이 포함된 `prerequisites`·`failureConditions`를 반환한다. 대체 계획의 `rollback`은
`on_failure` 보상 단계이며 실행 성공을 주장하지 않는다. 이 GET API는 Deployment Controller,
Kubernetes, Service/Ingress 또는 traffic plane을 호출하지 않는다.

### 승인 기반 Execution Controller

- `POST /api/runtime-recommendations/{serviceId}/execution-plan/dry-run`
- `POST /api/runtime-recommendations/{serviceId}/execution-plan/execute`
- `GET /api/execution-plans/{planId}`
- `GET /api/execution-plans/{planId}/audit`
- `GET /api/executions?serviceId={serviceId}&limit=100`

dry-run은 최신 `planId`, source Deployment·Service·PVC, target Node, immutable allowlisted image,
Placement requirements와 단계 지원 경계를 읽기 전용으로 확인한다. candidate는 source
Deployment를 복제하지 않고 `app/config/candidate_workload_templates.json`에 서비스별로 승인된
image digest, env, port/probe, resources, securityContext, namespace, architecture/accelerator와
state policy만 사용한다. source와 승인 계약이 다르면 `candidate_template_mismatch`, 템플릿이
없거나 유효하지 않으면 `candidate_template_not_found`·`candidate_contract_invalid`로 생성 전에
차단한다. 실행 API는 `EXECUTION_CONTROLLER_ENABLED=true`,
`X-Execution-Token`, 본문의 동일 `planId`, `approved=true`, `approvedBy`가 모두 필요하다.
planId가 idempotency key이므로 중복 요청은 저장된 최초 record를 반환한다.
신규 실행은 `202 Accepted`와 PENDING record를 즉시 반환하고 background task가 단계를 진행한다.
진행 상태와 validation 상세는 `GET /api/execution-plans/{planId}`로 조회한다.

현재 코드 지원 단계는 `create_candidate`, `verify_ready`,
`validate_candidate_pre_activation`, `handoff_execution_ownership`,
`verify_active_candidate`, `rollback_execution_ownership`, `switch_traffic`,
`verify_switched_traffic`, `rollback_traffic`이다. candidate는
`edge-ai-workloads`에 단일 replica Deployment로 생성하고 선택 node에 exact hostname으로
고정한다. `terminate_current`와 workload/PVC 삭제·promotion은 `unsupported_step`으로 중단한다.
실패 후 source workload를 update/delete하지 않고 생성된 candidate도 자동 삭제하지 않는다.
`sensor-anomaly-demo` v1은 `fresh_state`이며 기존 RWO `local-path` PVC를
재사용하거나 복제하지 않고 candidate의 `/var/lib/sensor-anomaly-demo`를 `emptyDir`로 만든다.
`ResultStore`가 빈 경로에 SQLite schema를 생성하므로 기존 `results.db` 없이도 `/readyz`까지
진행할 수 있다. candidate identity와 생성 PVC 목록(현재는 빈 목록)은 실행 record에 보존한다.
pre-activation validation은 `app/config/candidate_validation_contracts.json`을 읽어 Pod Ready,
health, 유효한 source Lease 아래의 candidate SHADOW 상태, fresh input, model ready와 shadow
inference를 확인한다. handoff 뒤 active validation은 candidate의 Lease ACTIVE 상태, production
`framesProcessed` 증가, 최근 결과 freshness와 측정 가능한 latency SLO를 다시 확인한다. 모든
필수 검사가 계약의 dwell 조건을 만족해야 성공하며 source와 candidate 관측값은 비교용으로
저장하되 candidate가 source보다 빨라야 한다는 조건은 없다.

`app/config/execution_ownership_contracts.json`은 서비스별 Lease namespace/name, 허용 holder
identity와 lease duration을 Git 계약으로 고정한다. Controller는 현재 source holder와
resourceVersion을 preflight하고 CAS로 candidate holder로 전환한다. 서비스별 SQLite lock이
동시 handoff를 막으며 snapshot·전환·rollback을 실행 record와 audit에 저장한다. handoff 또는
active validation 실패 시 persisted snapshot의 source holder로 CAS rollback하고 candidate는
삭제하지 않는다. 재시작 중 RUNNING handoff는 자동 재개하지 않고
`execution_ownership_recovery_required`로 차단한다.

실행과 단계 상태는 `PENDING/RUNNING/SUCCEEDED/FAILED/BLOCKED`이며 승인·상태 전이·reason을
`/app/data/runtime-executions.sqlite3`의 record와 append-only audit log에 저장한다. 재시작 시
남은 PENDING/RUNNING record는 중복 실행하지 않고 `execution_interrupted`로 차단한다.
`app/config/traffic_routing_contracts.json`은 Service/namespace/port, source selector,
post-switch dwell과 rollback 정책을 고정한다. Controller는 Argo CD 소유 Service를 patch하지 않고
selectorless Service에 연결된 Controller 단독 소유 EndpointSlice만 resourceVersion 조건부
replace한다. switch 직전 source endpoint snapshot을 SQLite/audit에 저장하고 Service 주소를 통해
동일 기능 검증을 30초 다시 수행한다. 실패하면 저장한 snapshot만 사용해 source로 rollback한다.
서비스별 SQLite routing lock은 서로 다른 plan의 동시 cutover를 막는다.

현재 live `sensor-anomaly-demo` Service에는 Argo CD 소유 selector와 Kubernetes endpoint-slice
controller 소유 slice가 있고, edge node의 EdgeMesh는 legacy Endpoints를 관측한다. EndpointSlice
소비 호환성이 입증되지 않았으므로 Git routing contract의 `compatibilityStatus`는 `blocked`이며
실제 실행은 `routing_mode_unsupported`로 차단된다. selectorless Service 전환, Runtime 소유 source
EndpointSlice bootstrap과 EdgeMesh traffic 시험이 완료되기 전에는 실클러스터 cutover를 수행하지 않는다.

2026-08-26 별도 격리 namespace에서는 selectorless Service와 Controller 소유 core `Endpoints`를
통한 source→candidate→source가 edge-resident probe와 EdgeMesh libp2p 로그로 확인됐다. 상세 증거는
`docs/ops/EdgeMesh-Endpoints-라우팅-검증.md`에 있다. 이 결과는 후속 `runtime-endpoints` 모드의
근거이며 현재 EndpointSlice 계약을 unblocked하거나 production Service를 변경하지 않는다.

/api/deployments

`placement` 필드에 `/api/placements/select`와 같은 서비스 프로파일·architecture·accelerator
조건을 넣고, 신규 `deploymentName`과 immutable digest `image`를 전달한다. Controller는
선택 노드를 exact hostname `nodeSelector`와 required node affinity에 함께 적용하고,
프로파일 CPU·memory·accelerator requests를 단일 replica Deployment에 설정한다. 생성 후
Deployment와 Pod를 관측해 `ready`, `failed`, `rejected`, `podReady`, Pod 상태와 안정적인
`reasonCodes`를 반환한다.

v1 경계:

- 대상 namespace는 `edge-ai-workloads`로 고정
- 단일 Pod에서 완전하게 수집된 서비스 자원 프로파일만 허용
- allowlist의 로컬 registry image와 `@sha256:<digest>`만 허용
- `X-Deployment-Token`과 `Idempotency-Key` header 필수
- raw manifest, env, command, volume, Service/Ingress 입력 없음
- 기존 Deployment update·patch·delete, migration·offloading 없음

예시:

```json
{
  "deploymentName": "quality-ai-v1",
  "image": "192.168.0.56:5000/state-aggregator@sha256:<64-hex-digest>",
  "placement": {
    "namespace": "default",
    "service": "redis",
    "architecture": "amd64"
  },
  "containerPort": 8000,
  "readinessPath": "/"
}
```

/state/workflows

전체 workflow 상태 반환

/state/summary

scheduler/planner가 바로 읽을 수 있는 요약 상태 반환

예:

어떤 노드가 hotspot인지
어떤 workflow가 SLA risk인지
최근 migration이 많은지
배포 방식
Kubernetes Deployment
server node 우선 배치
image는 로컬 registry 사용 가능하도록 Dockerfile 포함
기술 스택
Python 3.11
FastAPI
Pydantic
requests / httpx
제약사항
Redis/DB/Postgres는 사용하지 말 것
인증/인가 붙이지 말 것
고가용성 구현하지 말 것
초기 버전은 단일 replica 기준
코드는 mixed-device 환경에서도 문제 없도록 순수 Python으로 작성
완료 기준
Prometheus에서 node metric을 읽어 /state/nodes로 반환 가능
/workflow-event로 이벤트를 받아 /state/workflows에 반영 가능
/state/summary에서 scheduler용 요약 상태를 반환 가능
Dockerfile 포함
Kubernetes Deployment YAML 포함
2. Codex에게 줄 작업 명세: workflow_reporter
작업명

workflow/stage 실행 이벤트 수집기 구현

목적

AI 서비스 workflow의 stage 시작/종료/이동 이벤트를 수집하여
state_aggregator에 전달하는 최소 reporter를 구현한다.

구현해야 할 것
A. Python 라이브러리 또는 경량 서비스

아래 이벤트를 aggregator에 보낼 수 있어야 함

stage_start
stage_end
migration_event
workflow_end
failure_event
B. 전송 방식

HTTP POST
대상:

STATE_AGGREGATOR_URL=http://state-aggregator:8000/workflow-event
C. 공통 이벤트 스키마

필수 필드:

event_type
timestamp
workflow_id
workflow_type
stage_id
stage_type
assigned_node

상황별 추가 필드:

exec_time_ms
queue_wait_ms
transfer_time_ms
from_node
to_node
reason
status
D. helper 함수 제공

예:

report_stage_start(...)
report_stage_end(...)
report_migration(...)
report_failure(...)

즉, 각 stage 컨테이너에서 쉽게 import해서 쓸 수 있게 한다.

출력 대상

state_aggregator의 POST /workflow-event

배포 방식

초기 버전은 두 방식 중 하나로 충분하다.

Python package 형태
sidecar 또는 stage container 내부 helper 형태

우선은 Python helper module 형태로 구현하는 게 좋다.

기술 스택
Python 3.11
requests 또는 httpx
제약사항
Kafka, RabbitMQ 등 메시지 브로커 도입 금지
retry는 간단한 수준만 허용
로컬 파일 fallback logging 정도까지만 허용
완료 기준
샘플 코드에서 stage_start / stage_end 이벤트 전송 가능
migration event 전송 가능
aggregator와 연동 테스트용 예제 스크립트 포함
3. Codex에게 줄 작업 명세: placement_engine
작업명

node profile + runtime state 기반 heuristic placement engine 구현

목적

state_aggregator가 제공하는 node/workflow 상태를 입력으로 받아,
workflow stage를 어떤 노드에 배치하거나 이동시킬지 결정하는
초기 heuristic 기반 오케스트레이션 엔진을 구현한다.

구현해야 할 것
A. 입력
node profile
current node state
workflow stage metadata
current placement
B. node profile 형식

입력 예:

{
  "hostname": "etri-dev0001-jetorn",
  "node_type": "edge_ai_device",
  "arch": "aarch64",
  "compute_class": "medium",
  "memory_class": "low",
  "accelerator_type": "gpu_embedded",
  "preferred_workload": ["edge_inference", "preprocess"],
  "risky_workload": ["large_model_serving", "central_planner"]
}
C. stage metadata 형식

필수 필드:

stage_type
requires_accelerator
compute_intensity
memory_intensity
latency_sensitivity
input_size_kb
output_size_kb
D. 출력

배치 결정 결과

workflow_id
stage_id
target_node
decision_reason
action_type

action_type 예:

keep
migrate
offload_to_cloud
reject
E. 기본 heuristic 규칙 구현

반드시 포함할 것:

무거운 inference는 서버 우선
source-near stage는 Raspberry Pi 우선
GPU 필요 stage는 서버 또는 Jetson만 허용
memory pressure high인 노드는 신규 heavy stage 배치 금지
node_health unavailable이면 배치 금지
overload 시 sibling edge 또는 cloud로 이동 제안
F. 비용 함수 구현

초기 비용 함수 예:

compute_delay
transfer_cost
memory_penalty
overload_penalty
migration_penalty

최종 점수는 weighted sum 방식으로 구현

API 여부

초기 버전은 API 서버일 필요 없음
우선은 Python module로 구현

예:

decide_stage_placement(...)
replan_workflow(...)
제약사항
RL/LLM 사용 금지
heuristic / score 기반으로만 구현
Kubernetes API 직접 호출까지는 하지 않아도 됨
우선은 “결정 결과 반환”까지만 구현
완료 기준
node profile + node state + stage metadata를 넣으면 target node를 반환
최소 3가지 stage 유형에 대해 동작
decision reason이 함께 반환됨
테스트 코드 포함
4. Codex에게 줄 공통 환경 정보

이건 세 작업 모두에 같이 붙이면 된다.

환경
EdgeX physical-device + Kubernetes/KubeEdge node/workload cluster
nodes:
x86 server: etri-ser0001-CG0MSB
Jetson: etri-dev0001-jetorn
Raspberry Pi 5: etri-dev0002-raspi5
node role
server: cloud_server
Jetson: edge_ai_device
Raspberry Pi: edge_light_device
현재 available monitoring stack
node-exporter already running on each node
Prometheus available
use Prometheus as source for node-level CPU/memory/network metrics
architecture rule
do not implement host systemd-based collectors
prefer Kubernetes-native deployment
use Deployment for state_aggregator
use Python helper/module for workflow_reporter
placement_engine can start as standalone Python module
