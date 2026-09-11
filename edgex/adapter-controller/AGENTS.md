# EdgeX Adapter Controller — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 서비스는 승인된 Adapter Runtime, passive
discovery 후보, SQLite 상태 이력과 EdgeX 등록 Saga를 관리한다. 최종 Device/Profile/Event
권위는 EdgeX다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8080
docker build -t edge-adapter-controller:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_registration.py tests/test_reconciler.py
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_serial_discovery_integration.py
```

## Structure & Style

- `app/catalog.py`, `device_catalog.py` — versioned allowlist와 exact binding
- `app/discovery*.py` — candidate projection, 상태와 SQLite store
- `app/registration.py`, `edgex.py` — 등록/rollback/first Event Saga
- `app/reconciler.py`, `kube.py` — Controller 소유 runtime에 제한된 mutation
- `config/` — 검토된 runtime, device binding과 profile 계약

Pydantic 모델, 타입 힌트, bounded 입력과 명시적 idempotency/error 상태를 유지한다.

## Boundaries

- ✅ **Always do:** catalog allowlist, 인증, rollback과 first Event 판정을 테스트한다.
- ⚠️ **Ask first:** catalog schema, RBAC, 등록 Saga 또는 SQLite migration을 변경한다.
- 🚫 **Never do:** 임의 image/hostPath/command를 허용하거나 accepted candidate를 자동 등록으로 해석한다.
