# Serial Device Service — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 Go module은 Jetson의 승인된 Serial endpoint를
읽고 Arduino/MPU6050 sample을 기능별 EdgeX Device resource로 fan-out하는 현재 Device
Service다.

## Build & Run

```bash
go mod download
go build ./...
docker build -f Dockerfile -t edgex-device-serial:local ..
```

실제 실행에는 승인된 `/dev/serial/by-id/*` 경로와 EdgeX bootstrap 설정이 필요하다.

## Testing

```bash
go test ./...
go test -race ./...
go test ./internal/driver -run 'TestParseSerialConfig|TestParseLine'
go vet ./...
```

## Structure & Style

- `cmd/device-serial/` — EdgeX SDK bootstrap
- `internal/driver/config.go` — absolute port, baud, parser와 resource validation
- `internal/driver/framer.go`, `parser.go`, `reader.go` — bounded Serial 수집 pipeline
- `internal/driver/local_data_api.go` — 동일 노드 consumer용 recent cache API
- `res/profiles/`, `res/devices/` — 기능별 EdgeX 계약과 fixture

Go 표준 `gofmt`, 명시적 error wrapping과 bounded input validation을 유지한다.

## Boundaries

- ✅ **Always do:** parser, framing, shared reader, cache와 profile resource 계약을 테스트한다.
- ⚠️ **Ask first:** protocol properties, physical source ID, serial path 또는 resource value type을 변경한다.
- 🚫 **Never do:** 임의 host path를 허용하거나 Local Data cache를 durable outbox/Core Data 대체물로 설명한다.
