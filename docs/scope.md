# Project Scope

## 목적

이 문서는 현재 PoC에서 무엇을 구현 범위로 볼지, 무엇을 현재 연구 방향에서 제외할지 정리한다.
레포 안에는 현재 구현물, 과거 실험, 운영 도구, 연구 문서가 함께 있으므로 새 작업 판단은 이 문서를 기준으로 한다.


## 범위 분류 용어

이 문서와 `docs/repo-structure.md`에서 쓰는 분류는 다음 의미로 고정한다.

| 분류 | 의미 | 처리 규칙 |
|---|---|---|
| Current | 현재 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화에 직접 연결되는 구현 경로 | 새 기능/수정의 기본 대상 |
| Current-supporting | 설치, 배포, 운영, ingress, registry, GPU runtime처럼 현재 경로를 지원하는 자료 | 현재 경로와 연결될 때만 수정 |
| Legacy / Reference | 과거 workflow, placement, offloading, agent-planning 실험 또는 참조 구현 | 히스토리와 비교 근거로만 읽고 현재 요구사항으로 해석하지 않음 |
| Archive | 과거 통합 기록, 연구 초안, 논문/실험 자료 | 현재 판단 기준이 아니며 필요할 때만 인용 |
| Cleanup Review | 캐시, runner 산출물, 대형 바이너리, 운영 중 생성 데이터처럼 보존 여부 검토가 필요한 자료 | 삭제/이동 전 별도 승인 필요 |

`Legacy / Reference`와 `Archive` 자료는 현재 PoC 구현 방향을 바꾸는 근거가 아니다. 해당 자료를 현재 범위로 승격하려면 먼저 이 문서와 `docs/repo-structure.md`에 승격 이유, 현재 경로와의 연결, 검증 기준을 명시한다.

## 현재 PoC 범위

현재 범위는 혼합 디바이스 엣지 AI 플랫폼을 실공장 기반 서비스 데모 관점에서 설명 가능하게 만드는 것이다.

포함하는 방향:

- KubeEdge 기반 디바이스 등록/관리
- Jetson, Raspberry Pi, x86 서버가 함께 있는 mixed-device 환경
- 디바이스와 서비스의 연결 구조
- MQTT 기반 telemetry / command 경로
- mapper 기반 디바이스 연동
- raw telemetry data-plane과 운영 status-plane 분리
- InfluxDB 기반 telemetry 저장 및 latest 상태 조회
- Prometheus/Kubernetes 기반 node/service 상태 수집
- state-aggregator 기반 통합 운영 상태 API
- dashboard 기반 디바이스, 노드, 서비스, KPI 가시화
- 서비스 데모 시나리오와 생산성 향상 효과 설명

현재 범위의 핵심 표현:

- 서비스 데모 우선
- 디바이스-서비스 연결 구조
- 통합 운영 가시화
- 실공장 기반 PoC
- 현장 적용성
- 생산성 향상 효과
- 단계적 구현

## 현재 구현 과정에 포함되는 컴포넌트

현재 구현 과정에서 직접 다루는 컴포넌트는 다음과 같다.

| 구분 | 경로/컴포넌트 | 역할 |
|---|---|---|
| 디바이스 정의 | `edge-device/` | DeviceModel / Device manifest, Jetson/RPi 디바이스 배치 |
| 테스트 publisher | `mappers/script/test_device.py` | MQTT telemetry / command 테스트 |
| mapper | `mappers/mqttvirtual/` | MQTT topic 구독, command publish, KubeEdge DMI 연동 |
| telemetry 저장 | `influxdb/` | raw telemetry data-plane 저장소 |
| 상태 통합 | `edge-orch/state-aggregator/` | KubeEdge/InfluxDB/Prometheus 상태 통합 API |
| 대시보드 | `edge-orch/state-aggregator/app/static/` | 운영 가시화 UI |
| GPU runtime 보조 | HAMi Helm release `hami` in `kube-system` | x86 GPU 서버의 GPU 공유/스케줄링 기반. DeviceStatus/raw telemetry 경로가 아니라 node observability와 추론 Pod 자원 운영 보조 |
| 운영 도구 | `kubeedge-tools/`, `docs/ops/` | 설치, 노드 join, 네트워크 점검, 운영 절차 |
| 배포 보조 | `edge-orch-argocd/`, `traefik/`, `harbor/` | Argo CD, ingress, registry 관련 리소스 |

## 현재 연구 방향에서 제외하는 것

다음 항목은 현재 연구 방향에서 진행하지 않는다.
따라서 새 문서나 발표에서 앞으로 구현할 후속 고도화처럼 표현하지 않는다.

- 동적 workflow 분해/실행
- runtime replanning
- placement engine 기반 자동 재배치
- cost model 기반 offloading 판단
- workflow_executor 중심 orchestration
- workflow_reporter 중심 stage event pipeline
- agent-assisted planning layer
- LLM이 전체 플랫폼 제어를 수행하는 구조
- 전체 플랫폼 자율 제어형 orchestration

이 항목들은 필요한 경우 `Legacy / Reference` 또는 `Archive` 자료로만 다룬다. 현재 구현 요구사항, 발표자료의 현행 기능, 또는 다음 확정 단계처럼 해석하지 않는다.

## 제외 대상 컴포넌트 처리 원칙

| 경로/컴포넌트 | 현재 처리 원칙 |
|---|---|
| `edge-orch/workflow_executor/` | Legacy / Reference. 과거 workflow 실행/orchestration 실험으로만 유지 |
| `edge-orch/workflow_reporter/` | Legacy / Reference. 과거 stage event reporting 실험으로만 유지 |
| `edge-orch/placement_engine/` | Legacy / Reference. 과거 placement/offloading/replanning 실험으로만 유지 |
| `workflow/` | Legacy / Reference. 과거 workflow/event/scenario manifest로만 유지 |
| `docs/archive/legacy-orchestration/` | Archive. 현재 판단 기준이 아니라 과거 orchestration 자료 |
| `docs/archive/embedded-conference/`의 replanning/offloading 실험 | Archive. 현재 방향과 분리된 과거 실험 자료 |

## 문서 작성 원칙

현재 문서와 발표자료에서는 다음 표현을 사용한다.

유지할 표현:

- 서비스 데모 우선
- 디바이스-서비스 연결 구조
- 통합 운영 가시화
- 실공장 기반 PoC
- 현장 적용성
- 생산성 향상 효과
- 단계적 구현

피할 표현:

- dynamic offloading을 다음 구현 목표처럼 제시하는 표현
- 전체 플랫폼 자율 제어형 orchestration을 실증 완료처럼 보이게 하는 표현
- LLM 기반 전역 제어를 현재 기능처럼 보이게 하는 표현
- 동적 workflow 실행이 이미 완료된 것처럼 보이는 표현
- agent-assisted planning을 현재 연구 방향처럼 제시하는 표현
- 고도화 기능이 이미 실증 완료된 것처럼 보이는 표현

## 작업 판단 기준

새 작업을 시작할 때는 다음 순서로 판단한다.

1. 서비스 데모 또는 디바이스-서비스 연결 구조에 직접 기여하는가?
2. 통합 운영 가시화 또는 상태 판단을 명확하게 하는가?
3. DeviceStatus와 raw telemetry 분리 정책을 지키는가?
4. 실공장 기반 PoC와 현장 적용성 설명에 도움이 되는가?
5. workflow/offloading/agent-planning 계열로 다시 확장되는 작업은 아닌가?

1~4에 해당하면 현재 범위에 포함한다.
5에 해당하면 현재 작업에서 제외하거나 archive/reference로 분리한다.
