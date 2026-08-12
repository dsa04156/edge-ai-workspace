# 옥동 생산성 KPI

## 목적

KPI는 모델 정확도만 나열하지 않고, 데이터가 서비스 결과와 운영 조치로 이어졌는지 측정한다.

## 1. 생산품질 판별 KPI

| KPI | 정의 | 수집 위치 |
|---|---|---|
| 생산 건 coverage | MES 생산 건 중 센서 window가 연결된 비율 | MES + Event metadata |
| 판정 latency | 마지막 입력 Event부터 결과 저장까지 시간 | service result |
| unknown rate | 입력 결측·stale로 판정하지 못한 비율 | service result |
| defect detection | 불량 검출 precision/recall | 품질 라벨 + 결과 |
| 재검사 감소 | AI 판정으로 수동 확인이 줄어든 건수 | MES/운영 기록 |

## 2. 펌프·모터 이상감지 KPI

| KPI | 정의 |
|---|---|
| telemetry coverage | 필요한 진동·전류·온도 resource의 fresh 비율 |
| detection lead time | 임계 이상부터 실제 점검까지 선행 시간 |
| false alarm rate | 정상 구간을 이상으로 표시한 비율 |
| missed anomaly | 라벨된 이상을 놓친 비율 |
| maintenance response | 알림부터 점검·조치까지 시간 |
| unplanned stop avoidance | 이상 조기 감지로 예방한 비가동 시간 |

## 3. 플랫폼 KPI

| KPI | 정의 |
|---|---|
| Event delivery success | Core Data persisted ACK를 받은 Event 비율 |
| outbox recovery | 장애 중 저장된 Event가 복구 후 재전송된 비율 |
| duplicate rate | replay 후 중복 결과가 발생한 비율 |
| data loss | 원인별 유실 건수. 목표는 0건 |
| service availability | AI container readiness와 결과 성공 비율 |
| operator focus count | degraded/unavailable Device 수 |

`device_telemetry_ratio`는 설정된 telemetry 대상 비율이지 최신성 비율이 아니다. 최신성은 `core_data_freshness_ratio`와 필요한 resource별 `telemetry_freshness`로 계산한다.

## 4. 운영 가시화 KPI

- Device/Profile/Service를 찾는 데 걸리는 시간
- 장애 원인을 입력·전송·저장·모델 중 하나로 좁히는 시간
- 결과에서 원본 Event와 생산 건을 역추적하는 비율
- 장애 runbook 재현 성공률

## 5. 보고 원칙

1. live 관찰값과 목표값을 분리한다.
2. fixture·시뮬레이터 결과를 현장 성과로 합산하지 않는다.
3. 전체 Device 수와 resource/서비스 수를 같은 분모로 사용하지 않는다.
4. 모델 결과와 platform delivery 결과를 별도 지표로 보고한다.
5. KPI가 낮을 때 원본 Event, adapter 로그, outbox, gateway, result store를 역추적한다.
