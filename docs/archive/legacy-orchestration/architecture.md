# 아키텍처

## 1. 노드와 역할

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

### Jetson 노드
- hostname: `etri-dev0001-jetorn`
- role: `edge_ai_device`
- arch: `arm64`
- preferred for:
  - edge inference
  - preprocess
  - latency-sensitive stages

### Raspberry Pi 5 노드
- hostname: `etri-dev0002-raspi5`
- role: `edge_light_device`
- arch: `arm64`
- preferred for:
  - capture
  - lightweight preprocess
  - sensor ingestion
  - lightweight postprocess

---

## 2. 노드 프로파일 스키마

각 노드는 고정된 capability profile로 표현한다.

예시 필드:
- `hostname`
- `node_type`
- `arch`
- `compute_class`
- `memory_class`
- `accelerator_type`
- `runtime_role`
- `preferred_workload`
- `risky_workload`

예시:

```json
{
  "hostname": "etri-dev0001-jetorn",
  "node_type": "edge_ai_device",
  "arch": "aarch64",
  "compute_class": "medium",
  "memory_class": "low",
  "accelerator_type": "gpu_embedded",
  "runtime_role": ["inference_candidate", "edge_processing_candidate"],
  "preferred_workload": ["edge_inference", "preprocess", "latency_sensitive_stage"],
  "risky_workload": ["large_model_serving", "many_concurrent_workflows", "central_planner"]
}
```

---

## 3. `state_aggregator`

### 목적
다음 역할을 수행하는 중앙 상태 허브다.

- Prometheus에서 노드 메트릭을 읽는다.
- 워크플로우/단계 이벤트를 수신한다.
- 오케스트레이션용 정규화 상태를 만든다.
- 배치 로직이 사용할 경량 API를 제공한다.

### 배포 형태
- Kubernetes Deployment
- 서버 노드 배치 우선

### 입력
#### A. Prometheus 기반 메트릭
최소 질의 항목:

- 노드 상태 `up`
- CPU 사용률
- 메모리 사용 비율
- load average
- 네트워크 RX/TX 속도

#### B. workflow_reporter 기반 이벤트
최소 이벤트:

- `stage_start`
- `stage_end`
- `migration_event`
- `workflow_end`
- `failure_event`

### 출력 API
반드시 제공해야 하는 API:

- `GET /state/nodes`
- `GET /state/node/{hostname}`
- `GET /state/workflows`
- `GET /state/workflow/{workflow_id}`
- `GET /state/summary`
- `POST /workflow-event`

### 내부 저장 방식
초기 버전 기준:

- 최신 상태는 메모리 유지
- 원시 로그는 JSONL 저장

예시 파일:

- `data/node_state.jsonl`
- `data/workflow_event.jsonl`

### 인스턴스 매핑
Prometheus `instance` 값은 논리적 hostname으로 매핑해야 한다.

권장 경로:

- `app/config/instance_map.json`

---

## 4. `workflow_reporter`

### 목적
워크플로우와 단계 실행 이벤트를 aggregator로 전달한다.

### 구현 형태
초기 버전은 Python helper/module로 구현한다.

### 최소 helper 함수 예시
- `report_stage_start(...)`
- `report_stage_end(...)`
- `report_migration(...)`
- `report_failure(...)`

### 전송 대상
- `POST /workflow-event`

### 최소 이벤트 필드
- `event_type`
- `timestamp`
- `workflow_id`
- `workflow_type`
- `stage_id`
- `stage_type`
- `assigned_node`

### 선택 필드
- `exec_time_ms`
- `queue_wait_ms`
- `transfer_time_ms`
- `from_node`
- `to_node`
- `reason`
- `status`

---

## 5. `placement_engine`

### 목적
워크플로우 단계가 어디서 실행되어야 하는지 결정한다.

### 구현 형태
초기 버전은 독립 서비스가 아니라 Python 모듈로 구현한다.

### 입력
- 노드 profile
- 현재 노드 상태
- 워크플로우 단계 메타데이터
- 현재 배치 상태

### 출력
결정 객체 예시:

- `workflow_id`
- `stage_id`
- `target_node`
- `decision_reason`
- `action_type`

`action_type` 예시:

- `keep`
- `migrate`
- `offload_to_cloud`
- `reject`

### 초기 판단 규칙
- heavy inference는 서버 우선
- 데이터 소스 인접 단계는 Raspberry Pi 우선
- GPU 필요 단계는 서버 또는 Jetson만 허용
- 메모리 압박이 높은 노드에는 무거운 단계를 추가 배치하지 않음
- 사용 불가 노드는 절대 선택하지 않음
- 과부하 시 sibling edge 재분산 또는 cloud offloading을 검토

### 초기 구현 원칙
- heuristic / weighted score 우선
- RL 사용 금지
- LLM 기반 제어 금지

---

## 6. 정규화 상태 모델

### 노드 수준 상태
- `compute_pressure`: `low` / `medium` / `high`
- `memory_pressure`: `low` / `medium` / `high`
- `network_pressure`: `low` / `medium` / `high`
- `node_health`: `healthy` / `degraded` / `unavailable`

### 워크플로우 수준 상태
- `workflow_urgency`
- `sla_risk`
- `placement_stability`

이 상태는 `state_aggregator` 내부에서 생성한다.

---

## 7. 모니터링 경로와 제어 경로

### 모니터링 경로
- Prometheus
- Grafana
- JSONL 원시 로그

### 제어 경로
- `state_aggregator` API
- `placement_engine`
- 이후 선택적으로 `agent_assisted_planner`

Prometheus와 Grafana는 제어 평면이 아니다.
이들은 모니터링 인프라다.
