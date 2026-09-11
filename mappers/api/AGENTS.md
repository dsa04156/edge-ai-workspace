# Legacy Mapper API Module — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 upstream-synced KubeEdge API module은
MapperFramework 의존성과 과거 통합 실험을 위한 **Legacy / Reference** 코드다.

## Build & Test

```bash
go mod download
go test ./...
go test ./apis/util/... -run TestValidateNodeIP
go vet ./...
```

## Structure & Style

- `apis/` — versioned KubeEdge API와 DMI protobuf
- `client/` — generated clients, informer와 lister
- `apidoc/generated/` — generated OpenAPI/Swagger
- `apidoc/tools/` — 생성 scripts

`gofmt`, Kubernetes API versioning과 generated-file 경계를 유지한다.

## Boundaries

- ✅ **Always do:** public type 변경 시 generated artifacts와 API tests를 검증한다.
- ⚠️ **Ask first:** module version, replace directive 또는 generated API를 변경한다.
- 🚫 **Never do:** KubeEdge Device/DeviceStatus를 현재 EdgeX inventory의 권위나 fallback으로 사용한다.
