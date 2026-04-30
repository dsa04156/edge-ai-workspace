# 투고처 전략

## 목표
현재 연구 방향에서 논문 성공 가능성을 가장 높이는 투고처 전략을 정한다.

---

## 1. 이 연구의 가장 적절한 해석

이 프로젝트는 다음 성격의 논문으로 설명하는 것이 가장 맞다.

- edge systems
- runtime orchestration
- heterogeneous resource management
- workflow-stage placement and offloading
- mixed-device edge AI execution

반대로, 이 논문은 기본적으로 다음 주제가 아니다.

- 범용 AI agent 논문
- telemetry portability 논문
- 순수 네트워킹 논문
- 범용 cloud management 논문
- observability platform 논문

---

## 2. 투고처 적합도 순위

### A. 적합한 학회
1. **ACM/IEEE SEC**
2. **ACM Middleware**
3. **ACM SoCC**
4. **USENIX NSDI**

### B. 적합한 저널
1. **Future Generation Computer Systems (FGCS)**
2. **IEEE Access**
3. **IEEE Internet of Things Journal**

---

## 3. 투고처별 권장 framing

### SEC
다음을 강조할 때 가장 잘 맞는다.

- edge computing 동기
- mixed-device edge의 실제 문제
- offloading / runtime orchestration
- 실제 edge AI workflow

가장 강한 스토리가 edge systems paper일 때 적합하다.

### Middleware
다음을 강조할 때 가장 잘 맞는다.

- runtime control plane
- system architecture
- state normalization
- API / orchestration loop / path separation

가장 강한 스토리가 distributed systems platform paper일 때 적합하다.

### SoCC
다음을 강조할 때 적합하다.

- edge-cloud continuum
- heterogeneous infrastructure 전반의 서비스 배치
- cloud systems의 edge 확장

cloud 측 framing이 충분히 강할 때만 고려한다.

### NSDI
다음을 강조할 때 적합하다.

- distributed systems guarantees
- cross-node coordination behavior
- dynamic condition에서의 networking/runtime effect

단순 edge management가 아니라 distributed systems problem으로 설득할 수 있을 때만 고려한다.

### FGCS
논문이 충분히 성숙하고 저널 분량이 필요할 때 적합하다.

- 전체 시스템 설명
- 더 깊은 평가
- 더 넓은 workflow 및 infrastructure 서사

### IEEE Access
채택 확률과 실용적 공학 가치를 우선할 때 적합하다.

- full system build
- practical deployment detail
- strong measurement and implementation story

---

## 4. 권장 제출 전략

### 전략 A: 학회 우선, prestige와 현실성 균형
1. SEC 투고
2. 거절 시 Middleware framing으로 재구성
3. 다시 거절되면 FGCS 또는 IEEE Access 저널형으로 전환

### 전략 B: 가장 높은 출판 확률 우선
1. IEEE Access 투고
2. 이후 추가 실험과 확장 내용이 충분할 때만 FGCS 확장판 고려

### 전략 C: 아키텍처 중심 시스템 경로
1. Middleware 투고
2. 필요 시 FGCS로 하향 전환

---

## 5. 선택 가이드

다음일 때 **SEC**를 고른다.

- 가장 강한 스토리가 실제 mixed-device 환경의 edge AI workflow orchestration일 때

다음일 때 **Middleware**를 고른다.

- 가장 강한 스토리가 runtime control plane과 state/decision architecture일 때

다음일 때 **FGCS**를 고른다.

- 더 넓은 분량으로 architecture, evaluation, discussion을 충분히 담고 싶을 때

다음일 때 **IEEE Access**를 고른다.

- venue prestige보다 출판 확률을 우선할 때

---

## 6. 바꾸면 안 되는 원칙

먼저 venue를 정하고 그에 맞춰 핵심 기여를 비틀지 않는다.
반대로 다음 순서를 지킨다.

1. 논문의 진짜 중심을 고정한다.
2. 그 중심을 가장 강하게 설명하는 버전을 쓴다.
3. 그 스토리와 가장 자연스럽게 맞는 venue를 고른다.
