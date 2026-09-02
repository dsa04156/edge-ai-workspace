# Core Data 디바이스 조회 복구 패치

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
