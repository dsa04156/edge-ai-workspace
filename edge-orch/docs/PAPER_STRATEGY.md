# 논문 전략

## 목표
현재 mixed-device edge AI orchestration 프로젝트의 논문 채택 가능성을 최대화한다.

이 문서는 다음 현실적인 목표를 전제로 한다.

- 적합도와 채택 확률을 최대화한다.
- novelty sprawl을 피한다.
- `SEC` / `Middleware` / `FGCS` / `IEEE Access`에 맞는 스토리로 수렴한다.

목표는 여러 갈래로 퍼진 시스템 설명을 하나의 집중된 systems paper로 정리하는 것이다.

---

## 1. 가장 중요한 전략적 결정

### 이렇게 해야 한다
논문의 중심은 다음으로 잡는다.

**이기종 혼합 디바이스 엣지 AI 워크플로우를 위한 런타임 오케스트레이션**

### 이렇게 하면 안 된다
다음을 동시에 메인 기여로 올리지 않는다.

- agent-assisted planning
- RL scheduling
- eBPF telemetry
- 분산 데이터 미들웨어
- 전체 edge virtualization
- 범용 orchestration 플랫폼

강한 시스템 논문은 하나의 지배적 기여축이 필요하다.
다섯 개의 동등한 novelty 축이 필요한 것이 아니다.

---

## 2. 권장 논문 메시지

### 핵심 메시지
혼합 디바이스 엣지 AI 워크플로우는 정적 배치와 단일 서비스 단위 배포만으로는 안정적으로 처리하기 어렵다.
이기종 노드 상태를 반영해 단계 수준 배치와 재계획을 수행하는 런타임 오케스트레이션 시스템은, 실제 런타임 변화 아래에서 latency, makespan, load balance를 개선할 수 있다.

### 리뷰어가 한 문장으로 가져가야 하는 메시지
이 논문은 실제 mixed-device edge AI 환경에서 워크플로우 단계를 이기종 노드에 동적으로 배치하고 런타임 변화에 따라 재계획하는 시스템을 제시한다.

---

## 3. 헤드라인에서 내려야 할 것

### Agent-assisted planning
다음 정도로만 둔다.

- 제한된 확장 기능
- 늦은 단계의 replanning helper
- 선택적인 policy layer

제목의 첫 명사가 되게 두지 않는다.

### eBPF telemetry
사용하더라도 다음 수준에 둔다.

- 추후 측정 고도화 가능성
- 보조적 observability 경로

논문 전체를 telemetry portability나 kernel-level measurement 중심으로 다시 설계하지 않는 한, 메인 주제로 올리지 않는다.

### RL / DRL
첫 구현 마일스톤이나 메인 내러티브로 두지 않는다.
먼저 heuristic baseline을 단단히 만들고, 학습 기반 정책은 시스템 기여가 충분히 굳어진 다음에만 고려한다.

---

## 4. 채택 확률을 높이는 범위 축소

### 유지할 것
- workflow DAG 또는 ordered stage 구조
- stage-level dynamic offloading
- node capability profile
- normalized runtime state
- heterogeneity-aware placement
- runtime replanning
- 실제 mixed-device testbed

### 자르거나 미룰 것
- telemetry 자체를 주제로 한 별도 시스템 논문 방향
- full agentic control plane 주장
- 범용 edge platform 주장
- 평가와 직접 연결되지 않는 broad digital twin 서사
- 깊이가 약한 다수의 워크로드

---

## 5. venue별 가장 강한 framing

### SEC framing
다음 언어를 중심으로 쓴다.

- edge systems
- mixed-device orchestration
- dynamic offloading
- real edge AI workflows
- practical edge computing challenges

### Middleware framing
다음 언어를 중심으로 쓴다.

- runtime control plane
- state abstraction
- placement API와 decision loop
- monitoring/control path separation
- distributed systems architecture

### FGCS framing
다음 언어를 중심으로 쓴다.

- distributed runtime management
- heterogeneous infrastructure 위의 workflow execution
- edge-cloud-IoT orchestration
- 재현 가능한 시스템 평가

### IEEE Access framing
다음 언어를 중심으로 쓴다.

- complete system implementation
- real-world engineering solution
- broad applicability
- practical deployment and measurements

---

## 6. 리뷰어가 반드시 답을 얻어야 하는 질문

논문은 아래 질문에 모두 답해야 한다.

1. 왜 정적 배치로는 부족한가?
2. 왜 stage-level orchestration이 필요한가?
3. 왜 이기종성이 decision loop에서 중요하게 작동하는가?
4. 왜 deployment 시 1회 결정이 아니라 runtime replanning이 필요한가?
5. 오케스트레이션 메커니즘 자체의 비용은 얼마인가?
6. burst, overload, node degradation에서 어떻게 동작하는가?
7. 하나의 toy setup을 넘어서 어느 정도 일반화 가능한가?

이 중 하나라도 약하면 채택 가능성이 급격히 떨어진다.

---

## 7. 권장 기여 구조

주요 기여는 정확히 세 개로 잡는 것이 가장 안전하다.

### 권장 기여 세트
1. mixed-device edge AI workflow를 위한 runtime orchestration architecture
2. heterogeneity-aware stage-level placement 및 replanning mechanism
3. x86 + Jetson + Raspberry Pi 기반 실제 mixed-device evaluation

### 선택적 4번째 기여
지원 근거가 충분할 때만:
4. burst/overload 상황용 제한적 agent-assisted replanning layer

네 번째가 앞의 세 가지를 약하게 만들면 본 논문에서는 빼는 편이 낫다.

---

## 8. 제목 전략

### 강한 제목 패턴
**Heterogeneity-Aware Runtime Orchestration for Mixed-Device Edge AI Workflows**

### 허용 가능한 변형
- Stage-Level Dynamic Offloading for Mixed-Device Edge AI Workflows
- Runtime Replanning for Heterogeneous Edge AI Workflow Execution
- Workflow-Aware Orchestration for Mixed-Device Edge AI Systems

### 피해야 할 제목 패턴
- Agent-Assisted Everything for Edge AI
- Intelligent Autonomous Agentic Orchestration Platform
- Capability-Aware eBPF Telemetry and DRL Scheduling and Dynamic Offloading

이런 제목은 범위를 불필요하게 넓히고 중심을 흐린다.

---

## 9. 채택 확률을 높이는 평가 전략

### 워크플로우는 하나를 깊게
얕은 데모 여러 개보다 강한 실제 워크플로우 하나가 낫다.

권장 후보:
- 스마트팩토리 비전 파이프라인

예시 단계:
- capture
- preprocess
- inference
- postprocess
- result delivery

### 필수 baseline
최소한 다음 비교군은 있어야 한다.

1. 정적 배치
2. 단순 heuristic 배치
3. 이기종성 인지형 stage-level placement
4. overload/burst 시 replanning이 있는 stage-level placement

### 필수 시나리오
- 정상 부하
- 버스트 부하
- 지속 과부하
- 네트워크 열화 또는 transfer pressure
- 가능하면 node degradation / unavailability

### 필수 지표
- end-to-end latency
- p95 / p99 latency
- makespan
- resource utilization
- migration / replanning overhead
- failed or unstable placements
- scheduler / orchestrator overhead

### 강한 ablation
- heterogeneity awareness 없음
- stage decomposition 없음
- replanning 없음
- transfer-cost term 없음
- memory-pressure term 없음

ablation은 headline 성능만큼 중요하다.

---

## 10. 가장 피하기 쉬운 큰 실수

1. 메인 아이디어가 너무 많다.
2. 지배적인 대표 use case가 없다.
3. 시스템 claim 대신 marketing 문장이 많다.
4. orchestration overhead 비용 계산이 없다.
5. baseline이 약하다.
6. overload/burst 시나리오가 없다.
7. agent나 RL이 너무 일찍 들어와 본론을 덮는다.

---

## 11. 현실적인 제출 사다리

### 가장 적합한 conference 경로
1. SEC
2. Middleware
3. 거절 시 FGCS 또는 IEEE Access

### 안전한 publication 경로
1. IEEE Access
2. FGCS

### 위험하지만 상위 prestige 경로
1. SEC
2. Middleware
3. SoCC
4. NSDI

---

## 12. 최종 조언

채택 가능성을 최우선으로 둔다면:

- 논문 범위를 runtime orchestration에 집중한다.
- agent-assisted planning은 확장 기능으로 내린다.
- 핵심 기여는 정확히 세 개로 유지한다.
- 실제 mixed-device 평가를 가장 강한 증거로 만든다.
