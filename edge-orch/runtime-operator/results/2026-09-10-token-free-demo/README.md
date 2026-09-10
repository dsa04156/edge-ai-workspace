# 토큰 없는 데모 실측

2026-09-10 NEXUS 실제 버튼으로 시작한 4개 실행. `runs.json`은 모두 종료된 결과다.
`durable-journal.json`은 읽기 전용 SQLite 조회이며 845개 자식 요청의 완료 기록을 포함한다.
`same-id-replay.json`은 기존 단일 요청 ID 재접수 응답이다. 이후 원장에도 해당 자식 요청은 1개다.
`initial-runs.json`은 중간 관측으로 최종 결과와 구분한다.
`runtime-services.json`은 수집 시점의 관측이며 종료 결과 권위는 `runs.json`이다.
`running-images.json`은 실제 Pod UID·imageID·Ready·재시작 횟수다.

Llama 261/261, 합성 telemetry 173/173 왕복 통과. 단일 1/1. 사용자 중단 410/410 완료 후 Stopped.
중단 실행의 반환 중 1개는 종료 당시 기록이며 복귀 통과가 아니다.
접수 지연이 있었고 같은 실행 ID 확인/재접수로 중복 실행을 방지했다. 원인 미확정.
desktop.png와 mobile.png는 실행 중 화면이다. 최종 종료 결과는 runs.json을 따른다.
