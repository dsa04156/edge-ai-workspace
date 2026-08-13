# server1 승인 기반 추론 경로

이 overlay는 기본 배포에 포함되지 않는다. 자원 증강 evaluator가 `RECOMMENDED`를
출력하고 운영자가 승인한 뒤에만 별도 GitOps 변경으로 승격한다. server1
`server1-observed-only` endpoint가 먼저 배포되어 Ready여야 한다.

적용 전 `edgex-edge/sensor-anomaly-augmentation-approval` Secret의 `approval-id`
키가 반드시 있어야 한다. Secret 값은 Git에 저장하지 않는다. Secret이 없으면 edge
worker Pod가 시작되지 않아 승인 없는 원격 추론을 fail-closed한다.

승격하면 edge worker는 server1 endpoint에 1초 timeout으로 최대 2회 같은
`requestId`를 재전송한다. 3회 연속 실패하면 15분 동안 로컬 추론으로 rollback하고,
그동안에도 로컬 baseline은 계속 갱신한다. 이는 승인된 단일 서비스 경로 전환이며
자동 배치, 동적 migration 또는 범용 offloading 기능이 아니다.
