# Core Data 디바이스 조회 복구 패치

## 2026-09-16 운영 DB 인덱스 보완

위치별 최신 Event를 조회하는 기존 SQL에서도 PostgreSQL이 전체 `origin` 인덱스를 선택해
장비별 필터를 나중에 적용하는 재발을 확인했다. 13개 장비의 최신값 조회가 대시보드의
15초 제한을 초과했다. 기존 복합 인덱스는 유효했지만 조회 계획에서 사용되지 않았다.

`sql/20260916-event-device-covering-index.sql`은 `(device_info_id, origin DESC)`에
응답에 필요한 `id`까지 보관하는 인덱스를 추가한다. 적용 후 `Index Only Scan`과 장비 ID
조건을 확인했다. 데이터·서비스 이미지·대시보드 화면·시간 제한은 변경하지 않았다.

운영 DB 유지보수 담당자가 기존 `edgex-system/edgex-postgres`에서 수행하는 1회 보완이다.
새 DB를 구성하면 EdgeX schema 생성 후 이 SQL을 별도로 적용한다. Pod 재시작마다 실행하거나
Kustomize 동기화만으로 적용된 것으로 간주하지 않는다. 사용자 승인 범위에서 다음과 같이 실행한다.

```bash
rtk proxy kubectl -n edgex-system exec -i edgex-postgres-0 -c postgres -- \
  sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d edgex_db' \
  < edgex/core-data/sql/20260916-event-device-covering-index.sql
```

트랜잭션 밖에서 `CONCURRENTLY`로 실행한다. 같은 이름이 이미 있으면 정의와
`pg_index.indisvalid/indisready`를 확인한다. 중단된 invalid 인덱스를 정상 적용으로 해석하지 않는다.
완료 후 조회 계획, API 응답과 최신 Event 시각 증가를 확인한다. 철회가 필요한 경우에만
SQL 주석의 `DROP INDEX CONCURRENTLY`를 실행한다. 기존 인덱스는 유지했다.
실측·회귀 검증은 [복구 기록](results/2026-09-16-device-query-recovery/README.md)을 따른다.

## 아주 쉽게 설명하면

기존 Core Data는 오래 멈춘 센서의 최신 데이터 하나를 찾으면서 전체 이벤트를 최신순으로
훑었다. 이벤트가 약 1,200만 건 쌓인 현재 DB에서는 이 작업이 요청 제한시간 5초보다 오래
걸린다.

더 큰 문제는 이벤트 목록을 읽는 DB 연결을 놓지 않은 상태에서 각 이벤트의 Reading을
읽을 새 연결을 요청했다는 점이다. 동시에 네 요청이 들어오면 연결 네 개를 모두 붙든 채
서로 새 연결을 기다릴 수 있고, 이때 신규 센서 데이터 저장도 함께 멈춘다.

이 패치는 두 가지만 바꾼다.

1. 디바이스를 먼저 고른 뒤 기존 `(device_info_id, origin DESC)` 인덱스로 그 디바이스의
   최근 이벤트만 읽는다.
2. 이벤트 목록을 모두 읽고 첫 DB 연결을 반납한 뒤 Reading을 읽는다.

하트비트 주기, 물리 디바이스 상태 정책, EdgeX Device Service 데이터 계약은 바꾸지 않는다.

## 기준 소스

- EdgeX Foundry `edgex-go` tag: `v4.0.2`
- exact commit: `2526184332b489189495cbaa1266ec9db759a3df`
- upstream license: Apache-2.0

`Dockerfile`은 위 커밋을 checkout하고
`patches/0001-core-data-device-query-pool-deadlock.patch`를 적용한 뒤 PostgreSQL 패키지
테스트와 Core Data 빌드를 수행한다.

## 검증 기준

- 패치가 exact upstream 소스에 `git apply --check`로 적용된다.
- `go test ./internal/pkg/infrastructure/postgres -count=1`이 통과한다.
- 오래 멈춘 Sense HAT와 현재 수집 중인 Arduino의 latest Event API가 모두 HTTP 200이다.
- 네 개 이상의 동시 latest Event 요청 뒤에도 신규 Event가 계속 저장된다.
- 배포 manifest는 registry가 반환한 amd64 이미지 digest를 고정한다.
