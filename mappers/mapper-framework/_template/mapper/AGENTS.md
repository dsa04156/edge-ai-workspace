# Mapper Template — Agent Instructions

상위 `../../AGENTS.md`와 루트 `../../../../AGENTS.md`를 먼저 적용한다. 이 디렉터리는
MapperFramework가 복사·치환하는 **Legacy / Reference template**이며 독립 운영 module이
아니다.

## Validate

현재 template의 `go.mod` 상대 `replace`는 생성 후 `mappers/example-sensor/` 같은 위치를 기준으로 한다.
따라서 이 디렉터리에서 직접 `go test ./...`를 성공 조건으로 사용하지 않는다. 상위 module은
다음으로 검증한다.

```bash
cd ../.. && go test ./...
cd ../.. && go vet ./...
```

## Structure & Style

- `cmd/main.go` — 생성 mapper bootstrap
- `device/`, `driver/` — 구현 확장 지점
- `data/` — publish와 database adapter 예시
- `config.yaml`, `resource/` — runtime 설정과 Kubernetes template
- `hack/make-rules/mapper.sh` — generated mapper build helper

`Template` placeholder, module 상대 경로와 generator가 치환하는 이름을 보존한다.

## Boundaries

- ✅ **Always do:** template 변경이 새 복사본에 필요한 파일과 placeholder를 모두 남기는지 확인한다.
- ⚠️ **Ask first:** template dependency, generated layout 또는 Docker/resource 기본값을 변경한다.
- 🚫 **Never do:** template 자체를 current runtime으로 배포하거나 legacy mapper를 EdgeX fallback으로 설명한다.
