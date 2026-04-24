# Selective Replanning Progress

## 목적

현재 mixed-device KubeEdge 환경에서 `stage-level selective replanning` 연구 방향으로 전환하기 위한 구현 진행 상황을 기록한다.

이 문서는 다음을 남긴다.

- 현재까지 반영한 핵심 코드 변경
- 아직 클러스터에 반영되지 않은 부분
- 새 실험을 시작하기 전에 필요한 배포 단계
- 이번 턴에서 실제로 수행하는 배포 및 실험 시작 작업

---

## 현재 구현 상태

### 1. Placement Engine

기존 proxy weighted score를 확장해 hybrid cost model과 selective policy를 반영했다.

핵심 변경:

- empirical stats + fallback heuristic 혼합
- `expected_keep_cost_ms`
- `expected_target_cost_ms`
- `net_gain_ms`
- `decision_margin_ms`
- `selected_policy`
- fallback 여부(`used_exec_fallback`, `used_migration_fallback`)

선택 규칙:

- gain이 margin보다 작으면 `keep`
- gain이 margin보다 크면 `migrate` 또는 `offload_to_cloud`
- instability가 높으면 추가 penalty와 margin 증가

관련 파일:

- [engine.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/engine.py)
- [models.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/models.py)
- [service.py](/home/etri/jinuk/edge-orch/placement_engine/placement_engine/service.py)

### 2. State Aggregator

state-aggregator를 empirical cost read model로 확장했다.

추가 내용:

- `StageObservation`
- `MigrationObservation`
- `StageCostStats`
- `MigrationCostStats`
- append-only JSONL persistence
- startup 시 observation reload
- `GET /state/cost-model` API

관련 파일:

- [models.py](/home/etri/jinuk/edge-orch/state-aggregator/app/models.py)
- [storage.py](/home/etri/jinuk/edge-orch/state-aggregator/app/storage.py)
- [main.py](/home/etri/jinuk/edge-orch/state-aggregator/app/main.py)
- [service.py](/home/etri/jinuk/edge-orch/state-aggregator/app/service.py)

### 3. Workflow Executor

executor가 empirical reconstruction에 필요한 이벤트를 추가로 보내도록 확장했다.

추가 이벤트/필드:

- `stage_job_created`
- `action_type`
- `score_breakdown`
- enriched `migration_event`
- enriched `stage_start`
- enriched `stage_end`

관련 파일:

- [models.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/models.py)
- [service.py](/home/etri/jinuk/edge-orch/workflow_executor/workflow_executor/service.py)

### 4. Experiment Harness

기존 실험 스크립트를 5-method 연구형 harness로 확장했다.

추가 method:

- `always-offload`
- `threshold`
- `selective`
- `runtime`

유지 method:

- `static`

현재 스크립트는 다음을 지원한다.

- 4 scenarios
- 5 methods
- migration count
- unnecessary migration count
- net gain
- keep/migrate distribution

관련 파일:

- [run_minimal_latency_experiment.py](/home/etri/jinuk/edge-orch/experiments/run_minimal_latency_experiment.py)

---

## 테스트 상태

로컬 가상환경에서 아래 테스트를 수행했고 통과했다.

```bash
PYTHONPATH=edge-orch/state-aggregator:edge-orch/placement_engine:edge-orch/workflow_executor \
/tmp/edge-orch-test-venv/bin/python -m pytest --import-mode=importlib \
edge-orch/placement_engine/tests/test_engine.py \
edge-orch/placement_engine/tests/test_api.py \
edge-orch/state-aggregator/tests/test_api.py \
edge-orch/state-aggregator/tests/test_normalizer.py \
edge-orch/state-aggregator/tests/test_storage.py \
edge-orch/workflow_executor/tests/test_service.py
```

결과:

- `22 passed`

---

## 현재 남은 상태

코드는 반영됐지만, 클러스터에는 아직 기존 이미지가 떠 있다.

현재 배포 이미지:

- `placement-engine@sha256:7ffa32...`
- `state-aggregator@sha256:f11a5a...`
- `workflow-executor@sha256:4b9c73...`

이 상태에서는 새 실험 harness가 `GET /state/cost-model` 호출 시 `404`를 받는다.

즉, 다음 단계가 필요하다.

1. 새 이미지 빌드
2. registry push
3. deployment restart
4. rollout 확인
5. 실험 시작

---

## 이번 턴에서 수행할 작업

이번 턴에서는 아래를 실제로 수행한다.

1. 새 이미지 빌드 및 push
2. `state-aggregator`, `placement-engine`, `workflow-executor` 재배포
3. `/state/cost-model` 동작 확인
4. `selective replanning` 기준 extended experiment 시작

---

## 주의

이번 단계의 실험은 기존 2-baseline 실험과 다르다.

새 실험의 method는 다음 5개다.

- `static`
- `always-offload`
- `threshold`
- `selective`
- `runtime`

따라서 이후 나오는 결과는 기존 runtime-only 비교 결과와 직접 혼용하지 않는다.

---

## 실험 결과 분석 (2026-04-24)

### 실험 범위

- method 5개 x scenario 4개 = 총 20개 결과 파일
- 각 조합 `--workflows 5`
- 결과 경로: `edge-orch/experiments/results/20260424T*/*.json`

### 시나리오별 E2E 평균 지연(ms)

| scenario | 1위 | 2위 | 3위 | 4위 | 5위 |
|---|---:|---:|---:|---:|---:|
| normal | always-offload 12220.4 | runtime 12234.6 | selective 12422.4 | threshold 14223.4 | static 14424.6 |
| mild-burst | runtime 11824.2 | always-offload 12817.6 | static 13595.6 | threshold 14230.4 | selective 14429.0 |
| heavy-burst | threshold 12018.4 | runtime 12446.8 | selective 13050.8 | always-offload 13205.6 | static 13765.6 |
| sustained-overload | runtime 12039.4 | always-offload 12606.0 | threshold 12644.6 | selective 13232.6 | static 13800.4 |

### method 전체 평균 E2E(ms)

| method | overall avg e2e |
|---|---:|
| runtime | 12136.2 |
| always-offload | 12712.4 |
| threshold | 13279.2 |
| selective | 13283.7 |
| static | 13896.5 |

### 시나리오별 처리량(throughput, jobs/s)

| scenario | 1위 | 2위 | 3위 | 4위 | 5위 |
|---|---:|---:|---:|---:|---:|
| normal | always-offload 0.081237 | runtime 0.081153 | selective 0.079858 | threshold 0.069890 | static 0.068871 |
| mild-burst | runtime 0.069005 | always-offload 0.064593 | static 0.061548 | threshold 0.059117 | selective 0.058403 |
| heavy-burst | threshold 0.068063 | runtime 0.066110 | selective 0.063566 | always-offload 0.062983 | static 0.060915 |
| sustained-overload | runtime 0.082428 | always-offload 0.078754 | threshold 0.078555 | selective 0.075054 | static 0.071981 |

### method 전체 평균 처리량(jobs/s)

| method | overall avg throughput |
|---|---:|
| runtime | 0.074674 |
| always-offload | 0.071892 |
| selective | 0.069220 |
| threshold | 0.068906 |
| static | 0.065829 |

### 전체 요약값 표(현재 결과 20건)

| scenario | method | workflow_count | capture_mean_ms | preprocess_mean_ms | inference_mean_ms | e2e_mean_ms | preprocess_p95_ms | e2e_p95_ms | throughput_jobs_per_s | migration_time_mean_ms | migration_count | keep_count | unnecessary_migration_count | net_gain_mean_ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| normal | static | 5 | 5134.400 | 5138.400 | 3923.800 | 14424.600 | 5142 | 14643 | 0.068871 | 0.000000 | 0 | 5 | 0 | null |
| normal | always-offload | 5 | 4115.800 | 3918.200 | 3924.200 | 12220.400 | 4125 | 12617 | 0.081237 | 0.000000 | 5 | 0 | 5 | null |
| normal | threshold | 5 | 4721.200 | 5325.600 | 3920.600 | 14223.400 | 5143 | 14610 | 0.069890 | 0.000000 | 0 | 5 | 0 | null |
| normal | selective | 5 | 4316.600 | 4115.800 | 3705.200 | 12422.400 | 4124 | 12620 | 0.079858 | 136.600 | 5 | 0 | 5 | 1131.345 |
| normal | runtime | 5 | 4319.000 | 3717.400 | 3934.200 | 12234.600 | 4126 | 12635 | 0.081153 | 118.800 | 5 | 0 | 5 | 2068.148 |
| mild-burst | static | 5 | 4318.000 | 5124.200 | 3916.200 | 13595.600 | 5129 | 13589 | 0.061548 | 0.000000 | 0 | 5 | 0 | null |
| mild-burst | always-offload | 5 | 4521.000 | 4117.800 | 3912.600 | 12817.600 | 4122 | 13643 | 0.064593 | 0.000000 | 5 | 0 | 5 | null |
| mild-burst | threshold | 5 | 4721.400 | 5132.000 | 4103.800 | 14230.400 | 5140 | 14618 | 0.059117 | 0.000000 | 0 | 5 | 0 | null |
| mild-burst | selective | 5 | 4526.800 | 5523.000 | 4121.800 | 14429.000 | 6121 | 14602 | 0.058403 | 148.000 | 2 | 3 | 2 | 980.193 |
| mild-burst | runtime | 5 | 3909.400 | 4118.800 | 3518.400 | 11824.200 | 4127 | 11648 | 0.069005 | 117.200 | 5 | 0 | 5 | 1567.201 |
| heavy-burst | static | 5 | 4521.200 | 5117.000 | 3909.400 | 13765.600 | 5130 | 14554 | 0.060915 | 0.000000 | 0 | 5 | 0 | null |
| heavy-burst | always-offload | 5 | 4923.800 | 3909.000 | 4125.400 | 13205.600 | 4111 | 13617 | 0.062983 | 0.000000 | 5 | 0 | 0 | null |
| heavy-burst | threshold | 5 | 4119.200 | 3916.200 | 3718.000 | 12018.400 | 4119 | 12624 | 0.068063 | 0.000000 | 5 | 0 | 0 | null |
| heavy-burst | selective | 5 | 4926.600 | 3919.400 | 3924.600 | 13050.800 | 4128 | 13659 | 0.063566 | 126.200 | 5 | 0 | 0 | 1978.546 |
| heavy-burst | runtime | 5 | 3917.800 | 3928.400 | 4317.600 | 12446.800 | 4146 | 12663 | 0.066110 | 118.000 | 5 | 0 | 0 | 1975.930 |
| sustained-overload | static | 5 | 4320.800 | 5543.800 | 3712.600 | 13800.400 | 6135 | 13619 | 0.071981 | 0.000000 | 0 | 5 | 0 | null |
| sustained-overload | always-offload | 5 | 4310.800 | 3916.000 | 4115.200 | 12606.000 | 4130 | 12639 | 0.078754 | 0.000000 | 5 | 0 | 0 | null |
| sustained-overload | threshold | 5 | 4322.600 | 3922.000 | 4117.000 | 12644.600 | 4133 | 12659 | 0.078555 | 0.000000 | 5 | 0 | 0 | null |
| sustained-overload | selective | 5 | 5124.200 | 4121.600 | 3714.600 | 13232.600 | 4126 | 13614 | 0.075054 | 116.600 | 5 | 0 | 0 | 2074.373 |
| sustained-overload | runtime | 5 | 4315.800 | 3720.600 | 3714.800 | 12039.400 | 4118 | 12646 | 0.082428 | 132.400 | 5 | 0 | 0 | 2212.098 |

### 관찰 포인트

1. **전체 1위는 runtime**
	- method 전체 평균 E2E: runtime 12136.2ms, static 13896.5ms
	- 차이: 1760.3ms
	- method 전체 평균 처리량: runtime 0.074674, static 0.065829
2. **고부하에서는 오프로딩 계열 우위가 명확**
	- heavy-burst: threshold 12018.4ms, static 13765.6ms
	- sustained-overload: runtime 12039.4ms, static 13800.4ms
3. **normal/mild-burst 구간은 과도 오프로딩 신호 존재**
	- normal: runtime/always-offload 모두 unnecessary_migration_count=5
	- mild-burst: runtime/always-offload 모두 unnecessary_migration_count=5
4. **threshold는 high pressure 구간에서 강점**
	- heavy-burst 1위(12018.4ms)
5. **selective는 현재 파라미터에서 불안정**
	- mild-burst 최하위(14429.0ms)
	- normal: runtime 12234.6ms 대비 selective 12422.4ms

### 해석

- 본 섹션의 결론은 `2026-04-24` 결과 20건(method 5개 x scenario 4개, 각 5 workflows)에만 기반한다.
- 시나리오별 1위 method는 `normal=always-offload`, `mild-burst=runtime`, `heavy-burst=threshold`, `sustained-overload=runtime`이다.
- 전체 평균 E2E는 `runtime < always-offload < threshold ~= selective < static` 순서다.

### 운영 권고

1. 현재 결과 요약본에는 관측값(E2E mean/P95, migration, unnecessary migration)만 인용한다.
2. 정책 우열의 일반화 결론은 추가 반복 실험(workflows 확대) 이후 별도 섹션에서 분리해 기술한다.
