# 시스템 구축 목표

이 문서는 현재 KubeEdge 기반 혼합 디바이스 엣지 AI PoC에서 흔들리지 않아야 할 시스템 구축 목표를 정의한다.
기존 문서와 구현은 이 목표를 기준으로 Active, Ops, Archive로 나눈다.

## 한 문장 목표

KubeEdge 기반 혼합 디바이스 환경에서 실제 서비스 데모와 디바이스 상태를 통합 가시화하고, 운영자가 dashboard와 read-only 운영 보조 요약을 통해 현재 상태, 이상 지점, 생산성 KPI 의미를 빠르게 이해할 수 있는 edge AI 운영 가시화 PoC 시스템을 구축한다.

## 짧은 표현

혼합 디바이스 edge AI 서비스 데모를 운영 관점에서 보이게 만드는 시스템.

## 시스템 이름 후보

- KubeEdge 기반 혼합 디바이스 edge AI 서비스 운영 가시화 플랫폼
- 실공장 PoC형 edge AI 운영 가시화 시스템
- 혼합 디바이스 서비스 데모 운영 가시화 PoC

## 현재 시스템이 반드시 보여줘야 하는 것

1. 어떤 edge node와 server node가 존재하는가.
2. 어떤 device가 등록되어 있는가.
3. device가 어떤 node에 붙어 있는가.
4. InfluxDB에 device별 최신 값이 최근 들어오는가.
5. DeviceStatus snapshot이 보조 상태 정보로 최신인가.
6. env/vib/temp raw telemetry와 act health liveness가 DB timestamp 기준으로 구분되어 있는가.
7. device가 어떤 service demo group에 연결되어 있는가.
8. mapper, state-aggregator, dashboard가 현재 상태를 일관되게 보여주는가.
9. dashboard에서 healthy, degraded, unavailable 판단이 어떻게 내려지는가.
10. 운영자는 문제가 생겼을 때 device, node, mapper, telemetry, dashboard 중 어디부터 봐야 하는가.
11. 이 데모 상태가 옥동 시나리오의 생산성 향상 효과와 어떻게 연결되는가.
12. Kagenti 같은 운영 보조 agent가 read-only 방식으로 상태를 요약할 수 있는가.

## 현재 범위에 포함하는 것

- KubeEdge node/device 기반 운영 상태 가시화
- Jetson, Raspberry Pi, server node가 섞인 혼합 디바이스 환경
- 사전 등록된 KubeEdge Device 관리
- MQTT telemetry / command topic 구조
- mqttvirtual mapper 기반 DeviceStatus snapshot 반영
- InfluxDB device별 latest timestamp 기반 healthy 판단
- state-aggregator API
- dashboard 운영 가시화
- device-service binding
- 서비스 데모 시나리오
- 운영 runbook
- 옥동 시나리오 생산성 KPI 설명
- read-only 운영 보조 요약 API

## 현재 범위에서 제외하는 것

다음 항목은 현재 시스템 구축 목표가 아니다.
필요하면 archive에서 과거 연구 맥락으로만 확인한다.

- 완전 자율형 workflow orchestration
- 동적 offloading 최적화
- agent-assisted planning 기반 자동 실행
- LLM/agent가 Kubernetes, Device CR, mapper, command topic을 직접 제어하는 구조
- selective replanning 논문 방향을 현재 구현 목표로 보는 것
- 과거 cost model 중심 runtime 최적화를 현재 PoC의 핵심 목표로 보는 것

## 운영 보조 agent의 위치

Kagenti 또는 유사 agent는 제어 주체가 아니라 운영 보조 계층으로 제한한다.

허용하는 역할:

- state-aggregator API 조회
- dashboard 상태 요약
- docs/runbook 기반 troubleshooting 안내
- service demo group과 KPI 의미 설명
- Kubernetes 리소스 read-only 진단 일부

허용하지 않는 역할:

- `kubectl apply/delete/rollout restart` 실행
- KubeEdge Device CR 수정
- mapper 재배포
- command topic publish
- actuator command 직접 실행
- 운영자 승인 없는 자동 복구

## 문서 정리 기준

문서가 현재 목표를 직접 설명하면 Active 문서로 둔다.
운영 중 점검과 장애 대응에 필요하면 Ops 문서로 둔다.
과거 연구, 논문 초안, legacy orchestration, selective replanning 자료는 Archive로 둔다.
중복이 있거나 현재 목표와 연결이 약한 문서는 정리 후보로 표시한다.

판단 질문:

1. 이 문서가 현재 서비스 데모 운영 가시화에 직접 필요한가?
2. 운영자가 dashboard를 해석하거나 데모를 점검하는 데 필요한가?
3. device-service 연결 구조나 DeviceStatus/telemetry 정책을 설명하는가?
4. 생산성 KPI 또는 실공장 PoC 설명에 필요한가?
5. 아니라면 과거 연구 맥락으로 archive에 남길 가치가 있는가?

## 앞으로의 구현 우선순위

1. 서비스 데모 시나리오를 명확하게 유지한다.
2. device-service binding을 backend API와 dashboard에서 일관되게 보여준다.
3. dashboard healthy 판단은 InfluxDB device별 latest timestamp를 우선 기준으로 삼고, DeviceStatus는 보조 snapshot으로 표시한다.
4. dashboard가 운영자 질문에 바로 답하도록 정보를 배치한다.
5. 운영 runbook과 troubleshooting 문서를 실제 점검 흐름 중심으로 유지한다.
6. read-only 운영 보조 요약은 dashboard를 보조하는 계층으로만 둔다.
7. 과거 workflow/offloading/replanning 자료는 현재 구축 목표와 분리한다.
