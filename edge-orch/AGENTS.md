# edge-orch/AGENTS.md

이 디렉터리에서도 루트 작업 규칙을 우선 적용한다.

- 루트 규칙: `../AGENTS.md`
- 현재 개발 체크포인트: `../docs/현재-구현-상태.md`
- 현재 프로젝트 기준: `../docs/프로젝트-배경.md`
- 물리 디바이스 상태 정책: `../docs/물리-디바이스-상태-정책.md`
- 대시보드 판단 정책: `../docs/대시보드-판단-정책.md`
- 후속 로드맵: `../docs/단계별-추진계획.md`

주의:

- 현행 운영 UI는 `state-aggregator`, 승인된 공통 AI 실행·배치·요청 원장은 `runtime-operator`가 담당한다. 상세 범위와 사용자 확정 부하 버튼 소유권은 루트 AGENTS.md를 따른다.
- 과거 `workflow_executor`, `placement_engine`, `workflow_reporter` 중심 문서는 보관 자료로만 본다.
- `runtime-operator`의 등록된 Llama 자동 증강·복귀는 현재 구현이다. 비 Llama `modelRuntime`는 실행 검증과 preferred 정책 단계이며 자동 부하 이동·복귀는 미활성이다. 전체 AI·전체 장비 범용화와 agent-assisted planning은 후속이다.
- `state-aggregator/app/static/` 안의 workflow UI는 EdgeX Core Metadata Device와 Core Data Event freshness를 이용하는 prototype/dry-run 개발도구로만 설명한다. 별도 VirtualDevice registry/API로 설명하지 않고, Kubernetes, EdgeX metadata/state, command, actuator, runtime placement를 실제로 변경하는 현재 운영 기능으로 표현하지 않는다.
