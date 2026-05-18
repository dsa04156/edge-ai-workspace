# 문서 정리 계획

이 문서는 `docs/goal.md`의 시스템 구축 목표를 기준으로 기존 문서를 정리하기 위한 작업 계획이다.
현재 단계에서는 삭제보다 분류, 노출 순서 조정, 검색 노이즈 축소를 우선한다.

## 정리 원칙

1. 원본 Markdown은 계속 source of truth로 유지한다.
2. HTML은 `scripts/build-docs-html.py`로 재생성되는 보기용 산출물로 둔다.
3. Active 문서는 현재 시스템 구축 목표와 직접 연결되는 문서만 둔다.
4. Ops 문서는 운영 점검, 장애 대응, 데모 실행에 필요한 문서로 둔다.
5. Archive 문서는 과거 연구/논문/legacy orchestration 맥락으로만 둔다.
6. 삭제는 즉시 하지 않고, 중복/검색 제외/통합 후보를 먼저 표시한다.
7. workflow/offloading/agent-assisted planning 계열은 현재 방향으로 보이지 않게 분리한다.

## Active 문서

현재 PoC 목표를 설명하는 중심 문서다.
README와 HTML 홈에서 가장 먼저 보여준다.

| 문서 | 역할 | 조치 |
|---|---|---|
| `goal.md` | 시스템 구축 목표 고정 | 신규 Active |
| `README.md` | 문서 진입점 | 목표 중심으로 재정리 |
| `project-context.md` | 과제 배경과 현재 방향 | 유지 |
| `scope.md` | 포함/제외 범위 | 유지 |
| `service-demo-scenario.md` | 서비스 데모 스토리 | 유지 |
| `current-demo-path.md` | device -> dashboard 흐름 | 유지 |
| `okdong-productivity-kpi.md` | 생산성 KPI 설명 | 유지 |
| `dashboard-information-structure.md` | dashboard 정보 구조 | 유지 |
| `dashboard-policy.md` | 상태 판단 기준 | 유지 |
| `device-status-policy.md` | DeviceStatus/telemetry 분리 | 유지 |
| `device-service-binding.md` | device-service 연결 명세 | 유지 |
| `kagenti-operator-assistant.md` | read-only 운영 보조 agent | 유지 |
| `repo-structure.md` | 구현자용 레포 구조 | 유지 |
| `roadmap.md` | 산출물과 단계 정리 | 유지하되 현재 목표 기준으로 표현 점검 |

## Ops 문서

운영자가 데모 실행, 점검, 장애 대응에 사용하는 문서다.
HTML 홈에서는 Active 다음에 보여준다.

| 문서 | 역할 | 조치 |
|---|---|---|
| `ops/runbook-current-demo.md` | 현재 데모 실행/점검 runbook | 유지, 운영 진입점 |
| `ops/troubleshooting-network.md` | 네트워크/EdgeMesh 문제 대응 | 유지 |
| `ops/edge-node-join-check.md` | edgecore 노드 조인 점검 | 유지 |
| `ops/node-join-check.md` | 일반 노드 조인 점검 | 유지 |
| `ops/pod-connectivity-check.md` | 파드 간 통신 점검 | 유지 |
| `ops/node-spec-template.md` | 노드 실측 사양 기록 | 유지하되 현재 시스템 기준으로 필요한 항목만 남길지 검토 |

## Archive 문서

현재 구축 목표가 아니라 과거 맥락 확인용 문서다.
기본 설명에서는 뒤로 빼고, 필요할 때만 확인한다.

| 문서 | 이유 | 조치 |
|---|---|---|
| `archive/integration/integration-summary.md` | 과거 통합 요약 | Archive 유지 |
| `archive/integration/integration-doc.md` | 과거 통합 문서 | Archive 유지 |
| `archive/integration/integration-detail-log.md` | 1514줄 대형 통합 로그 | 검색 노이즈 후보, 기본 검색 제외 검토 |
| `archive/integration/handoff-legacy.md` | 과거 handoff | Archive 유지 |
| `archive/research/*` | 논문/연구 전략 초안 | Archive 유지 |
| `archive/embedded-conference/*` | selective replanning 관련 과거 실험 | Archive 유지 |
| `archive/legacy-orchestration/*` | legacy orchestration 자료 | Archive 유지 |

## 중복/통합 검토 후보

| 후보 | 이유 | 제안 |
|---|---|---|
| `archive/embedded-conference/cost-model-and-runtime-method.md` | `archive/legacy-orchestration/cost-model-and-runtime-method.md`와 sha256/line count/cmp가 완전히 동일했음 | 본문을 제거하고 canonical 안내 문서로 축소 완료 |
| `archive/legacy-orchestration/cost-model-and-runtime-method.md` | cost model/orchestration 내용의 canonical 위치로 유지 | canonical 본문 유지 |
| `archive/integration/integration-doc.md` / `archive/integration/integration-detail-log.md` | 통합 문서와 상세 로그가 검색 결과를 크게 오염시킬 수 있음 | `integration-detail-log.md`는 기본 검색 제외 처리 완료 |

## 검색 정책 제안

문서 사이트 검색은 기본적으로 Active와 Ops를 우선한다.
Archive는 검색 결과에 나오더라도 뒤로 밀거나, 별도 필터로 접근하게 한다.

권장 필터:

- 전체
- Active
- 운영
- Archive

권장 기본값:

- 문서 홈: Active + 운영 우선
- Archive 포함 여부: 사용자가 직접 선택
- 대형 로그 문서: 기본 검색 제외 후보

## HTML 홈 개편 방향

현재 홈은 전체 문서 목록을 보여준다.
앞으로는 다음 순서로 보이게 한다.

1. 시스템 구축 목표
2. 처음 읽을 문서
3. 데모 실행/운영 문서
4. 아키텍처/정책 문서
5. 운영 보조 agent 문서
6. Archive
7. 정리/검토 후보

## 실제 파일 이동은 아직 보류

현재 단계에서는 파일 이동/삭제를 하지 않는다.
먼저 README와 HTML 홈에서 노출 구조를 정리한 뒤, 중복 여부가 확실한 문서만 별도 승인 후 삭제/통합한다.

## 다음 작업 후보

1. `README.md`를 `goal.md` 중심으로 재정리한다.
2. `scripts/build-docs-html.py`의 Active 문서 순서에 `goal.md`와 이 문서를 추가한다.
3. HTML 홈에서 Archive 섹션을 뒤로 빼고 설명 문구를 강화한다.
4. 검색 필터를 추가해 Active/Ops/Archive를 분리한다.
5. 중복 cost model 문서는 `archive/legacy-orchestration/cost-model-and-runtime-method.md`를 canonical로 유지하고, embedded-conference 쪽 문서는 안내 문서로 축소했다.
6. `integration-detail-log.md`는 기본 검색에서 제외했다.
