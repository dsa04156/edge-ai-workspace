# Dashboard Source Failure Isolation Design

## 배경

`state-aggregator` 대시보드는 `/state/dashboard` 한 응답에 node, EdgeX device, workflow, service resource profile을 묶는다. 현재 `_dashboard_state()`는 node를 정상 수집한 뒤 EdgeX device 조회에서 `EdgeXError`가 발생하면 전체 요청을 `500`으로 종료한다. 그 결과 `/state/nodes`는 정상이어도 브라우저는 node 상태를 표시하지 못한다.

## 목표

- EdgeX Core Metadata/Core Data 관측 실패를 device 영역에만 격리한다.
- EdgeX 실패 중에도 `/state/dashboard`는 `200`으로 node, workflow, summary, service resource profile을 반환한다.
- device 목록이 실제로 0개인 상태와 EdgeX 관측 불가 상태를 명확히 구분한다.
- 화면에 EdgeX 관측 오류를 운영 이슈로 표시하되 node 상태를 계속 렌더링한다.
- 기존 미커밋 EdgeX authority 전환 작업을 보존한다.

## 비목표

- EdgeX namespace 및 DNS 장애 자체를 복구하지 않는다.
- 마지막 성공 device 값을 캐시하거나 stale 값을 정상 데이터처럼 표시하지 않는다.
- `/state/devices`의 독립 API 오류 계약은 이번 변경에서 바꾸지 않는다.
- Kubernetes apply, rollout restart, EdgeX metadata/state mutation을 수행하지 않는다.

## 접근법 비교

1. **백엔드 partial-degraded 응답 — 채택**
   - `_dashboard_state()`가 예상 가능한 `EdgeXError`만 격리한다.
   - 모든 브라우저와 API 소비자가 동일한 장애 격리 계약을 받는다.
   - 현재 단일 fetch 구조를 유지해 변경 범위가 작다.
2. **프런트 source별 독립 fetch**
   - node 렌더링은 보호되지만, 다른 `/state/dashboard` 소비자는 여전히 전체 실패를 받는다.
   - 화면 상태 조합과 refresh 동기화가 복잡해진다.
3. **마지막 성공값 캐시**
   - 화면 연속성은 높지만 EdgeX authority의 현재 관측값과 stale cache가 섞일 수 있다.
   - 현재 PoC 상태 정책에 맞지 않아 채택하지 않는다.

## API 계약

`DashboardState`에 다음 필드를 추가한다.

```json
{
  "device_observation_error": null
}
```

- 정상 관측: `device_observation_error=null`, `devices`는 실제 EdgeX inventory다.
- EdgeX 관측 실패: `device_observation_error="EdgeX device observation unavailable: EdgeXBackendError"`, `devices=[]`다.
- `devices=[]`만으로 실제 inventory 0개라고 판단하지 않으며, 소비자는 `device_observation_error`를 먼저 확인한다.
- 내부 URL, credential, 원본 예외 문자열은 응답에 노출하지 않고 오류 종류만 표시한다.

## 백엔드 데이터 흐름

1. `service.get_nodes()`로 node snapshot을 가져온다.
2. `service.get_devices()`를 별도 `try/except EdgeXError` 경계에서 호출한다.
3. EdgeX가 실패하면 빈 device 목록과 명시적인 `device_observation_error`를 만든다.
4. workflow와 resource profile 수집은 계속 진행한다.
5. 기존 resource profile의 `httpx.HTTPError` 격리 동작은 유지한다.
6. 예상하지 못한 프로그래밍 오류는 숨기지 않고 기존처럼 실패시킨다.

## 화면 동작

- node 카드와 node KPI는 정상 데이터로 계속 렌더링한다.
- device 목록에는 일반적인 “등록 device 없음” 대신 “EdgeX device 관측 불가”를 표시한다.
- Active Alerts에 source-level high alert를 하나 추가한다.
- device 수와 availability/freshness 비율은 관측 불가 상태에서 실제 0개처럼 강조하지 않는다.
- refresh가 성공하면 별도 사용자 조작 없이 오류 표시를 제거하고 실제 device 데이터를 다시 렌더링한다.

## 테스트

- EdgeX device 조회가 `EdgeXBackendError`를 발생시키는 회귀 테스트를 먼저 추가한다.
- 테스트는 `/state/dashboard`가 `200`이고 node 데이터가 보존되며 `devices=[]`와 `device_observation_error`가 반환되는지 검증한다.
- 정상 EdgeX 응답에서는 `device_observation_error=null`인지 검증한다.
- 프런트 단위 테스트에서 관측 오류가 일반적인 빈 inventory 문구가 아니라 source 오류 문구와 alert로 표시되는지 검증한다.
- 기존 dashboard, EdgeX, API 테스트를 함께 실행해 회귀가 없는지 확인한다.

## 성공 기준

- EdgeX가 DNS/HTTP/response-contract 오류 상태여도 `/state/dashboard`는 node 데이터를 포함한 `200` 응답을 반환한다.
- EdgeX 오류가 device 영역에 명시적으로 보이고 node 영역은 계속 보인다.
- 실제 device 0개와 EdgeX 관측 실패가 API와 화면에서 구분된다.
- 기존 관련 테스트 전체가 통과한다.
