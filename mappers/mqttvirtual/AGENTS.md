# MQTT Virtual Mapper — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 Go mapper는 MQTT/KubeEdge DeviceStatus와
direct database publish를 시험한 **Legacy / Reference** 통합 경로다. 현재 물리 inventory나
telemetry fallback이 아니다.

## Build & Test

```bash
go mod download
go build ./...
go test ./...
go test ./device ./status ./telemetry
go vet ./...
kubectl kustomize resource >/dev/null
```

## Structure & Style

- `cmd/main.go` — mapper bootstrap과 EdgeCore 등록
- `device/`, `driver/` — legacy device/twin와 protocol behavior
- `telemetry/`, `status/` — sample freshness와 heartbeat projection
- `data/` — legacy DB/publish adapter
- `resource/` — historical Kubernetes resources

Go 표준 `gofmt`, bounded timeout과 explicit status/error contract를 유지한다.

## Boundaries

- ✅ **Always do:** legacy tests와 Kustomize render를 실행한다.
- ⚠️ **Ask first:** topic, database sink, EdgeCore socket 또는 deployment resource를 변경한다.
- 🚫 **Never do:** `command`/`heartbeat` topic이나 direct-to-Influx 경로를 현재 운영 fallback으로 사용한다.
