# Workspace Tests — Agent Instructions

루트 `AGENTS.md`를 먼저 적용한다. 이 디렉터리는 저장소 전체의 문서, 배포 계약,
대시보드와 운영 스크립트 회귀 테스트를 담는다.

## Test

저장소 루트에서 실행한다.

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q tests/test_docs_consistency.py
.venv/bin/python -m pytest -q tests/test_docs_consistency.py::CurrentDeviceManagementScopeTest::test_current_docs_define_bounded_edgex_device_management_scope
```

테스트 이름이 실제 정책 문구나 manifest 계약을 설명하도록 유지한다. 파일 시스템 검사는
`Path(__file__).resolve().parents[1]`로 저장소 루트를 구하고, YAML은 가능한 경우 구조로
파싱한 뒤 비교한다.

## Structure

- `test_docs_*.py` — 문서 공개 목록, 링크, 생성 HTML과 검색 계약
- `test_dashboard_*.py` — 정적 대시보드 구조와 사용자 흐름 회귀
- `test_*_k8s.py`, `test_*_deploy.py` — Kustomize와 GitOps 배포 계약
- `test_*_experiment.py` — 자원 증강 및 대표 AI 실험 도구 계약
- `test_verify_*.py` — 운영 검증 스크립트의 현재 경로와 판정 기준

## Boundaries

- ✅ **Always do:** 정책 변경에는 실패하는 회귀 테스트를 함께 추가하고 단일 테스트와 전체 `tests`를 실행한다.
- ⚠️ **Ask first:** live cluster, 외부 registry 또는 실제 장비를 필수 전제로 만드는 테스트를 추가한다.
- 🚫 **Never do:** 테스트를 통과시키기 위해 현재/legacy 경계를 완화하거나 생성물만 직접 수정한다.
