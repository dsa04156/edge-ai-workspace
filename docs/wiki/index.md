# KubeEdge PoC LLM Wiki

## 한 줄 요약

이 wiki는 KubeEdge 기반 혼합 디바이스 엣지 AI PoC 문서를 한눈에 찾기 위한 지식 지도다.
정확한 명령, API, 정책 문구가 필요할 때만 원본문서로 들어간다.

## 먼저 볼 지도

| 질문 | Wiki | 근거 문서 |
|---|---|---|
| 지금 무엇을 만드는가? | [운영 모델](operating-model.md) | [목표](../goal.md), [프로젝트 배경](../project-context.md), [범위](../scope.md) |
| 디바이스부터 dashboard까지 어떻게 이어지는가? | [현재 데모 흐름](current-demo-flow.md) | [현재 데모 경로](../current-demo-path.md), [디바이스-서비스 바인딩](../device-service-binding.md) |
| `DeviceStatus`와 raw telemetry는 어떻게 다른가? | [상태와 텔레메트리](status-and-telemetry.md) | [DeviceStatus 정책](../device-status-policy.md), [raw telemetry plane](../raw-telemetry-data-plane.md) |
| dashboard는 무엇을 보고 상태를 판단하는가? | [대시보드와 KPI 모델](dashboard-and-kpi.md) | [정보 구조](../dashboard-information-structure.md), [판단 기준](../dashboard-policy.md), [옥동 KPI](../okdong-productivity-kpi.md) |
| 데모 실행과 점검은 어디서 시작하는가? | [운영 진입점](operations-entry-points.md) | [runbook](../ops/runbook-current-demo.md), [dashboard 검증](../ops/dashboard-verification.md), [E2E 검증](../ops/e2e-demo-verification.md) |
| 2차년도 설계는 현재 기능과 어떻게 구분하는가? | [2차년도 설계 트랙](second-year-design-track.md) | [2차년도 아키텍처](../second-year-virtual-device-workflow-architecture.md), [로드맵](../roadmap.md) |

## Wiki 문서

- [운영 모델](operating-model.md): 현재 PoC를 “서비스 데모 운영 가시화”로 고정한다.
- [현재 데모 흐름](current-demo-flow.md): device, MQTT, mapper, telemetry store, state-aggregator, dashboard의 연결을 정리한다.
- [상태와 텔레메트리](status-and-telemetry.md): `DeviceStatus` snapshot과 raw telemetry data-plane을 분리한다.
- [대시보드와 KPI 모델](dashboard-and-kpi.md): node/device/service/KPI를 운영 판단 기준으로 묶는다.
- [운영 진입점](operations-entry-points.md): 실제 데모 실행과 검증 문서로 안내한다.
- [2차년도 설계 트랙](second-year-design-track.md): 가상디바이스, 디바이스트윈, workflow 설계를 현재 기능 주장과 분리한다.

## 원본문서 묶음

### Active

- [문서 안내](../README.md): 사람용 첫 진입점
- [시스템 구축 목표](../goal.md): 현재 목표 고정
- [프로젝트 배경](../project-context.md): 과제 배경, 노드, 디바이스, 현재 구현 상태
- [프로젝트 범위](../scope.md): Current, 2차년도, 보조, Legacy, Archive 경계
- [현재 데모 경로](../current-demo-path.md): device부터 dashboard까지의 구현 경로
- [디바이스-서비스 바인딩](../device-service-binding.md): device와 service demo group의 운영 관계
- [대시보드 정보 구조](../dashboard-information-structure.md): dashboard API와 화면 정보 구조
- [대시보드 판단 기준](../dashboard-policy.md): available/degraded/unavailable 판단
- [DeviceStatus 정책](../device-status-policy.md): status snapshot과 raw telemetry 분리
- [옥동 생산성 KPI](../okdong-productivity-kpi.md): 현장 생산성 효과 설명
- [로드맵](../roadmap.md): 현재 산출물과 2차년도 방향

### Ops

- [현재 데모 Runbook](../ops/runbook-current-demo.md): 데모 실행과 점검
- [Dashboard 검증](../ops/dashboard-verification.md): dashboard 검증 체크리스트
- [E2E 데모 검증](../ops/e2e-demo-verification.md): end-to-end 검증
- [네트워크 트러블슈팅](../ops/troubleshooting-network.md): 네트워크 문제 좁히기
- [HAMi GPU runtime](../ops/gpu-hami-runtime.md): GPU 운영 관측 메모

### Archive

`docs/archive/`는 과거 연구, 통합 기록, legacy orchestration 맥락이다.
현재 기능으로 설명하려면 먼저 `docs/scope.md`와 `docs/repo-structure.md`에서 승격 근거를 명시한다.

## 유지 관리

- 규칙: [LLM Wiki 운영 규칙](SCHEMA.md)
- 로그: [Wiki 변경 로그](log.md)

wiki를 수정할 때는 먼저 [LLM Wiki 운영 규칙](SCHEMA.md)을 읽는다.
