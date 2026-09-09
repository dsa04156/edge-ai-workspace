# State Aggregator — Agent Instructions

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 프로젝트는 EdgeX,
Kubernetes/KubeEdge와 Prometheus의 서로 다른 권위 신호를 결합하는 read model과 운영
대시보드다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000
docker build -t state-aggregator:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
node --test tests/*.js
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_api.py
node --test tests/test_service_designer.js
kubectl kustomize k8s >/dev/null
```

## Structure & Style

- `app/edgex.py`, `kube.py`, `prometheus.py` — 권위별 외부 reader
- `app/service.py`, `normalizer.py`, `models.py` — 상태 계산과 typed read model
- `app/device_management*.py` — 승인된 등록 경로; Kubernetes 쓰기는 Adapter Controller가 소유
- `app/static/` — vanilla JS/CSS 운영 UI와 브라우저 내부 서비스 설계 dry-run
- `app/config/*.json` — Git 기반 service/adapter/instance 계약

Python은 타입 힌트와 명시적 오류 reason을 유지한다. JavaScript는 DOM selector와 exported
test seam을 기존 테스트와 함께 변경한다.

## Boundaries

- ✅ **Always do:** EdgeX Device/Event, node/workload, 서비스 결과의 출처와 실패 상태를 분리한다.
- ⚠️ **Ask first:** 상태 판정, management API, catalog schema 또는 dashboard 정보 구조를 변경한다.
- 🚫 **Never do:** 서비스 설계 화면에서 Kubernetes/EdgeX mutation, command, migration이나 offloading을 실행한다.
