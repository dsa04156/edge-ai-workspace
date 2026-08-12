# 대시보드와 KPI 모델

## 화면의 우선순위

대시보드 첫 화면은 운영자가 “무엇이 연결됐고, 무엇을 먼저 점검하며, 2차년도 서비스 입력이 준비됐는가”를 답하도록 구성한다.

1. 등록 Device 수와 available/degraded/unavailable 수
2. Core Data fresh 비율과 최근 수신 시각
3. 서비스 데모별 입력 Device·리소스·데이터 준비 상태
4. 오류·outbox·gateway·Core Data 진단
5. Kubernetes/KubeEdge node/workload 진단

`state-aggregator`가 `/state/devices`, `/state/dashboard`, `/state/summary`를 제공하고 frontend는 이를 표시한다. EdgeX Device/Profile과 최신 Event는 화면의 기준값이며 node placement는 별도 진단 카드다.

## Device 상태 표시

| 표시 | 기준 |
|---|---|
| available | Core Metadata가 잠기지 않았고 `operatingState=UP`, 연결 상태가 정상이며 최신 Core Data Event가 fresh |
| degraded | `UNKNOWN`, Event 없음/stale, source timestamp 해석 실패 등 일부 근거 부족 |
| unavailable | `LOCKED`, `DOWN`, `disconnected` |

Explain panel에는 Profile, Device Service, protocol, 관리/운영 상태, 최신 Event 시각·age, latest readings와 판단 사유를 함께 보여준다. Kubernetes Node Ready만으로 available을 표시하지 않는다.

## 2차년도 서비스 카드

| 서비스 | 입력 예 | 화면에서 보여줄 것 |
|---|---|---|
| 생산품질 양품·불량 판별 | PLC/MES 생산 건, 공정 센서 | 입력 신선도, 생산 건 연결, 추론 결과, 알림 |
| 유압펌프·모터 이상감지 | 진동 X/Y/Z, 전류, 온도 | 샘플 수, 시간 정렬, 이상 점수, 최근 상태 |

현재 checkout에는 서비스 카드용 설계와 binding 문서가 있고, 모델 실행·자동 배포를 완료 기능으로 표시하지 않는다. workflow builder는 validation/plan preview만 제공한다.

## KPI 정의

- `registered_device_count`: Core Metadata inventory
- `available/degraded/unavailable_device_count`: EdgeX state와 Core Data freshness 결합 결과
- `core_data_freshness_ratio`: fresh 최신 Event device / 등록 Device
- `operator_focus_count`: degraded + unavailable
- 서비스 KPI: 품질 판정 정확도/불량 누락률, 이상감지 탐지율/오탐률, 추론 지연
- 운영 KPI: 수집 성공률, outbox 재전송 성공률, 장애 복구 시간

AI 모델 KPI와 물리 장비 availability KPI의 분모를 섞지 않는다. 세부 정의는 [옥동 생산성 KPI](../옥동-생산성-kpi.md)를 따른다.

## 저장소 표현

Core Data/PostgreSQL은 장기 Event·결과 저장, edge SQLite outbox는 미전송 보존, 메모리/애플리케이션 cache는 최근 화면 응답용이다. 선택적 InfluxDB resource-profile 기록은 물리 telemetry 권위가 아니며 `_start`/`_stop` query window, `_time` sample timestamp 의미를 유지한다.
