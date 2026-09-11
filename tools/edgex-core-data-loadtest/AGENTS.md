# EdgeX Core Data Load Test — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 dependency-free Go CLI는 전용 synthetic Device
identity로 EdgeX Core Data event 부하, readback, threshold와 cleanup을 검증한다.

## Build & Run

```bash
go build -o /tmp/edgex-core-data-loadtest .
/tmp/edgex-core-data-loadtest -help
```

실제 endpoint 대상 실행은 Event 생성·검증·삭제를 수행하므로 대상 URL과 run ID를 확인한
후에만 한다.

## Testing

```bash
go test ./...
go test ./... -run 'TestHTTPClient|TestBuildEvent|TestRun'
go test -race ./...
go vet ./...
```

## Structure & Style

- `main.go` — CLI config, validation, JSON report와 exit code
- `loadtest.go` — load scheduling, threshold와 aggregate report
- `http_client.go` — Core Data Event write/read/delete
- `loadtest_test.go` — deterministic fake client와 threshold tests

표준 library, `context` cancellation, deterministic run IDs와 machine-readable JSON을 유지한다.

## Boundaries

- ✅ **Always do:** destructive cleanup scope와 threshold exit code를 단위 테스트한다.
- ⚠️ **Ask first:** live Core Data URL, device 수/요청률 또는 cleanup을 활성화해 실행한다.
- 🚫 **Never do:** 기존 실제 Device Event를 삭제하거나 synthetic 부하 결과를 실장비 실증으로 표현한다.
