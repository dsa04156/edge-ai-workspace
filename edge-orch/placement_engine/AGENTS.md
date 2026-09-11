# Placement Engine — Agent Instructions

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 프로젝트는 과거
placement/offloading/replanning 실험인 **Legacy / Reference** 코드다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn placement_engine.main:app --port 8001
docker build -t placement-engine:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_engine.py
```

## Structure & Style

- `placement_engine/main.py` — FastAPI entry point
- `placement_engine/engine.py` — placement 판단 로직
- `placement_engine/api_models.py`, `models.py` — Pydantic/API 모델
- `tests/` — API와 engine 단위 테스트

Python 3.11, 타입 힌트, snake_case와 명시적 Pydantic 모델을 유지한다.

## Boundaries

- ✅ **Always do:** 변경을 legacy 실험 범위로 설명하고 단위 테스트를 실행한다.
- ⚠️ **Ask first:** 이 경로를 현재 배포나 대시보드 기능의 입력으로 연결한다.
- 🚫 **Never do:** 동적 offloading이나 replanning을 현재 완료 기능으로 문서화한다.
