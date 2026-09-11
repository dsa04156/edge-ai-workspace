# Edge Device Discovery Agent — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 agent는 Controller의 plan에 따라 USB Serial과
허용된 I2C identity를 수동 관측하고 서명된 후보 보고서를 보낸다. 후보는 EdgeX Device나
통신 성공 증거가 아니다.

## Build & Run

```bash
PYTHONPATH=. python3 -m app.main
docker build -t edge-device-discovery:local .
```

실행에는 `NODE_NAME`, Controller URL과 HMAC key 등 배포 환경이 필요하다. 실제 secret은
명령이나 문서에 기록하지 않는다.

## Testing

```bash
PYTHONPATH=. python3 -m pytest -q
PYTHONPATH=. python3 -m pytest -q tests/test_serial_plugin.py tests/test_i2c_plugin.py
PYTHONPATH=. python3 -m pytest -q tests/test_plugin_contracts.py
```

## Structure & Style

- `app/scanner.py`, `plugins.py` — plan 기반 passive scan 조합
- `app/serial_plugin.py`, `i2c_plugin.py` — protocol별 read-only 관측
- `app/reporter.py` — plan fetch와 HMAC 서명 보고
- `app/health.py` — bounded readiness 상태
- `simulators/` — 개발 전용 입력

## Boundaries

- ✅ **Always do:** scan 범위, timeout, allowlist와 보고서 서명을 테스트한다.
- ⚠️ **Ask first:** protocol, bus/address, host mount 또는 scan capability를 넓힌다.
- 🚫 **Never do:** 광역 network probe, write command, 자동 등록 또는 임의 hostPath 실행을 추가한다.
