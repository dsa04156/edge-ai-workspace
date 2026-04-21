# 시스템 개요

## 1. 프로젝트 목표

이 프로젝트는 KubeEdge/Kubernetes 기반의 혼합 디바이스 엣지 AI 환경을 대상으로 한다.

대상 환경:
- x86 제어/클라우드 서버 1대
- x86 워커 서버 1대
- Jetson 엣지 AI 디바이스 1대
- Raspberry Pi 5 엣지 디바이스 1대

구축 목표:
- AI 서비스를 워크플로우 단계로 분해한다.
- 노드 상태와 워크플로우 실행 상태를 관측한다.
- 단계별 배치, 마이그레이션, 오프로딩을 동적으로 수행한다.
- 필요할 때만 보조적인 agent-assisted replanning을 추가한다.

이 시스템은 범용 쿠버네티스 스케줄러가 아니다.
핵심은 워크플로우 인지형 엣지 런타임 오케스트레이션이다.

---

## 2. 왜 이 시스템이 필요한가

대상 환경은 강한 이기종성을 가진다.

- 아키텍처가 다르다: `amd64`와 `arm64`
- 가속기 구성이 다르다
- 메모리 용량과 연산 성능이 다르다
- 네트워크 조건과 지연 특성이 다르다
- 같은 워크로드라도 단계별 병목 위치가 달라진다

이 때문에 다음 문제가 발생한다.

- 정적 배치는 금방 비효율적이 된다.
- 한 노드만 병목이 되고 다른 노드는 놀 수 있다.
- CPU/메모리만 보는 단순 판단으로는 실제 서비스 지연 원인을 설명하기 어렵다.
- AI 서비스를 하나의 큰 단위로 취급하면 세밀한 오프로딩이 어렵다.

따라서 AI 서비스는 다음과 같은 단계로 나누어 다루어야 한다.

- capture
- preprocess
- inference
- postprocess
- result delivery

그리고 시스템은 다음 질문에 답해야 한다.

- 어떤 단계는 데이터 소스 가까이에 남겨야 하는가
- 어떤 단계는 Jetson으로 보내야 하는가
- 어떤 단계는 서버로 보내야 하는가
- 과부하나 SLA 위험이 생기면 언제 재배치를 해야 하는가

---

## 3. 기존 구성요소와 신규 구성요소

### 이미 존재하는 것
- KubeEdge / Kubernetes 클러스터
- Prometheus
- Grafana
- node-exporter

### 그대로 재사용하는 것
Prometheus와 node-exporter를 노드 수준 원시 메트릭 수집 경로로 사용한다.

주요 수집 항목:
- CPU 사용률
- 메모리 사용률
- 네트워크 송수신량
- load average
- 노드 생존 여부

### 새로 구현하는 핵심 구성요소
1. `state_aggregator`
2. `workflow_reporter`
3. `placement_engine`
4. `agent_assisted_planner`(후순위, 선택적)

---

## 4. 상위 수준 아키텍처

### A. Prometheus / node-exporter
노드 수준 원시 메트릭을 제공한다.

### B. workflow_reporter
워크플로우 및 단계 실행 이벤트를 보고한다.

### C. state_aggregator
다음을 결합한다.

- Prometheus에서 가져온 노드 메트릭
- workflow_reporter가 보낸 워크플로우 이벤트

다음 상태를 생성한다.

- 노드 상태
- 워크플로우 상태
- 정규화된 상태
- 스케줄링/재계획 판단용 요약 상태

### D. placement_engine
다음을 입력으로 사용한다.

- 노드 capability profile
- 현재 런타임 상태
- 단계 메타데이터

다음 결정을 반환한다.

- 유지
- 마이그레이션
- 서버 오프로딩
- 재배치

### E. agent-assisted planner
후순위의 선택적 계층이다.
기본 동작의 주체가 아니라, 급격한 상태 변화에서만 재계획을 보조한다.

---

## 5. 핵심 설계 원칙

1. 노드 메트릭은 Prometheus를 재사용한다.
2. 모니터링 경로와 제어 경로를 분리한다.
3. AI 서비스는 단일 덩어리가 아니라 워크플로우 단계로 취급한다.
4. 초기 배치와 재배치는 heuristic 기반으로 시작한다.
5. agent-assisted planning은 핵심 기여가 아니라 확장 기능으로 둔다.
6. 이기종성 인지형 상태 모델을 먼저 단단하게 만든다.

---

## 6. 주요 입력 데이터

### 노드 수준 원시 메트릭
Prometheus / node-exporter 기반:

- CPU 사용률
- 메모리 사용률
- load average
- 네트워크 RX/TX
- 노드 up/down

### 워크플로우 수준 이벤트
workflow_reporter 기반:

- `stage_start`
- `stage_end`
- `migration_event`
- `workflow_end`
- `failure_event`

---

## 7. 시스템의 주요 출력

### 제어 평면용 출력
- 정규화된 노드 상태
- 워크플로우 긴급도
- SLA 위험도
- 배치 안정성
- 단계별 배치 결정 사유

### 사람을 위한 출력
- Grafana 대시보드
- JSONL 원시 이벤트 로그
- 실험 결과 및 평가 지표

---

## 8. 구현 우선순위

1. `state_aggregator` 구축
2. `workflow_reporter` 구축
3. `placement_engine` 구축
4. 실제 워크플로우 1개 연동
5. 단계 간 데이터 전달 경로 정리
6. 과부하/버스트 상황 재계획 추가
7. 선택적 agent-assisted planning 계층 추가
