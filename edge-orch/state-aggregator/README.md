작업명

Prometheus 기반 node state + workflow event 통합 상태 허브 구현

목적

KubeEdge mixed-device 환경에서,

Prometheus/node-exporter로부터 노드 상태를 읽고
workflow/stage 이벤트를 수신하고
이를 scheduler/planner가 쓸 수 있는 normalized state로 변환하는
중앙 상태 허브를 구현한다.
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
B. Prometheus reader

Prometheus HTTP API를 사용해 아래 metric을 주기적으로 읽어오기

node up/down
CPU utilization
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
mixed-device KubeEdge cluster
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