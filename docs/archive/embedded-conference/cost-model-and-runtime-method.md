# Cost Model and Runtime Method

## 목적

이 문서는 현재 구현 기준으로 아래 2가지를 한 번에 설명한다.

- 비용모델(cost model)을 어떤 데이터로 만들고 어떻게 업데이트하는가
- 런타임 orchestration이 어떤 구성으로 어떻게 동작하는가

기준 코드는 아래 컴포넌트다.

- `state-aggregator`
- `placement-engine`
- `workflow-executor`

---

## 1. 전체 구조

1. `workflow-executor`가 stage 실행 과정에서 이벤트를 발행한다.
2. `state-aggregator`가 이벤트를 수집하고 observation(JSONL)을 누적한다.
3. `state-aggregator`가 observation으로 stage/migration 통계를 재계산한다.
4. `placement-engine`이 `/state/cost-model`을 조회해 node state + cost stats를 가져온다.
5. `placement-engine`이 stage별 expected cost를 계산하고 keep/migrate/offload를 결정한다.
6. `workflow-executor`가 결정 결과대로 Job을 생성하고 실행한다.

---

## 2. 비용모델 생성 방식

### 2.1 입력 데이터

비용모델은 두 가지 observation 로그를 기반으로 만든다.

- `stage_observation.jsonl`
- `migration_observation.jsonl`

이 로그는 `workflow-executor` 이벤트(`stage_job_created`, `stage_start`, `stage_end`, `migration_event`)를 `state-aggregator`가 재구성해 생성한다.

### 2.2 stage observation 생성

`stage_end`가 들어오면 같은 `(workflow_id, stage_id)`의 `stage_start`와 결합해 아래를 만든다.

- `observed_latency_ms`
- `queue_wait_ms`
- `transfer_time_ms`
- `warmup_ms`
- `action_type`
- `from_node`, `to_node`

### 2.3 migration observation 생성

`migration_event` 이후 `stage_start`가 해당 `to_node`에서 시작되면 migration observation을 기록한다.

- `migration_time_ms = started_at - decided_at`
- 키: `(stage_type, from_node, to_node)`

### 2.4 통계 재계산

`state-aggregator`는 observation 갱신 시마다 stats를 rebuild한다.

- StageCostStats
  - `exec_median_ms`
  - `exec_ema_ms` (alpha=0.5)
  - `queue_median_ms`
  - `warmup_median_ms`
  - `recent_migration_count_last_hour`
  - `placement_stability` (`stable`/`moving`/`unstable`)
- MigrationCostStats
  - `migration_median_ms`
  - `migration_ema_ms` (alpha=0.5)

최종 스냅샷은 `GET /state/cost-model`로 제공된다.

---

## 3. placement cost 계산식

각 후보 노드에 대해 `placement-engine`은 아래 합으로 `expected_cost_ms`를 계산한다.

$$
\text{expected\_cost} =
\text{exec} + \text{queue} + \text{transfer} + \text{warmup} + \text{migration} + \text{resource\_penalty} + \text{instability\_penalty}
$$

score breakdown에는 다음이 포함된다.

- `expected_cost_ms`
- `exec_ms`, `queue_ms`, `transfer_ms`, `warmup_ms`, `migration_ms`
- `resource_penalty_ms`, `instability_penalty_ms`
- `used_exec_fallback`, `used_migration_fallback`
- legacy heuristic 항목(`legacy_compute_delay`, `legacy_transfer_cost`, ...)

추가 비교 값:

- `expected_keep_cost_ms`
- `expected_target_cost_ms`
- `net_gain_ms = keep - target`
- `decision_margin_ms`

---

## 4. selective decision rule

현재 stage가 실행 중인 노드를 `current`, 최소 비용 후보를 `best`라고 할 때:

1. `best == current` 이면 `keep` (`selective_keep_best_node`)
2. `net_gain < decision_margin` 이면 `keep` (`selective_keep_below_margin`)
3. `net_gain >= decision_margin` 이면 `migrate` 또는 `offload_to_cloud` (`selective_migrate_above_margin`)

margin 기본 규칙:

- 기본 900ms
- `compute_pressure=high` 또는 `node_health=degraded`면 600ms
- `placement_stability=unstable`이면 +300ms

즉,

- 정상/안정 구간: 보수적 이동
- 고압/불안정 구간: 민감한 이동

---

## 5. 런타임 구성과 실행 루프

### 5.1 구성 컴포넌트

- `state-aggregator`
  - node metric 수집/정규화
  - workflow event 수집
  - cost model state 제공
- `placement-engine`
  - `/placement/decide`
  - `/placement/replan`
- `workflow-executor`
  - stage별 실행, Job 생성/대기
  - migration/transition/event 발행

### 5.2 stage 실행 단위 루프

1. executor가 현재 placement 확인
2. placement-engine `/placement/decide` 호출
3. 필요 시 `migration_event` 발행
4. Kubernetes Job 생성 (`nodeSelector`로 target 고정)
5. `stage_job_created` -> `stage_start` -> `stage_end` 이벤트 발행
6. aggregator가 observation/stats 업데이트

### 5.3 workflow 단위 replanning

`execute_workflow` 경로에서 남은 stage들에 대해 `/placement/replan`을 호출해 stage별 decision을 선반영할 수 있다.

- replan 성공: planned decision으로 실행
- replan 실패: stage 단건 decide fallback

---

## 6. API 요약

- state-aggregator
  - `POST /workflow-event`
  - `GET /state/cost-model`
  - `GET /state/nodes`
  - `POST /internal/refresh`
- placement-engine
  - `POST /placement/decide`
  - `POST /placement/replan`
- workflow-executor
  - 내부에서 placement/aggregator API 호출
  - Kubernetes Job 생성 및 상태 추적

---

## 7. 현재 문서와의 관계

- 진행/실험 결과: `SELECTIVE_REPLANNING_PROGRESS_2026-04-23.md`
- 연구 방향/메시지: `docs/research/research-topics.md`, `docs/research/paper-strategy.md`
- 본 문서: 코드 구현 기준의 비용모델 생성 방식 + 런타임 동작 메커니즘 통합 설명
