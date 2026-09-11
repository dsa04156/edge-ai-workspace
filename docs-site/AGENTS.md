# Documentation Image — Agent Instructions

루트 `AGENTS.md`를 먼저 적용한다. 이 디렉터리는 `docs/html/`과 `docs/assets/`를 nginx
이미지로 포장하고 `docs-html` 배포 manifest를 제공한다. 문서 원본은 `docs/`에서 관리한다.

## Build & Validate

이 디렉터리에서 실행한다.

```bash
docker build -f Dockerfile -t docs-html:local ..
kubectl kustomize . >/dev/null
../.venv/bin/python -m pytest -q ../tests/test_docs_html_search.py ../tests/test_docs_consistency.py
```

Registry push가 필요한 운영 빌드는 고유 tag를 정한 뒤에만 실행한다.

```bash
scripts/build-amd64-oci.sh 192.168.0.56:5000/docs-html:20260820-local
```

## Structure

- `Dockerfile` — 저장소 루트를 build context로 쓰는 nginx 이미지
- `scripts/build-amd64-oci.sh` — 고정 base digest와 검증된 `crane`으로 amd64 OCI 이미지 생성
- `kustomization.yaml`, `k8s.yaml` — `docs-html` Kubernetes 배포

## Boundaries

- ✅ **Always do:** `docs/html/`은 생성기로 갱신하고 이미지와 Kustomize render를 검증한다.
- ⚠️ **Ask first:** base image digest, registry 대상, public route 또는 deployment 소유권을 변경한다.
- 🚫 **Never do:** `docs/html/` 생성물을 문서 원본처럼 직접 편집하거나 unique tag 없이 registry에 push한다.
