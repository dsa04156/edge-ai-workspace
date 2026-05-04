# 평가 계획

## 목표
오케스트레이션 논문을 publishable하게 만들기 위한 최소 평가 패키지를 정의한다.

---

## 1. 핵심 시스템 질문

혼합 디바이스 엣지 AI 워크플로우를 위한 이기종성 인지형 런타임 오케스트레이션이, 런타임 변화가 있는 환경에서 정적 배치와 단순 heuristic 배치보다 더 나은 성능을 낼 수 있는가?

---

## 2. 테스트베드

실제 mixed-device 환경을 사용한다.

- x86 cloud/control 노드
- x86 worker 노드
- Jetson edge 노드
- Raspberry Pi edge 노드

런타임 환경:
- Kubernetes / KubeEdge
- 컨테이너 기반 stage 실행
- Prometheus / Grafana 재사용

---

## 3. 주력 워크플로우

워크플로우는 하나를 깊게 평가한다.

권장:
- 스마트팩토리 비전 파이프라인

권장 stage 구조:
1. capture
2. preprocess
3. inference
4. postprocess
5. result delivery

주력 워크플로우가 단단해지기 전에는 얕은 다중 워크플로우를 늘리지 않는다.

---

## 4. 비교군

### Baseline A: 정적 배치
고정된 stage-to-node 매핑.

### Baseline B: 단순 heuristic 배치
런타임 replanning 없이 1회성 resource-aware placement 수행.

### Baseline C: 제안 방식의 runtime orchestration
런타임 상태를 반영하는 stage-level placement.

### Baseline D: 제안 방식의 runtime orchestration + replanning
Baseline C에 overload / burst 기반 replanning을 추가한 형태.

### 선택 Baseline E: planning layer
충분히 성숙했고 역할이 명확히 분리될 때만 포함한다.

---

## 5. 시나리오

### S1. 정상 부하
안정적인 workflow 유입률을 유지한다.

### S2. 버스트 부하
workflow 도착률 또는 특정 stage 부하가 순간적으로 급증한다.

### S3. 지속 과부하
일부 노드가 장시간 높은 압박 상태를 겪는다.

### S4. 전송 비용 스트레스
cross-node transfer cost가 유의미하게 커지는 상황을 만든다.

### S5. 노드 열화 / 부분 장애
가능하다면 부분적 성능 저하 또는 노드 가용성 저하를 유도한다.

---

## 6. 지표

### End-to-end 서비스 지표
- end-to-end latency
- p95 / p99 latency
- makespan
- workflow completion time

### 자원 지표
- CPU utilization
- memory pressure
- network throughput / transfer load
- 가능하면 accelerator utilization

### 오케스트레이션 지표
- placement decision latency
- 재할당 / migration 횟수
- failed placement 수
- unstable placement 수
- scheduling overhead

### 실용성 지표
- burst 부하에서의 개선폭
- overload 상황에서의 개선폭
- orchestrator가 추가한 오버헤드

---

## 7. 필수 ablation

ablation은 어떤 요소가 실제로 필요한지 보여줘야 한다.

### A1. 이기종성 인지 제거
모든 노드를 동일한 것으로 취급한다.

### A2. stage 분해 제거
서비스 전체 단위 배치로 바꾼다.

### A3. replanning 제거
초기 1회 결정만 사용한다.

### A4. transfer-cost 모델 제거
cross-node handoff cost를 무시한다.

### A5. memory-pressure 항 제거
메모리를 배치 판단 요인에서 뺀다.

이 ablation이 없으면 리뷰어는 쉽게 이렇게 묻는다.

`왜 전체 시스템이 꼭 필요한가?`

---

## 8. 데이터 전달 평가 요구사항

실제 AI 워크플로우 실행에는 stage handoff가 필요하므로 최소한 다음은 평가한다.

- same-node local handoff 경로
- cross-node handoff 경로
- handoff overhead가 end-to-end latency에 미치는 영향

Redis나 MinIO를 도입한다면 다음도 측정한다.

- control/state handoff overhead
- artifact handoff overhead
- makespan과 stage transition delay에 미치는 영향

---

## 9. 최소 publishable evidence

논문이 publishable하려면 최소한 아래 다섯 가지를 보여줄 수 있어야 한다.

1. 정적 배치는 충분하지 않다.
2. stage-level orchestration이 도움이 된다.
3. heterogeneity-aware placement가 도움이 된다.
4. runtime variation에서 replanning이 도움이 된다.
5. overhead가 허용 가능한 수준이다.

이 중 하나라도 빠지면 논문은 크게 약해진다.

---

## 10. 최종 원칙

넓지만 얕은 평가보다, 작더라도 빈틈없는 평가가 낫다.
