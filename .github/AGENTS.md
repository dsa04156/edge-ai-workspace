# GitHub Automation — Agent Instructions

루트 `AGENTS.md`를 먼저 적용한다. 이 디렉터리는 self-hosted runner용 이미지 빌드,
digest 해석과 Argo CD 배포 자동화를 소유한다.

## Validate

저장소 루트에서 실행한다.

```bash
.venv/bin/python -m pytest -q tests/test_state_aggregator_argocd_deploy.py
.venv/bin/python -m pytest -q tests/test_state_aggregator_device_management_deployment.py
git diff --check -- .github
```

## Structure

- `workflows/docker-build-push.yml` — 변경 경로별 multi-arch 이미지 빌드와 GitOps 배포
- `buildkitd.toml` — 테스트베드 내부 registry를 위한 BuildKit 설정

## Conventions

- shell step은 `set -euo pipefail`을 사용하고 digest가 비어 있지 않은지 검증한다.
- 신규 빌드 대상은 push path filter, change output, build, digest와 배포 순서를 함께 갱신한다.
- 현행 이미지는 immutable digest로 전달하고 직접 `kubectl set image` 하지 않는다.

## Boundaries

- ✅ **Always do:** workflow 변경 후 관련 계약 테스트와 YAML 표현을 검증한다.
- ⚠️ **Ask first:** runner label, registry, branch trigger, Argo CD target revision 또는 배포 순서를 변경한다.
- 🚫 **Never do:** secret 값을 workflow에 기록하거나 live 리소스를 GitOps 밖에서 지속 변경한다.
