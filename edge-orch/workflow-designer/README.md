# Workflow Designer MVP

## 목적

`edge-orch/workflow-designer/`는 KubeEdge 혼합 디바이스 Edge AI PoC에서 서비스 논리, 실행 배치, 데이터 전송 경로를 분리해 보여주는 정적 MVP다.

현재 범위는 read-only + dry-run이다.

수행하지 않는 것:

- Kubernetes apply/delete/rollout restart
- 실제 Pod 배포
- MQTT command publish
- actuator command 실행
- Device CR 수정
- runtime migration/offloading 실행
- LLM/RAG/agent 자동 제어

## 실행 방법

```bash
cd /home/etri/jinuk
python3 -m http.server 8080
```

```text
http://localhost:8080/edge-orch/workflow-designer/index.html
```

## UI 구조

### A. Service Workflow DAG View

서비스의 논리 stage 흐름을 보여준다.

- input device node
- stage node
- platform endpoint node
- stage 사이 edge label: output data name + transport

예: `Input Device -> collect -> preprocess -> inference -> event-publish -> Dashboard / State Aggregator / InfluxDB`

### B. Stage Placement View

각 stage가 어떤 compute node에서 실행되는지 보여준다.

- stage
- type
- target node
- input/output
- required resource

target node 변경은 이 View에서 select box 또는 compute node drop target으로만 수행한다. 중앙 DAG는 서비스 논리만 보여주며 node column 배치를 하지 않는다.

### C. Data Transport / Endpoint View

각 output data의 전달 경로를 표로 보여준다.

- data name
- producer stage
- producer node
- transport type
- consumer stage 또는 endpoint
- consumer node 또는 platform service

Platform endpoint는 compute node와 분리한다.

- MQTT Broker
- InfluxDB
- State Aggregator
- Dashboard

### Experimental Dynamic Workflow Lab

기존 workflow designer 안에 분리된 실험 영역으로 표시한다. 선택된 example workflow를 기준으로 Current State, Generated Workflow Proposal, Placement Plan, Dry-run Validation 네 가지 read-only/dry-run 패널만 렌더링한다.

경계: experimental, read-only, dry-run only. Kubernetes apply/delete/restart, MQTT command publish, actuator command, Device CR mutation, runtime migration/offloading execution, autonomous platform control은 수행하지 않는다. Production dashboard나 `state-aggregator` 정적 UI와도 분리한다.

## 데이터 모델

workflow example은 다음 구조를 포함한다.

- `serviceName`
- `inputDevices[]`
- `stages[]`
- `edges[]`
- `placements[]`
- `endpoints[]`
- `transports[]`

`edges[]`는 DAG의 논리 연결과 data label을 표현한다.

```json
{ "from": "preprocess", "to": "inference", "data": "feature-vector", "transport": "http" }
```

`transports[]`는 실제 data delivery 관점의 producer/consumer/endpoint를 표현한다.

```json
{ "producer": "event-publish", "consumer": "Dashboard", "endpoint": "Dashboard", "data": "mqtt-event", "transport": "http" }
```

## 기본 예시

- `factory-anomaly-detection`
  - vib/rpi-vib input device
  - collect → preprocess → inference → event-publish
  - Dashboard / State Aggregator / optional InfluxDB sink
- `environment-monitoring`
  - env/rpi-env input device
  - collect → normalize → threshold-check
  - InfluxDB storage sink, Dashboard sink
- `actuator-command-monitoring`
  - act/rpi-act input device
  - command-state-read → state-validate → event-publish → dashboard sink
  - actuator command 실행 없음, 상태 확인만 표시

## Dry-run validation rules

- 모든 stage에 target node가 지정되어야 한다. 누락 시 FAIL
- target node가 compute node model에 없으면 FAIL
- stage input/output chain이 끊기면 FAIL
- producer/consumer edge가 유효하지 않으면 FAIL
- transport producer/consumer가 stage/endpoint에 없으면 FAIL
- endpoint model이 없으면 FAIL
- event-publish에서 MQTT Broker 연결이 없으면 FAIL
- dashboard sink 연결이 없으면 WARN
- service input device가 없으면 WARN
- inference stage가 Raspberry Pi 5에 배치되면 WARN
- FAIL이 없으면 dry-run plan generation PASS

## state-aggregator API 연동

브라우저에서 `/state/dashboard`를 read-only로 시도한다. 실패하면 example mode로 동작한다.

## 검증

```bash
cd /home/etri/jinuk
node --check edge-orch/workflow-designer/workflow-designer.js
node tools/check_workflow_designer.js
python3 scripts/build-docs-html.py
python3 tools/docs_consistency/generate_report.py
```
