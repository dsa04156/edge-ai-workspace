# 연구 주제 정리

## 1. 주제명

이기종 혼합 디바이스 엣지 AI 워크플로우를 위한 런타임 오케스트레이션

## 2. 영문 제목 후보

- Heterogeneity-Aware Runtime Orchestration for Mixed-Device Edge AI Workflows
- Runtime Replanning for Heterogeneous Edge AI Workflow Execution
- Workflow-Aware Orchestration for Mixed-Device Edge AI Systems

## 3. 왜 이 주제를 하는가

온디바이스 AI와 엣지 AI가 확산되면서, 단일 서버가 모든 연산을 처리하는 구조는 실제 환경을 충분히 설명하지 못한다.
현실의 서비스는 디바이스, 엣지, 서버가 함께 협력하는 분산 실행 구조를 요구한다.

하지만 실제 엣지 환경은 다음 문제를 가진다.

- 노드마다 CPU, 메모리, GPU/NPU, 네트워크 특성이 다르다.
- 서비스 부하는 시간에 따라 계속 변한다.
- 정적 배치나 단순 규칙 기반 오프로딩은 쉽게 병목을 만든다.
- AI 서비스를 통째로 이동하는 coarse-grained offloading은 비효율적이다.
- mixed-device 환경에서는 단계마다 적합한 실행 위치가 다르다.

즉, 이 연구는 이기종 엣지 환경에서 AI 서비스를 어떻게 단계로 나누고, 어디에 배치하고, 언제 재배치할지를 다룬다.

## 4. 핵심 문제 정의

### 한 줄 문제 정의
서로 다른 하드웨어 구성을 가진 이기종 엣지 환경에서, 시스템 상태를 반영한 단계 수준 런타임 오케스트레이션이 정적 배치나 단순 heuristic 방식보다 더 낮은 지연 시간과 더 안정적인 자원 활용을 제공할 수 있는가?

### 세부 문제
1. 정적 배치의 한계
   - 초기에는 잘 맞더라도 부하 변화가 생기면 금방 비효율적이 된다.
2. 이기종성으로 인한 불균형
   - x86 서버, Jetson, Raspberry Pi에 같은 정책을 일괄 적용하면 병목이 생긴다.
3. 단순 상태 지표의 한계
   - CPU, 메모리만으로는 실제 병목과 서비스 지연 원인을 충분히 설명할 수 없다.
4. 런타임 재계획 필요성
   - 실제 운영에서는 전체 워크플로우를 다시 나누거나 특정 단계만 이동해야 하는 경우가 생긴다.

## 5. 핵심 아이디어

핵심 문장:

AI 서비스를 워크플로우 단계로 분해하고, 이기종 노드 상태를 반영하는 runtime orchestration engine이 기본 배치와 재배치를 수행하며, 필요할 때만 보조적인 agent-assisted planning layer가 개입한다.

중요한 점은 다음과 같다.

- 메인 기여는 런타임 오케스트레이션 시스템이다.
- agent는 보조적인 planning/policy layer다.
- 논문의 헤드라인은 agent autonomy가 아니라 stage-level orchestration이다.

## 6. 시스템 구조

### 6.1 Runtime State Layer
각 노드와 서비스의 상태를 수집하고 정규화한다.

예시 입력:
- CPU usage
- memory pressure
- accelerator availability
- node type
- network throughput / latency proxy
- queue length 또는 backlog proxy
- stage별 실행 시간
- end-to-end latency

목적:
- 의사결정 가능한 상태 벡터를 만든다.

### 6.2 Workflow Decomposition
AI 서비스를 분할 가능한 workflow DAG 또는 ordered stage 구조로 표현한다.

예시 단계:
- capture
- preprocess
- inference
- postprocess
- result delivery

목적:
- 서비스 전체 이동이 아니라 stage-level offloading을 가능하게 한다.

### 6.3 Heterogeneity-Aware Placement Engine
기본 배치와 런타임 재배치를 수행하는 핵심 엔진이다.

입력:
- 노드 capability/profile
- stage 요구 자원
- 현재 runtime state

출력:
- 각 stage의 배치 위치
- migration 여부
- offloading 여부

예시 비용 함수:

`Cost(stage, node) = compute_delay + transfer_cost + memory_pressure + migration_penalty`

### 6.4 Optional Agent-Assisted Planning Layer
planning이 꼭 필요한 상황에서만 개입하는 후순위 계층이다.

개입 조건 예시:
- workload burst
- p95 latency 급증
- 특정 노드 overload
- 반복적인 병목
- SLA violation 위험 증가
- 노드 장애 또는 성능 저하

가능한 출력:
- workflow 재분할 여부
- 특정 stage의 다른 edge 노드 이동 여부
- cloud offloading 여부
- replica 증가 여부
- degraded mode 전환 여부

## 7. 전체 동작 흐름

전체 루프:

`monitor -> normalize -> place -> execute -> feedback -> replan`

단계별 의미:
1. 각 노드의 자원 상태와 capability를 수집한다.
2. AI 서비스를 workflow stage로 모델링한다.
3. placement engine이 기본 배치를 수행한다.
4. 실행 결과와 상태 변화를 다시 반영한다.
5. 병목이나 버스트가 크면 제한적으로 재계획을 수행한다.

## 8. 연구 목표

1. 이기종 노드 상태와 capability를 반영하는 runtime state model 설계
2. AI 서비스를 workflow 단위로 분해하고 stage-level dynamic offloading이 가능한 orchestration framework 구현
3. 정적 배치와 단순 heuristic보다 나은 stage-level placement 및 replanning 효과 검증
4. 실제 mixed-device testbed에서 latency, makespan, load balance, migration overhead 기준 평가

## 9. 기대 기여점

1. mixed-device edge 환경에서 동작하는 workflow-aware runtime orchestration architecture 제안
2. heterogeneity-aware stage-level placement 및 dynamic replanning 메커니즘 제시
3. 실제 x86 + Jetson + Raspberry Pi testbed 기반 실험 검증

선택적 확장:
4. burst/overload 상황에서만 개입하는 agent-assisted replanning layer

## 10. 논문 framing 규칙

반드시 강조할 것:
- workflow-aware runtime orchestration
- heterogeneity-aware stage placement
- dynamic offloading
- stage-level replanning
- mixed-device edge AI workflows

헤드라인에서 피할 것:
- full agentic AI system
- autonomous AI scheduler replacing Kubernetes
- LLM-controlled orchestration
- observability platform paper
- RL-first control logic

## 11. 왜 이 방향이 더 강한가

이 방향은 다음 이유로 논문 성공 가능성을 높인다.

- 핵심 기여축이 하나로 모인다.
- 실제 시스템 논문으로 읽히기 쉽다.
- 평가 설계를 더 단단하게 만들 수 있다.
- agent, telemetry, RL 같은 부가 축이 본론을 흐리지 않는다.
- SEC, Middleware, FGCS, IEEE Access 쪽 framing과 자연스럽게 맞는다.
