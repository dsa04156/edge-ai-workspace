# Vision Stage Runner — Agent Instructions

상위 `../AGENTS.md`와 루트 `../../AGENTS.md`를 먼저 적용한다. 이 디렉터리는 독립 FastAPI
vision stage 실험 서비스다. 현재 운영 경로로 승격됐다는 근거 없이 현행 옥동 서비스로
설명하지 않는다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn vision_stage_runner.service:app --port 8080
docker build -t vision-stage-runner:local .
```

## Testing

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_service.py
kubectl kustomize k8s >/dev/null
```

## Structure & Style

- `vision_stage_runner/service.py` — FastAPI service
- `vision_stage_runner/main.py` — 실행 진입점
- `tests/` — service와 entry-point 회귀
- `k8s/` — 독립 배포 manifest

## Boundaries

- ✅ **Always do:** HTTP 계약과 manifest를 함께 검증한다.
- ⚠️ **Ask first:** root Kustomize, 서비스 catalog 또는 운영 dashboard에 연결한다.
- 🚫 **Never do:** 실험 runner를 검증된 생산품질 판별 서비스로 표현한다.
