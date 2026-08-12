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
자원증강 탭은 `GET /state/virtual-resources`를 통해 AI HAT/GPU/cache 같은
read-only Resource Profile과 관측된 실행 인스턴스를 표시한다.
Kubernetes CRD로 관리되는 자원증강 상태는 `GET /state/augmentation-resources`,
`GET /state/device-augmentations`를 통해 조회하며 dashboard `자원증강` 탭에서
`DeviceAugmentation.status.conditions`와 `selectedResources`를 read-only로 표시한다.
이 경로는 workload 생성, 자동 offloading, runtime migration을 수행하지 않는다.

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
- state-aggregator 자체는 Kubernetes 쓰기 권한이 없고, 외부/Argo runtime을
  restart/retire하지 않는다.
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
