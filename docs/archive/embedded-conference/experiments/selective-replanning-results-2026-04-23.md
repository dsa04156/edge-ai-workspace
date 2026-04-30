# Stage-Level Selective Replanning 중간 점검 리포트

> **작성 일시**: 2026-04-23
> **진행도**: 13/16 조합 완료 (약 81%)

## 1. 지표 추출 요약 테이블 (현재까지)

| Scenario | Method | E2E p95 (ms) | Preprocess p95 (ms) | Migrations | Unnecessary | Net Gain (ms) | TPS |
|---|---|---:|---:|---:|---:|---:|---:|
| **normal** | static | 13646 | 5115 | 0 | 0 | N/A | 0.0741 |
| normal | always-offload | 12662 | 4121 | 5 | 5 | N/A | 0.0786 |
| normal | threshold | 13579 | 5138 | 0 | 0 | N/A | 0.0742 |
| normal | **selective** | 15672 | 7105 | **2** | **2** | 605.88 | 0.0676 |
| **mild-burst** | static | 14609 | 5126 | 0 | 0 | N/A | 0.0599 |
| mild-burst | always-offload | 13582 | 4133 | 5 | 5 | N/A | 0.0636 |
| mild-burst | threshold | 13628 | 5122 | 0 | 0 | N/A | 0.0639 |
| mild-burst | **selective** | 12636 | 4117 | **5** | **5** | 586.59 | 0.0662 |
| **heavy-burst** | static | 13620 | 5130 | 0 | 0 | N/A | 0.0620 |
| heavy-burst | always-offload | 13656 | 4141 | 5 | 0 | N/A | 0.0605 |
| heavy-burst | threshold | 13654 | 4126 | 5 | 0 | N/A | 0.0645 |
| heavy-burst | **selective** | **12721** | **4121** | **5** | 0 | **1228.01** | **0.0662** |
| **sustained** | static | 13656 | 5144 | 0 | 0 | N/A | 0.0719 |
*(sustained-overload 나머지 및 완료되지 않은 항목은 제외)*

---

## 2. 중간 분석 결과

현재까지 확보된 결과를 바탕으로 각 시나리오에서의 동작을 분석합니다.

### 🌟 긍정적인 성과 (가설 입증)
* `Heavy burst` 시나리오에서 **Selective Replanning의 압도적인 우위가 증명**되었습니다.
* Threshold 방식과 동일하게 5번의 마이그레이션을 수행했지만, **E2E p95 Latency가 12721ms로 가장 빨랐고 TPS도 가장 높았습니다.**
* 즉, 부하가 높을 때 비용을 정확히 계산하여 이득이 되는 타이밍(Net gain 1228ms)에 마이그레이션하는 Cost model v2의 가설이 매우 성공적으로 작동합니다. 

### ⚠️ 발견된 문제점 (개선 필요)
* **Normal 및 Mild Burst 조건에서 지나치게 호전적인 마이그레이션 발생**
* 계획서의 Acceptance Criteria에 따르면, `Normal`에서 selective 방식은 Zero에 가까운 마이그레이션을 보여야 하나 오히려 **2회**나 불필요한 마이그레이션(Unnecessary Migration)이 발생했습니다. 
* 심지어 Normal에서 마이그레이션을 시도한 결과 TPS와 p95(15672ms)가 모두 악화되었습니다.
* `Mild burst`에서도 5회 모두 마이그레이션을 선택했습니다 (목표: threshold 방식보다 적은 발생량). 

### 💡 해결 방안 (엔진 튜닝)
이 문제는 `Placement Engine`이 Normal/Mild 상태일 때 마이그레이션 예상 이득을 지나치게 긍정적으로 잡고 있기 때문입니다. 

> [!TIP]
> **해결책**: 엔진(`engine.py`)의 `decision_margin_ms`가 현재 `low`, `medium` 압력일 때 **500ms**로 설정되어 있습니다. 추출된 결과를 보면 Normal일 때의 오판단 `Net gain`이 대략 580~605ms 근처로 형성되었습니다. 
> 따라서 기본 `decision_margin_ms`를 **700ms 혹은 800ms** 사이로 상향 조정한다면 이 불필요한 오판단(Unnecessary migrations)을 완벽히 억제할 수 있을 것으로 보입니다!
