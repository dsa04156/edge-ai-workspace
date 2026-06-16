# LLM Wiki 운영 규칙

## 목적

`docs/wiki/`는 KubeEdge 기반 혼합 디바이스 엣지 AI PoC 문서를 위한 LLM 유지형 지식 지도다.
기존 `docs/*.md` 원본문서를 대체하지 않고, 여러 문서에 흩어진 판단 기준을 주제별로 압축해 연결한다.

## 계층

| 계층 | 경로 | 소유 | 규칙 |
|---|---|---|---|
| 원본 문서 | `docs/*.md`, `docs/ops/*.md`, 필요한 프로젝트 README | 사람과 구현 작업 | source of truth로 유지한다. |
| Wiki | `docs/wiki/*.md` | LLM이 유지하고 사람이 검토 | 요약, 연결, 충돌 표시, 탐색 지도를 담당한다. |
| 운영 규칙 | `docs/wiki/SCHEMA.md`, 루트 `AGENTS.md` | 사람과 에이전트 | 문서 갱신 방식과 금지 표현을 고정한다. |
| HTML 보기 | `docs/html/` | 생성 산출물 | `python3 scripts/build-docs-html.py`로 재생성한다. 직접 편집하지 않는다. |

## 문서 유형

| 유형 | 파일 | 역할 |
|---|---|---|
| 색인 | `index.md` | wiki와 원본문서의 첫 진입점 |
| 로그 | `log.md` | ingest, query, lint 변경 이력 |
| 합성 문서 | `<topic>.md` | 여러 원본문서를 하나의 주제로 요약 |
| 개념 문서 | `<concept>.md` | 정의, 경계, 관련 문서, 근거 문서 정리 |
| gap 문서 | `<topic>-gaps.md` | 충돌, 누락, 확인 필요 사항 정리 |

## 기본 템플릿

합성 문서와 개념 문서는 필요할 때 아래 구조를 따른다.

```markdown
# 문서 제목

## 한 줄 요약

현재 운영 관점의 의미를 짧게 쓴다.

## 현재 기준

프로젝트가 지금 사실로 취급하는 내용을 쓴다.

## 경계

현재 기능이 아닌 것, legacy로 보아야 할 것, 과장하면 안 되는 것을 쓴다.

## 운영상 의미

운영자, 구현자, 검토자가 이 내용을 어떻게 써야 하는지 쓴다.

## 관련 Wiki

- [관련 문서](related-page.md)

## 근거 문서

- [원본문서](../source.md)
```

## 유지 Workflow

### Ingest

원본문서가 바뀌거나 새 문서가 추가되면 다음 순서로 처리한다.

1. `docs/wiki/index.md`를 먼저 읽는다.
2. 변경된 원본문서를 읽는다.
3. 영향을 받는 wiki 문서를 찾는다.
4. 영향을 받은 wiki 문서만 수정한다.
5. `docs/wiki/index.md`의 링크와 설명을 갱신한다.
6. `docs/wiki/log.md`에 변경 이력을 추가한다.
7. `python3 scripts/build-docs-html.py`로 HTML을 재생성한다.

로그 형식:

```markdown
## [YYYY-MM-DD] ingest | 짧은 제목

- 근거: `docs/path.md`
- 갱신: `docs/wiki/page.md`
- 메모: 변경 의미 한 문장
```

### Query

문서 질문에 답할 때는 다음 순서로 읽는다.

1. `docs/wiki/index.md`
2. 관련 wiki 문서
3. 세부 명령, API, 정책 문구가 필요할 때만 원본문서

질문 답변에서 재사용할 만한 합성이 생기면 wiki에 반영하고 `log.md`에 `query` 항목을 남긴다.

### Lint

주기적으로 다음을 점검한다.

- `index.md`에서 연결되지 않은 고아 문서
- 끊어진 링크
- 중복 요약
- `docs/scope.md`와 충돌하는 주장
- legacy workflow/offloading/agent-assisted planning을 현재 기능처럼 보이게 하는 표현
- 운영 runbook으로 이어지지 않는 운영 설명

수정이 있으면 `log.md`에 `lint` 항목을 남긴다.

## 프로젝트 표현 규칙

유지할 표현:

- 서비스 데모 우선
- 디바이스-서비스 연결 구조
- 통합 운영 가시화
- 실공장 기반 PoC
- 현장 적용성
- 생산성 향상 효과
- 단계적 확장

피할 표현:

- 완전 자율형 오케스트레이션
- LLM이 전체 제어를 수행
- 동적 워크플로우 전체 구현 완료
- runtime replanning 구현 완료
- placement/offloading이 현재 데모 경로인 것처럼 보이는 표현
- agent-assisted planning이 현재 control plane인 것처럼 보이는 표현

`DeviceStatus`와 telemetry 표현은 다음 기준을 지킨다.

- `DeviceStatus`는 저빈도 status/control snapshot이다.
- raw telemetry는 `DeviceStatus`에 올리지 않는다.
- raw telemetry ingestion은 MapperFramework가 아니라 향후 EdgeX data-plane으로 분리한다.
- `status.state=online`만으로 healthy라고 판단하지 않는다.

## 문서 우선순위

문서가 충돌하면 아래 순서로 판단한다.

1. 루트 `AGENTS.md`와 직접 지시
2. `docs/scope.md`
3. `docs/project-context.md`
4. `docs/device-status-policy.md`
5. `docs/dashboard-policy.md`
6. `docs/roadmap.md`
7. 기타 Active 문서
8. Ops 문서
9. Archive 문서는 과거 맥락으로만 사용

Archive나 Legacy 항목을 현재 경로로 승격하려면 먼저 `docs/scope.md`와 `docs/repo-structure.md`를 갱신한다.
