# edge-orch/AGENTS.md

이 디렉터리에서도 루트 작업 규칙을 우선 적용한다.

- 루트 규칙: `../AGENTS.md`
- 현재 프로젝트 기준: `../docs/프로젝트-배경.md`
- 물리 디바이스 상태 정책: `../docs/물리-디바이스-상태-정책.md`
- 대시보드 판단 정책: `../docs/대시보드-판단-정책.md`
- 후속 로드맵: `../docs/단계별-추진계획.md`

주의:

- 현행 데모 운영 경로는 `state-aggregator` 중심이다.
- 과거 `workflow_executor`, `placement_engine`, `workflow_reporter` 중심 문서는 보관 자료로만 본다.
- 동적 오프로딩과 agent-assisted planning은 현재 완성 기능이 아니라 후속 확장 방향이다.
- `state-aggregator/app/static/` 안의 workflow UI는 EdgeX Core Metadata Device와 Core Data Event freshness를 이용하는 prototype/dry-run 개발도구로만 설명한다. 별도 VirtualDevice registry/API로 설명하지 않고, Kubernetes, EdgeX metadata/state, command, actuator, runtime placement를 실제로 변경하는 현재 운영 기능으로 표현하지 않는다.
