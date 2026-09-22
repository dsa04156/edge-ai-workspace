# EdgeX 장비 조회 시간 초과 복구

2026-09-16 사용자 요청으로 가상 디바이스 확장 이전 버전을 유지한 채 장비 조회 오류를 수정했다.
수정 대상은 PostgreSQL 인덱스1개다. 대시보드·엔진·Core Data 이미지를 배포하거나 센서 설정을 변경하지 않았다.

## 원인과 수정

- 등록 목록13개 조회는0.075초였으나 개별 최신 Event는 약2~5초, 일부 응답은503/잘린JSON이었다.
- `/state/devices`는 전체15초 제한을 넘겨HTTP500, Core Data는 context canceled/Content-Length 오류를 기록했다.
- [이전 조회 계획](plan-before.json)은 장비별 LATERAL 내부에서 `idx_event_origin` 역순 조회 후
  `device_info_id` 필터를 적용했다. 활성/비활성 device_info가 섞인 수백만 Event에서 넓은 범위를 읽었다.
- 기존 `(device_info_id,origin DESC)` 인덱스는 valid였지만 비용 추정상 선택되지 않았다.
- [적용 SQL](../../sql/20260916-event-device-covering-index.sql)은 `(device_info_id,origin DESC) INCLUDE(id)`를
  CONCURRENTLY로 추가했다. 원본 데이터를 삭제·변경하지 않았고 기존 인덱스도 유지했다.
- [이후 조회 계획](plan-after.json)은 새 인덱스의 `Index Only Scan`, `Index Cond: device_info_id=device_info.id`다.
- 생성9.388초, 인덱스203,849,728bytes(약194MiB), valid/ready 모두true.
  [실행 기록](index-build.json), [유효성 확인](index.json).

## 실제 확인

Core Data를 직접13개 순차 조회한 결과는 [edgex-after.json](edgex-after.json)이다.
등록 조회 포함 총0.497초, 개별 최신값13~52ms, 오류0개다. 원래의 다중 source reading을 유지했다.
대시보드 API는10초 cache TTL보다 긴11초 간격으로3회 요청했다. 실제 값은 다음과 같다.

| 회차 | HTTP | 장비 수 | 전체 응답초 |
|---|---|---|---|
| 1 | 200 | 13 | 0.757 |
| 2 | 200 | 13 | 5.904 |
| 3 | 200 | 13 | 1.873 |

[회차별 결과](dashboard-repeated.json)에 지연을 생략하지 않고 기록했다.
이는3회 기능 복구 확인이며 장기 SLO나 부하 한계 검증이 아니다.
[수집 보존](ingestion-preserved.json): 기존12개 UP 센서 모두 fresh이며 첫 회차와 마지막 회차 사이
최신 Event 시각이 증가했다. 전체13개 중 기존 DOWN 항목1개의 상태는 정상으로 바꾸지 않았다.

브라우저에서 이전 화면의 Arduino/Sense HAT와 기능 목록이 다시 표시됐다. 새 세션의 콘솔 오류0개다.
화면 증거는 저장소 `output/playwright/edgex-device-query-recovered.png`에 보관한다.
가상 디바이스 확장 화면/API는 계속 철회 상태다. runtime-operator와 aggregator의 이미지도 복원 버전을 유지한다.

## 운영 조건

새 DB에는 schema 생성 후 같은 SQL의 별도 적용이 필요하다. 재시도 시 같은 이름의 인덱스가
valid/ready이며 기대한 열 구성이 맞는지 확인한다. 실패한 CONCURRENTLY 작업의 invalid 인덱스는
자동으로 정상 인덱스로 바뀌지 않는다. 원상복구 SQL은 적용 파일의 주석을 따른다.
추가 인덱스의 저장 공간·입력 쓰기 비용이 생기며 장기 누적 데이터에서 조회 계획을 재확인해야 한다.
