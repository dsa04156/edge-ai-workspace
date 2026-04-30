# Docs Index

이 디렉터리가 현재 기준 문서의 진입점이다.
`edge-orch/docs`에 있던 문서는 루트 `docs/`로 이동했고, 오래된 실험/논문/통합 기록은 `docs/archive/`에 보관한다.

## Active Guides

- `project-context.md`: 과제 배경, 현재 목표, 테스트베드, 디바이스 등록/토픽 규칙
- `device-status-policy.md`: DeviceStatus와 raw telemetry 분리 정책
- `dashboard-policy.md`: 대시보드 상태 판단 기준
- `roadmap.md`: 동적 오프로딩, agent-assisted planning 후속 계획

## Operations

- `ops/node-join-check.md`: 워커 노드 조인 후 점검
- `ops/edge-node-join-check.md`: KubeEdge edge node 조인 점검
- `ops/pod-connectivity-check.md`: pod 연결성 점검
- `ops/troubleshooting-network.md`: 네트워크/EdgeMesh 복구 기록
- `ops/node-spec-template.md`: 노드 실측 사양표 템플릿

## Research

- `research/paper-strategy.md`
- `research/venue-strategy.md`
- `research/evaluation-plan.md`
- `research/writing-checklist.md`
- `research/research-topics.md`

## Archive

- `archive/integration/`: 기존 통합문서와 상세 작업 로그
- `archive/legacy-orchestration/`: 이전 동적 워크플로우/비용 모델 문서
- `archive/embedded-conference/`: 임베디드공학회 실험/원고 관련 보관 자료

새 작업 판단은 Active Guides를 우선 기준으로 삼고, Archive 문서는 과거 맥락 확인용으로만 사용한다.
