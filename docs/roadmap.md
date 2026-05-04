# Roadmap

## 현재 단계

현재 단계는 서비스 데모와 통합 운영 가시화가 우선이다.

목표:

1. 디바이스가 실제로 등록되고 관리되는지 보인다.
2. 디바이스와 서비스가 실제로 연결되는지 보인다.
3. 전체 관계와 상태가 대시보드에서 보인다.
4. 옥동 시나리오 등 현장 적용 효과를 생산성 언어로 설명한다.

현재 데모 운영 경로는 `state-aggregator` 중심으로 단순화한다.
워크플로우 실행기, placement engine, workflow reporter, 동적 offloading 계열은 현행 연구 방향과 데모 경로에서 제외한다.

## 현재 산출물

즉시 필요한 산출물:

1. 서비스 데모 시나리오 정의서
2. 디바이스 등록/관리 절차서
3. 디바이스-서비스 바인딩 명세
4. 통합 대시보드 정보 구조 정의서
5. 옥동 시나리오 생산성 KPI 정의서

그 다음 정리 산출물:

1. 현재 PoC 범위 정의서
2. 레포 구조와 컴포넌트 역할표
3. 현재 데모 실행/점검 runbook
4. 운영 상태 판단 기준과 troubleshooting guide
5. 실공장 적용성 설명 자료

## 현재 구현 방향

현재 구현은 다음 흐름을 기준으로 한다.

```text
physical / virtual device
  -> MQTT telemetry / command topic
  -> mqttvirtual mapper
  -> KubeEdge DeviceStatus snapshot
  -> InfluxDB raw telemetry data-plane
  -> state-aggregator
  -> dashboard / service demo view
```

핵심은 디바이스, 서비스, 노드, telemetry, 운영 상태를 하나의 설명 가능한 PoC 경로로 연결하는 것이다.

## 현재 범위에서 제외하는 경로

다음 경로는 현재 연구 방향에서 진행하지 않는다.
새 문서나 발표자료에서 후속 고도화 또는 예정 기능처럼 표현하지 않는다.

- 동적 workflow 분해/실행
- runtime replanning
- placement engine 기반 자동 재배치
- cost model 기반 offloading 판단
- workflow_executor 중심 orchestration
- workflow_reporter 중심 stage event pipeline
- agent-assisted planning layer
- LLM이 전체 플랫폼 제어를 수행하는 구조
- 전체 플랫폼 자율 제어형 orchestration

위 항목들은 필요한 경우 과거 검토/실험 자료 또는 archive로만 다룬다.

## 정리 우선순위

1. 현재 PoC 범위와 제외 범위를 문서화한다.
2. 현재 데모 경로와 관련 컴포넌트를 명확히 표시한다.
3. 디바이스-서비스 바인딩 명세를 작성한다.
4. 서비스 데모 시나리오를 작성한다.
5. 대시보드에서 보여줄 정보 구조와 KPI를 정리한다.
6. 기존 workflow/offloading/agent-planning 문서는 현재 경로와 분리한다.

## 문서 표현 원칙

유지할 표현:

- 서비스 데모 우선
- 디바이스-서비스 연결 구조
- 통합 운영 가시화
- 실공장 기반 PoC
- 현장 적용성
- 생산성 향상 효과
- 단계적 구현

피할 표현:

- 전체 플랫폼 자율 제어형 orchestration을 실증 완료처럼 보이게 하는 표현
- LLM 기반 전역 제어를 현재 기능처럼 보이게 하는 표현
- 동적 workflow 실행이 이미 완료된 것처럼 보이는 표현
- offloading 고도화가 다음 확정 단계인 것처럼 보이는 표현
- agent-assisted planning이 현재 연구 방향인 것처럼 보이는 표현
- 고도화 기능이 이미 실증 완료된 것처럼 보이는 표현
