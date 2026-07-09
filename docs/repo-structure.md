# Repository Structure

## 목적

이 문서는 레포 안의 디렉터리와 주요 파일을 현재 PoC 범위 기준으로 분류한다.
새 작업을 시작할 때 어떤 경로를 현재 구현 경로로 볼지, 어떤 경로를 보조/참조/보관 대상으로 볼지 판단하기 위한 기준 문서다.

현재 범위 판단은 `docs/scope.md`를 우선한다.

## 분류 기준

| 분류 | 의미 |
|---|---|
| Current | 현재 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화에 직접 연결되는 경로 |
| Current-supporting | 설치, 배포, 운영, ingress, registry 등 현재 범위를 지원하는 경로 |
| Legacy / Reference | 현재 연구 방향에서 진행하지 않는 과거 workflow/offloading/agent-planning 실험 또는 참조 구현 |
| Archive | 과거 통합 기록, 연구 초안, 논문/실험 자료. 현재 판단 기준이 아님 |
| 외부/참조 | KubeEdge API, mapper framework 등 외부 코드 또는 참고용 코드 |
| Cleanup Review | 운영 중 생성된 데이터, 캐시, runner 산출물 등 레포 관리 대상인지 검토가 필요한 경로 |

## 현재 범위 경로

| 경로 | 역할 | 작업 원칙 |
|---|---|---|
| `docs/` active guides | 현재 PoC 판단 기준 문서 | `scope.md`, `project-context.md`, `device-status-policy.md`, `dashboard-policy.md`, `roadmap.md` 우선 |
| `edge-device/` | KubeEdge DeviceModel/Device manifest와 생성 스크립트 | Jetson/RPi 사전 등록 방식 유지, DeviceStatus/raw telemetry 정책 준수 |
| `mappers/mqttvirtual/` | MQTT 기반 KubeEdge mapper 구현 | MQTT telemetry/command, DMI, InfluxDB pushMethod, DeviceStatus allowlist 정책 기준으로 유지 |
| `mappers/script/test_device.py` | 테스트 publisher | edge node 로컬 mosquitto(`127.0.0.1:1883`) 기준, `DEVICE_PLAN`/`DEVICE_FILTER` 사용 |
| `edge-orch/state-aggregator/` | KubeEdge/InfluxDB/Prometheus 상태 통합 API와 dashboard | 현재 데모 운영 경로의 상태 통합 컴포넌트로 유지 |
| `influxdb/` | telemetry data-plane 저장소 manifest | raw telemetry 저장 경로로 유지 |

## 2차년도 설계 트랙 경로

다음 경로는 현재 서비스 데모 기능으로 주장하지 않고, 2차년도 협약 방향에 맞춘 설계/프로토타입 후보로 관리한다.

| 경로 | 역할 | 작업 원칙 |
|---|---|---|
| `docs/second-year-virtual-device-workflow-architecture.md` | 등록 Device/source, 디바이스트윈, AI 서비스 워크플로우 재설계 기준 | 현재 PoC는 KubeEdge Device와 InfluxDB freshness 기반으로 관리하고, 별도 VirtualDevice registry는 현재 구현 경로로 두지 않음 |
| `docs/(2차년도협약용) 연구개발계획서-엣지 컴퓨팅 시스템을 위한 대규모 혼합 디바이스 제어·관리 플랫폼 개발_0415.pdf` | 2차년도 협약 방향 원문 | 요구사항과 표현 근거로만 사용하고 PDF 원본은 수정하지 않음 |
| 신규 `workflow-*` 경로 후보 | AI 서비스 workflow builder/runtime/control plane 후보 | legacy workflow 코드를 현행 기능으로 오해하지 않도록 새 설계 경계 명시 |
| 신규 `resource-augmentation-scheduler` 경로 후보 | runtime pod/service 사용량과 `AugmentationResource`/`DeviceAugmentation` 상태를 결합해 자원증강 recommendation/status를 계산하는 v1 prototype 후보 | dashboard 수동 실행이나 per-click Job 생성이 아니라 controller/scheduler 정책 경로로 다룸 |

## 현재 범위 보조 경로

| 경로 | 역할 | 작업 원칙 |
|---|---|---|
| `docs/ops/` | 노드 join, pod 연결성, 네트워크 troubleshooting 등 운영 문서 | 현재 데모 실행/점검 runbook과 연결 |
| `kubeedge-tools/` | KubeEdge 설치, patch, reset, cloud/edge setup 도구 | 운영 절차 문서와 연결하되 대형 tarball/산출물은 별도 관리 검토 |
| `edge-orch-argocd/` | Argo CD application/ingress 관련 리소스 | 현재 배포 경로에 쓰는 파일만 명확히 표시 |
| `traefik/` | Traefik ingress/ingressroute 리소스 | 현재 노출 중인 서비스와 연결된 파일만 유지 기준 명시 |
| `harbor/` | Harbor registry 설정 | 현재 이미지 배포 경로 보조로 유지 |
| `.github/` | GitHub workflow 등 자동화 설정 | 현재 CI/CD에 쓰는 항목만 유지 |
| `Easy-Kube-Command/` | kubectl 편의 명령 모음 | 운영 보조 자료로 유지 여부 검토 |

## Legacy / Reference 및 Archive 경로

다음 경로는 현재 연구 방향에서 진행하지 않는다.
새 문서에서 후속 고도화 또는 예정 기능처럼 표현하지 않는다. 에이전트와 작업자는 이 경로를 히스토리/비교/참조 자료로만 읽고, 현재 구현 요구사항으로 사용하지 않는다.

| 경로 | 현재 처리 원칙 |
|---|---|
| `edge-orch/workflow_executor/` | Legacy / Reference. 과거 workflow 실행/orchestration 실험. 현재 service demo 구현 대상으로 사용하지 않음 |
| `edge-orch/workflow_reporter/` | Legacy / Reference. 과거 stage event reporting 실험. 현재 dashboard 요구사항으로 해석하지 않음 |
| `edge-orch/placement_engine/` | Legacy / Reference. 과거 placement/offloading/replanning 실험. 현재 자동 재배치 기능으로 설명하지 않음 |
| `workflow/` | Legacy / Reference. 과거 workflow/event/scenario manifest. 현재 배포 경로로 사용하지 않음 |
| `docs/archive/legacy-orchestration/` | Archive. 현재 판단 기준이 아니라 과거 orchestration 자료 |
| `docs/archive/embedded-conference/` | Archive. replanning/offloading 실험은 현재 방향과 분리된 과거 자료 |
| `docs/archive/integration/` | Archive. 과거 통합 기록, 현재 판단은 active guides 우선 |

## 외부/참조 성격 경로

| 경로 | 역할 | 작업 원칙 |
|---|---|---|
| `api/` | KubeEdge API sync/reference 성격 | 직접 수정 전 출처와 필요성 확인 |
| `mappers/api/` | KubeEdge mapper/API reference 성격 | 현재 mapper 구현과 혼동하지 않도록 주의 |
| `mappers/mapper-framework/` | KubeEdge mapper framework reference/scaffold | `mappers/mqttvirtual/`과 역할 분리 |
| `codex-skills/` | 별도 agent/skill 자료 | 현재 PoC 구현 경로와 분리 |

## 정리 검토 대상

다음 경로/파일은 운영 중 생성된 자료이거나 레포에 계속 둘지 검토가 필요하다.
삭제 또는 이동은 별도 확인 후 진행한다.

| 경로 | 검토 이유 |
|---|---|
| `actions-runner/` | Cleanup Review. GitHub Actions runner 작업 디렉터리와 로그/체크아웃 산출물 포함 |
| `Platform-Service/` | Cleanup Review. 여러 서비스, venv, mysql data 등 운영/실험 산출물이 섞여 있음. 현재 PoC 경로로 승격 전 역할 확인 필요 |
| `.pytest_cache/`, `**/__pycache__/` | 테스트/파이썬 캐시 |
| `.vscode/` | 개인/환경 설정일 수 있음 |
| `her/` | 역할 확인 필요 |
| `middleware/` | 현재 PoC와의 연결성 확인 필요 |
| `통합문서.md` | 과거 통합 문서로 보이며 archive 이동 여부 검토 |
| `deploy.yaml` | 현재 사용 여부 확인 필요 |
| `traefik/gemma-ingressroute.yaml` | 현재 untracked 파일, 생성 의도 확인 필요 |

## edge-orch 내부 기준

`edge-orch/`에는 현재 경로와 제외 경로가 함께 있다.
따라서 이 디렉터리에서 작업할 때는 다음 기준을 따른다.

| 하위 경로 | 분류 | 원칙 |
|---|---|---|
| `edge-orch/state-aggregator/` | 현재 범위 | 현재 운영 상태 API/dashboard 경로 |
| `edge-orch/redis/` | 현재 범위 보조/확인 필요 | state-aggregator 또는 현재 서비스 데모와 연결될 때만 유지 |
| `edge-orch/nvidia-device-plugin/` | 현재 범위 보조 | x86 추론 서버/GPU 운영 보조 |
| HAMi Helm release `hami` (`kube-system`) | 현재 범위 보조 | x86 GPU 서버의 GPU 공유/스케줄링 기반. 설치/점검 메모는 `docs/ops/gpu-hami-runtime.md` |
| `edge-orch/gemma/` | 확인 필요 | 현재 서비스 데모와 연결되는지 확인 후 분류 |
| `edge-orch/vision_stage_runner/` | 2차년도 prototype 후보/확인 필요 | runtime resource augmentation scheduler가 선택한 workload/resource 검증 경로와 연결되는 경우에만 제한적으로 승격 |
| `edge-orch/workflow_executor/` | Legacy / Reference | 과거 workflow orchestration 실험. 현재 제외 |
| `edge-orch/workflow_reporter/` | Legacy / Reference | 과거 stage event pipeline 실험. 현재 제외 |
| `edge-orch/placement_engine/` | Legacy / Reference | 과거 placement/offloading 실험. 현재 제외 |
| `edge-orch/experiments/` | Legacy / Reference 또는 Cleanup Review | 실험 자료로 분리하고 현재 범위 승격 전 확인 |

## 새 작업 판단 절차

새 파일을 만들거나 기존 파일을 수정하기 전에 다음을 확인한다.

1. `docs/scope.md`의 현재 PoC 범위에 들어가는가?
2. 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화에 직접 기여하는가?
3. DeviceStatus와 raw telemetry 분리 정책을 지키는가?
4. workflow/offloading/agent-planning 계열을 다시 현재 경로로 끌어오는 작업은 아닌가?
5. 현재 범위가 아니라면 archive/reference/정리 검토 대상으로 표시할 수 있는가?

## 정리 순서 제안

1. 현재 범위 문서 유지: `scope.md`, `project-context.md`, `device-status-policy.md`, `dashboard-policy.md`, `roadmap.md`
2. 현재 데모 경로 문서화: Device -> MQTT -> mapper -> InfluxDB/DeviceStatus -> state-aggregator -> dashboard
3. 디바이스-서비스 바인딩 명세 작성
4. 서비스 데모 시나리오 작성
5. 제외/보관 경로를 README 또는 archive index에 명시
6. 정리 검토 대상에서 캐시/runner/운영 데이터 분리 여부 결정
