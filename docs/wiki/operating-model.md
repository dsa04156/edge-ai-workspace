# 운영 모델

## 한 줄 요약

현재 시스템은 KubeEdge 기반 혼합 디바이스 엣지 AI 서비스 데모를 운영 관점에서 보이게 만드는 PoC다.
핵심은 디바이스와 서비스를 실제로 연결하고, 그 상태를 dashboard와 read-only 운영 보조 요약으로 해석 가능하게 만드는 것이다.

## 현재 기준

이 프로젝트는 동적 orchestration 전체를 먼저 완성하는 단계가 아니다.
현재 우선순위는 서비스 데모 1종을 운영 관점에서 설명 가능하게 만드는 것이다.

1. 디바이스가 등록되고 edge node에 할당된다.
2. telemetry와 command 경로가 보인다.
3. mapper와 status 경로를 점검할 수 있다.
4. 상태가 `state-aggregator` API로 모인다.
5. dashboard 상태, service binding, 생산성 KPI를 함께 설명할 수 있다.

짧은 정의:

```text
혼합 디바이스 edge AI 서비스 데모를 운영 관점에서 보이게 만드는 시스템
```

## 경계

현재 모델은 다음을 주장하지 않는다.

- 완전 자율형 orchestration
- LLM 기반 인프라 제어
- dynamic offloading이 현재 데모 경로라는 주장
- `workflow_executor` 또는 `placement_engine`이 현재 데모 제어 컴포넌트라는 주장
- runtime replanning 구현 완료

Legacy workflow, offloading, selective replanning, agent-assisted planning 자료는 `docs/scope.md`에서 승격하지 않는 한 과거 맥락 또는 설계 후보로만 본다.

## 운영상 의미

새 문서나 기능이 현재 PoC 범위인지 판단할 때 이 페이지를 기준으로 삼는다.
아래 질문에 직접 답하면 현재 경로에 가깝다.

- 어떤 device가 존재하는가?
- 어떤 node에 할당되어 있는가?
- 최근 telemetry가 보이는가?
- `DeviceStatus` snapshot이 운영 신호로 최신인가?
- mapper, node, telemetry 중 어디를 먼저 봐야 하는가?
- 어떤 service demo group이 이 device에 의존하는가?
- 이 상태가 옥동 생산성 설명과 어떻게 연결되는가?

주요 내용이 dynamic workflow 실행, placement 최적화, agent control 확장이라면 먼저 2차년도 설계 트랙 또는 legacy/reference로 분류한다.

## 관련 Wiki

- [현재 데모 흐름](current-demo-flow.md)
- [상태와 텔레메트리](status-and-telemetry.md)
- [대시보드와 KPI 모델](dashboard-and-kpi.md)
- [2차년도 설계 트랙](second-year-design-track.md)

## 근거 문서

- [시스템 구축 목표](../goal.md)
- [프로젝트 배경](../project-context.md)
- [프로젝트 범위](../scope.md)
- [로드맵](../roadmap.md)
