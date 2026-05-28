# 문서 안내

이 디렉터리는 KubeEdge 기반 혼합 디바이스 edge AI 운영 가시화 PoC 문서의 진입점이다.
모든 문서는 `goal.md`의 시스템 구축 목표를 기준으로 읽고 정리한다.

## 시스템 구축 목표

KubeEdge 기반 혼합 디바이스 환경에서 실제 서비스 데모와 디바이스 상태를 통합 가시화하고, 운영자가 dashboard와 read-only 운영 보조 요약을 통해 현재 상태, 이상 지점, 생산성 KPI 의미를 빠르게 이해할 수 있는 edge AI 운영 가시화 PoC 시스템을 구축한다.

짧게 말하면 다음과 같다.

```text
혼합 디바이스 edge AI 서비스 데모를 운영 관점에서 보이게 만드는 시스템
```

현재 문서와 구현은 아래 세 가지를 우선한다.

1. 서비스 데모를 먼저 완성한다.
2. 디바이스-서비스 연결 구조를 dashboard에서 보이게 한다.
3. 실공장 기반 PoC의 현장 적용성과 생산성 향상 효과를 설명한다.

과거 workflow/offloading/agent-assisted planning 계열 문서는 현재 판단 기준이 아니다.
필요할 때만 `docs/archive/`에서 과거 맥락으로 확인한다.

## 먼저 읽을 문서

처음 보는 사람은 아래 순서로 읽는다.

| 순서 | 문서 | 언제 보는가 |
|---|---|---|
| 1 | `goal.md` | 시스템 구축 목표를 하나로 고정할 때 |
| 2 | `project-context.md` | 과제 배경과 현재 PoC 방향을 이해할 때 |
| 3 | `scope.md` | 현재 포함 범위와 제외 범위를 확인할 때 |
| 4 | `service-demo-scenario.md` | 서비스 데모 스토리를 설명할 때 |
| 5 | `ops/runbook-current-demo.md` | 실제 데모를 실행/점검할 때 |
| 6 | `okdong-productivity-kpi.md` | 옥동 시나리오의 생산성 효과를 설명할 때 |
| 7 | `docs-cleanup-plan.md` | 문서 정리 기준과 archive 분류 기준을 볼 때 |

## 운영자가 자주 보는 문서

| 문서 | 내용 |
|---|---|
| `ops/runbook-current-demo.md` | 데모 전 점검, publisher 실행, dashboard 확인, 문제 원인 좁히기 |
| `ops/ci-cd-autodeploy.md` | GitHub Actions와 Argo CD 기반 이미지 build/push/rollout 자동 배포 기준 |
| `ops/gpu-hami-runtime.md` | HAMi 기반 GPU 공유/스케줄링 설치 상태와 GPU 관측 경로 점검 |
| `dashboard-information-structure.md` | dashboard에 표시되는 node/device/service/KPI 정보 구조 |
| `dashboard-policy.md` | healthy/degraded/unavailable 판단 기준 |
| `device-status-policy.md` | DeviceStatus와 raw telemetry 분리 정책 |
| `kubeedge-edgex-model-mapping.md` | KubeEdge DeviceModel property와 EdgeX Device Profile resource 매핑표 |
| `device-service-binding.md` | device가 어떤 service demo group에 연결되는지 |
| `current-demo-path.md` | 현재 device -> mapper/DeviceStatus -> state-aggregator -> dashboard 흐름과 EdgeX telemetry plane TODO |
| `raw-telemetry-data-plane.md` | MapperFramework 책임 축소와 EdgeX 기반 raw telemetry ingestion plane 목표 |
| `edge-orch/workflow-designer/README.md` | 서비스 stage, input device, target node를 dry-run으로 설계/시각화하는 Workflow Designer MVP |
| `kagenti-operator-assistant.md` | Kagenti 운영 보조 agent PoC와 read-only 요약 API |

## 구현자가 자주 보는 문서

| 문서 | 내용 |
|---|---|
| `repo-structure.md` | 레포 디렉터리별 역할 |
| `current-demo-path.md` | 현재 구현 경로 |
| `device-service-binding.md` | backend service binding 필드와 판단 기준 |
| `dashboard-information-structure.md` | dashboard API/화면 구조 |
| `kagenti-operator-assistant.md` | `/state/operator-assistant` 응답 구조와 guardrail |
| `roadmap.md` | 현재 산출물과 정리 우선순위 |

## 문서 정리 기준

문서는 아래 네 묶음으로 관리한다.

| 분류 | 기준 | 예시 |
|---|---|---|
| Active | 현재 시스템 구축 목표를 직접 설명 | `goal.md`, `service-demo-scenario.md`, `device-service-binding.md` |
| Ops | 데모 실행, 점검, 장애 대응 | `ops/runbook-current-demo.md`, `ops/troubleshooting-network.md` |
| Assistant | read-only 운영 보조 agent 설명 | `kagenti-operator-assistant.md` |
| Archive | 과거 연구, 논문 초안, legacy orchestration | `archive/*` |

문서 정리 세부 계획은 `docs-cleanup-plan.md`를 따른다.

## 운영 데모 빠른 흐름

현재 데모는 아래 흐름을 보여준다.

```text
Device 등록
  -> edge node 할당
  -> MQTT command/status
  -> mqttvirtual mapper / MapperFramework DMI adapter
  -> KubeEdge DeviceStatus summary
  -> EdgeX raw telemetry ingestion plane TODO
  -> state-aggregator
  -> dashboard
  -> operator assistant summary
  -> 운영자 판단 / KPI 설명
```

운영자가 dashboard에서 확인해야 하는 핵심 질문은 다음이다.

1. 어떤 device가 등록되어 있는가?
2. 어떤 node에 붙어 있는가?
3. telemetry가 최근에 들어왔는가?
4. DeviceStatus snapshot이 최신인가?
5. mapper와 node는 정상인가?
6. 어떤 service demo group에 연결되어 있는가?
7. 이 service는 어떤 stage 흐름이고 각 stage는 어느 node에서 실행되는 구조인가?
8. 문제가 있다면 어느 device/node/mapper/telemetry 경로를 먼저 봐야 하는가?
9. 이 상태가 현장 생산성 향상 효과로 어떻게 설명되는가?

## 현재 주요 산출물

| 산출물 | 문서 |
|---|---|
| 시스템 구축 목표 | `goal.md` |
| 서비스 데모 시나리오 | `service-demo-scenario.md` |
| 디바이스-서비스 바인딩 명세 | `device-service-binding.md` |
| 통합 dashboard 정보 구조 | `dashboard-information-structure.md` |
| Workflow Designer MVP | `../edge-orch/workflow-designer/README.md` |
| 현재 데모 실행 runbook | `ops/runbook-current-demo.md` |
| GPU runtime 운영 메모 | `ops/gpu-hami-runtime.md` |
| CI/CD 자동 배포 기준 | `ops/ci-cd-autodeploy.md` |
| 옥동 시나리오 생산성 KPI | `okdong-productivity-kpi.md` |
| Kagenti 운영 보조 agent PoC | `kagenti-operator-assistant.md` |
| Raw telemetry data-plane 목표 구조 | `raw-telemetry-data-plane.md` |
| KubeEdge-EdgeX 모델 매핑표 | `kubeedge-edgex-model-mapping.md` |
| 현재 PoC 범위 | `scope.md` |
| 문서 정리 계획 | `docs-cleanup-plan.md` |

## Archive 사용 원칙

`docs/archive/`는 과거 실험, 이전 통합 문서, 논문/연구 초안, legacy orchestration 자료를 보관하는 위치다.
새 작업 판단은 Active 문서를 우선한다.

Archive 문서를 읽을 때 주의할 점:

- 현재 구현 방향으로 간주하지 않는다.
- 발표자료에 그대로 옮기지 않는다.
- workflow/offloading/agent-assisted planning을 다음 확정 단계처럼 표현하지 않는다.
- 현재 데모 설명은 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화, 현장 적용성, 생산성 향상 효과 중심으로 작성한다.
