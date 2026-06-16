# Wiki 변경 로그

이 파일은 append-only로 유지한다.
ingest, query, lint 과정에서 wiki가 어떻게 바뀌었는지 기록한다.

## [2026-06-16] ingest | LLM wiki 계층 추가

- 근거: `docs/goal.md`, `docs/project-context.md`, `docs/scope.md`, `docs/current-demo-path.md`, `docs/device-service-binding.md`, `docs/dashboard-information-structure.md`, `docs/device-status-policy.md`, `docs/roadmap.md`
- 갱신: `docs/wiki/SCHEMA.md`, `docs/wiki/index.md`, `docs/wiki/operating-model.md`, `docs/wiki/current-demo-flow.md`, `docs/wiki/status-and-telemetry.md`, `docs/wiki/dashboard-and-kpi.md`, `docs/wiki/operations-entry-points.md`, `docs/wiki/second-year-design-track.md`
- 메모: Active/Ops 원본문서를 유지하면서 Karpathy식 Markdown wiki 계층을 추가했다.

## [2026-06-16] lint | 한국어 중심 문서 정리

- 근거: `docs/README.md`, `docs/docs-cleanup-plan.md`, `docs/wiki/SCHEMA.md`
- 갱신: `docs/wiki/*.md`
- 메모: wiki 제목과 본문을 한국어 중심으로 정리하고, 원본문서와 wiki의 역할 경계를 더 명확히 했다.
