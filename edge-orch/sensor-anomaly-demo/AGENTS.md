# Sensor Anomaly Demo — Agent Instructions

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 프로젝트는 실제 Local
Data 입력, 정렬, 통계 기준선 추론, 파생 결과 저장을 검증하는 현재 고정 서비스 데모다.
옥동 실장비 AI 모델이거나 범용 동적 offloading 구현은 아니다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8080
docker build -t sensor-anomaly-demo:local .
```

Replay 절차는 `README.md`의 simulator와 `app.replay:create_app_from_env` 명령을 따른다.

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_runtime.py
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_server1_observed_only.py tests/test_server1_approved_offload.py
```

## Structure & Style

- `app/contracts.py`, `alignment.py`, `features.py` — 입력 계약과 feature pipeline
- `app/model_adapter.py`, `detector.py`, `cuda_runtime.py` — 명시적 backend/version 추론
- `app/runtime.py`, `remote_inference.py` — 로컬 실행과 승인된 원격 후보 경계
- `app/storage.py` — application-owned SQLite 결과와 알림
- `k8s/` — 기본 로컬 실행, `k8s/server1-observed-only/` — 요청 전환 없는 GPU 후보

타입 힌트와 Pydantic 모델을 유지하고 외부 I/O는 timeout과 명시적 오류 상태를 갖게 한다.

## Boundaries

- ✅ **Always do:** 입력 schema, model version, routing mode와 결과 저장 경계를 테스트한다.
- ⚠️ **Ask first:** model backend, 승인 overlay, threshold 또는 remote routing을 변경한다.
- 🚫 **Never do:** SQLite를 raw EdgeX telemetry 권위로 쓰거나 observed-only 후보를 활성 offload로 설명한다.
