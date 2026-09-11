# Workflow Executor — Agent Instructions

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 프로젝트는 과거 workflow
실행/orchestration 실험인 **Legacy / Reference** 코드다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn workflow_executor.main:app --port 8002
docker build -t workflow-executor:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_service.py
kubectl kustomize k8s >/dev/null
```

## Structure

- `workflow_executor/service.py` — legacy workflow execution service
- `workflow_executor/kube.py` — Kubernetes interaction
- `workflow_executor/storage.py` — legacy execution state
- `k8s/` — historical deployment and RBAC

## Boundaries

- ✅ **Always do:** 변경과 검증 결과를 legacy 실험으로 한정한다.
- ⚠️ **Ask first:** RBAC, workload mutation 또는 현재 대시보드와의 연결을 변경한다.
- 🚫 **Never do:** 이 API를 현재 서비스 설계 dry-run의 실행 backend로 취급한다.
