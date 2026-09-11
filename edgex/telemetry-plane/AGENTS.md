# EdgeX Telemetry Plane — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 Python package의 중앙 ingest gateway 구현은
보존되지만 edge Agent/outbox/command bridge 실험은 현재 Serial·I2C 운영 데이터 경로가
아니다.

## Build & Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m telemetry_plane.main
docker build -t edgex-telemetry-plane:local .
```

Gateway 실행에는 PostgreSQL, EdgeX Core Data, mTLS와 환경 설정이 필요하다. secret 값은
명령이나 저장소 파일에 넣지 않는다.

## Testing

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_gateway.py
.venv/bin/python -m pytest -q tests/test_outbox.py tests/test_commands.py
```

## Structure & Style

- `src/telemetry_plane/gateway.py` — 중앙 HTTPS ingest와 PostgreSQL inbox
- `edge.py`, `outbox.py`, `mqtt.py` — 퇴역한 edge forwarding 실험
- `commands.py` — 비활성 command bridge 계약
- `metadata_*.py` — historical bootstrap/validation

`from __future__ import annotations`, typed settings, async resource cleanup과 bounded timeout을
유지한다.

## Boundaries

- ✅ **Always do:** replay, auth, cleanup과 failure behavior를 테스트한다.
- ⚠️ **Ask first:** gateway 저장 계약, mTLS, command enablement 또는 운영 manifest 연결을 변경한다.
- 🚫 **Never do:** edge outbox를 현재 Device Service fallback으로 복원하거나 command를 기본 활성화한다.
