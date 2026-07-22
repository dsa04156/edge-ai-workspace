# Docs Consistency Report Generator

이 도구는 현재 operator-facing docs와 state-aggregator 관련 코드가 같은 기준을 설명하는지 정규식/키워드 기반으로 검사하고 단일 HTML 리포트를 생성한다.

## 실행

repo root에서 실행한다.

```bash
python3 tools/docs_consistency/generate_report.py
```

생성 파일:

```text
docs/generated/consistency-report.html
```

`FAIL` 규칙이 있으면 프로세스 exit code는 1이다. `WARN`만 있으면 리포트는 생성되고 exit code는 0이다.

## 검사 대상 문서

- `docs/대시보드-정보-구조.md`
- `docs/옥동-생산성-kpi.md`
- `docs/카젠티-운영-보조-에이전트.md`
- `docs/현재-데모-경로.md`
- `docs/디바이스-서비스-연결.md`
- `docs/물리-디바이스-상태-정책.md`
- `docs/서비스-데모-시나리오.md`
- `docs/ops/현재-데모-운영-절차.md`

`docs/archive`는 기본 검사 대상에 포함하지 않는다.

## 검사 대상 코드

- `edge-orch/state-aggregator/app/service.py`
- `edge-orch/state-aggregator/app/static/dashboard.js`

## 현재 규칙

1. `device_telemetry_ratio`는 telemetry configured ratio여야 한다.
2. telemetry freshness 설명은 `telemetry_freshness_ratio` 또는 `fresh_telemetry_device_count`를 사용해야 한다.
3. DeviceStatus freshness는 현재 physical availability 권위가 아니며 EdgeX 상태/Event와 구분해야 한다.
4. `operator_focus_count`는 degraded/unavailable device 수 + non-healthy node 수이며 workflow risk를 포함하지 않는다.
5. dashboard `node_ready`는 Kubernetes Ready condition과 같은 값이 아니라 state-aggregator의 node_health 기반 판단값이다.
6. Core Data telemetry freshness는 latest Event의 nanosecond `origin`을 sample 시각으로 사용해야 한다.
7. workflow/offloading/placement/agent autonomous control은 현재 구현 기능처럼 표현하지 않는다. 단, read-only/dry-run 설계·시각화 도구는 실제 실행 기능이 아님을 명시하면 허용한다.

## 구현 메모

- 외부 LLM API를 호출하지 않는다.
- Python standard library만 사용한다.
- HTML/CSS는 단일 파일에 포함한다.
- 규칙은 `rules.py`에 모아두고, 리포트 렌더링은 `generate_report.py`가 담당한다.
