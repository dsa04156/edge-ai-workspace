# Edge AI Workspace

KubeEdge의 edge node/workload 관리와 EdgeX의 물리 Device/Profile/Event 관리를 결합한
혼합 디바이스 엣지 AI PoC다.

현재 구현과 운영 경계는 다음 문서부터 확인한다.

- [문서 안내](docs/문서-안내.md)
- [2026년도 2차년도 옥동 PoC 추진계획](docs/단계별-추진계획.md)
- [프로젝트 범위](docs/프로젝트-범위.md)
- [디바이스 발견 및 등록 아키텍처](docs/디바이스-발견-아키텍처.md)
- [디바이스 발견 및 등록 API](docs/디바이스-등록-API.md)
- [디바이스 Catalog](docs/디바이스-카탈로그.md)
- [현재 구현 상태](docs/현재-구현-상태.md)
- [발견·등록 운영 절차](docs/ops/디바이스-발견-등록-운영.md)

운영 EdgeX 배포의 단일 진입점은 `edgex/k8s`이고, Argo CD Application
`edgex-telemetry`가 관리한다. EdgeX Core Metadata/Core Data가 물리 디바이스와
telemetry의 권위이며 KubeEdge는 node와 workload를 관리한다.

빠른 회귀 테스트:

```bash
cd edgex/adapter-controller && PYTHONPATH=. pytest -q
cd ../device-discovery-agent && PYTHONPATH=. pytest -q
cd ../device-serial && go test ./...
```
