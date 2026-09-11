# Mapper Framework — Agent Instructions

루트 `../../AGENTS.md`를 먼저 적용한다. 이 Go module과 generator는 과거 KubeEdge mapper
통합을 위한 **Legacy / Reference** 코드이며 현재 물리 디바이스 plane이 아니다.

## Build & Test

```bash
go mod download
go test ./...
go vet ./...
make verify-golang
```

새 mapper 생성은 디렉터리를 만들고 `go mod tidy`를 실행하므로 명시적 승인 후에만 한다.

```bash
make generate ExampleSensor
```

## Structure & Style

- `pkg/common/`, `pkg/config/` — mapper 공통 계약과 설정
- `pkg/grpcclient/`, `pkg/grpcserver/` — EdgeCore DMI 통신
- `pkg/httpserver/` — mapper REST surface
- `_template/mapper/` — 생성 원본
- `hack/make-rules/` — generate/build/verify scripts

`gofmt`, KubeEdge license header와 explicit error 반환 관례를 유지한다.

## Boundaries

- ✅ **Always do:** framework compile/test와 generated template 상대 경로를 검증한다.
- ⚠️ **Ask first:** mapper 생성, vendoring, DMI contract 또는 generator template을 변경한다.
- 🚫 **Never do:** MapperFramework를 EdgeX Device Service의 병행 plane이나 fallback으로 배포한다.
