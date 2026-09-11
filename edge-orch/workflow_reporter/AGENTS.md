# Workflow Reporter — Agent Instructions

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 프로젝트는 과거 stage
event reporting 실험인 **Legacy / Reference** Python helper다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python examples/sample_reporter.py
docker build -t workflow-reporter:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_reporter.py
```

## Structure & Style

- `workflow_reporter/client.py` — HTTP event client
- `workflow_reporter/models.py` — typed event payload
- `workflow_reporter/helpers.py` — stage helper API
- `examples/` — historical integration examples

## Boundaries

- ✅ **Always do:** event schema와 retry/fallback 동작을 단위 테스트한다.
- ⚠️ **Ask first:** 현재 서비스나 dashboard가 reporter 이벤트에 의존하게 만든다.
- 🚫 **Never do:** stage event 전송을 현재 workflow 실행 완료 증거로 제시한다.
