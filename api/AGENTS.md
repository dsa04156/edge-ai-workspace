# KubeEdge API Module — Agent Instructions

루트 `../AGENTS.md`를 먼저 적용한다. 이 Go module은 KubeEdge external API type, generated
clients와 API 문서를 담는 upstream-synced 라이브러리다. 현재 물리 디바이스 권위 plane이
아니다.

## Build & Test

```bash
go mod download
go test ./...
go test ./apis/componentconfig/edgecore/v1alpha2/validation -run TestValidateEdgeCoreConfiguration
go vet ./...
```

## Structure & Style

- `apis/` — versioned API와 component configuration type
- `client/` — generated clientset, informer와 lister
- `apidoc/generated/` — generated OpenAPI/Swagger output
- `apidoc/tools/` — 생성 도구와 update script

Go 표준 `gofmt`, exported identifier 주석과 Kubernetes API versioning 관례를 따른다.
`zz_generated.*`와 Swagger 산출물은 생성 도구의 결과로만 갱신한다.

## Boundaries

- ✅ **Always do:** API type 변경 시 deepcopy/client/OpenAPI 생성물과 관련 테스트를 함께 검증한다.
- ⚠️ **Ask first:** public API, module dependency, version 또는 code-generation 방식을 변경한다.
- 🚫 **Never do:** KubeEdge Device type을 현재 EdgeX 물리 inventory의 병행 권위로 연결한다.
