# Sense HAT Device Service — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 Go module은 Raspberry Pi의 `/dev/i2c-1`에서
`sensehat-001`을 읽고 기능별 EdgeX Device resource로 fan-out하는 현재 Device Service다.

## Build & Run

```bash
go mod download
go build ./...
docker build -f Dockerfile -t edgex-device-sensehat:local ..
```

실제 실행에는 Sense HAT reader, I2C device와 EdgeX bootstrap 설정이 필요하다.

## Testing

```bash
go test ./...
go test -race ./...
go test ./internal/driver -run TestParseI2CConfig
python3 -m pytest -q reader/test_read_sensehat.py
go vet ./...
```

## Structure & Style

- `cmd/device-sensehat/` — EdgeX SDK bootstrap
- `internal/driver/` — I2C 계약, reader process, sample과 Local Data API
- `reader/read_sensehat.py` — Sense HAT hardware reader
- `res/profiles/`, `res/devices/` — 기능별 EdgeX resource 계약과 fixture

Go는 `gofmt`, typed errors와 context cancellation을 유지한다. Python reader는 JSON stdout
계약을 깨지 않고 진단은 stderr로 보낸다.

## Boundaries

- ✅ **Always do:** bus/device/resource allowlist, process lifecycle, cache와 profile 계약을 테스트한다.
- ⚠️ **Ask first:** I2C bus, physical source ID, resource schema 또는 base image digest를 변경한다.
- 🚫 **Never do:** 물리 source ID를 aggregate EdgeX Device로 만들거나 write command를 활성화한다.
