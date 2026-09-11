# Local Data Cache — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 Go library는 Device Service가 사용하는
device/resource별 bounded in-memory recent sample ring이다. durable storage나 offline
replay queue가 아니다.

## Build & Test

```bash
go mod download
go test ./...
go test -race ./...
go test ./... -run 'TestCache|TestRing'
go vet ./...
```

## Structure & Style

- `cache.go` — retention, memory budget, series rebalance와 stats
- `ring.go` — typed bounded sample ring
- `cache_test.go` — age, series, byte budget와 concurrency 계약

Generic type과 immutable snapshot 관례를 유지하고 모든 capacity 계산은 overflow와 최소
slot 조건을 검증한다.

## Boundaries

- ✅ **Always do:** 시간, sample 수, byte budget과 race 동작을 함께 테스트한다.
- ⚠️ **Ask first:** public generic API, eviction semantics 또는 metrics contract를 변경한다.
- 🚫 **Never do:** cache에 raw telemetry 장기 보존이나 장애 재전송 책임을 추가한다.
