# 문서 안내

이 디렉터리는 KubeEdge 기반 혼합 디바이스 edge AI 운영 가시화 PoC 문서의 진입점이다.
처음 읽을 때는 상세 문서 목록을 훑기보다 `wiki/index.md`에서 전체 지도를 먼저 본다.

## 한 문장 목표

KubeEdge 기반 혼합 디바이스 환경에서 실제 서비스 데모와 디바이스 상태를 통합 가시화하고, 운영자가 dashboard와 read-only 운영 보조 요약을 통해 현재 상태, 이상 지점, 생산성 KPI 의미를 빠르게 이해할 수 있는 edge AI 운영 가시화 PoC 시스템을 구축한다.

짧은 표현:

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

| 순서 | 문서 | 역할 |
|---|---|---|
| 1 | `wiki/index.md` | 전체 지식 지도. 질문이 있을 때 먼저 읽는다. |
| 2 | `wiki/SCHEMA.md` | 에이전트가 wiki를 갱신할 때 따르는 규칙 |
| 3 | `goal.md` | 시스템 구축 목표 고정 |
| 4 | `project-context.md` | 과제 배경과 현재 PoC 방향 |
| 5 | `scope.md` | 현재 포함 범위와 제외 범위 |
| 6 | `ops/runbook-current-demo.md` | 실제 데모 실행과 점검 |

## 문서 묶음

| 묶음 | 기준 | 대표 문서 |
|---|---|---|
| Wiki | Active/Ops 원본문서를 LLM이 합성한 지식 지도 | `wiki/index.md`, `wiki/operating-model.md` |
| Active | 현재 시스템 구축 목표를 직접 설명 | `goal.md`, `service-demo-scenario.md`, `device-service-binding.md` |
| Ops | 데모 실행, 점검, 장애 대응 | `ops/runbook-current-demo.md`, `ops/troubleshooting-network.md` |
| Assistant | read-only 운영 보조 agent 설명 | `kagenti-operator-assistant.md` |
| Archive | 과거 연구, 논문 초안, legacy orchestration | `archive/*` |

정리 기준과 archive 정책은 `docs-cleanup-plan.md`를 따른다.

## 현재 데모 흐름

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

dashboard에서 확인할 핵심 질문:

1. 어떤 device가 등록되어 있는가?
2. 어떤 node에 붙어 있는가?
3. telemetry가 최근에 들어왔는가?
4. DeviceStatus snapshot이 최신인가?
5. mapper와 node는 정상인가?
6. 어떤 service demo group에 연결되어 있는가?
7. 문제가 있다면 어느 device/node/mapper/telemetry 경로를 먼저 봐야 하는가?
8. 이 상태가 현장 생산성 향상 효과로 어떻게 설명되는가?

## Archive 사용 원칙

`docs/archive/`는 과거 실험, 이전 통합 문서, 논문/연구 초안, legacy orchestration 자료를 보관하는 위치다.
새 작업 판단은 Active 문서를 우선한다.

Archive 문서를 읽을 때 주의할 점:

- 현재 구현 방향으로 간주하지 않는다.
- 발표자료에 그대로 옮기지 않는다.
- workflow/offloading/agent-assisted planning을 다음 확정 단계처럼 표현하지 않는다.
- 현재 데모 설명은 서비스 데모, 디바이스-서비스 연결 구조, 통합 운영 가시화, 현장 적용성, 생산성 향상 효과 중심으로 작성한다.
