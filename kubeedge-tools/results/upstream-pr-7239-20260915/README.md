# KubeEdge PR #7239 범위 축소 — 2026-09-15

- 목표: 정상 메트릭 완료의 잘못된 오류 로그를 고치되 세션 종료·범용 완료 규약 확장을 제외한다.
- PR: https://github.com/kubeedge/kubeedge/pull/7239
- 반영 커밋: `e844485e28f2baa6cb197d6a8c1afee5933ff4d9`; 기존 두 커밋을 서명된 한 커밋으로 정리하고 원래 PR 브랜치에 반영했다. DCO SUCCESS 확인.
- 변경: 10개 파일 +471/-71 → **5개 파일 +176/-86**. 제품 코드 3개 파일 +42/-17, 테스트 2개 파일 +134/-69.
- 완료된 메트릭 응답에만 `metrics-stream-success-v1` 표시를 보낸다. CloudCore는 메트릭 연결에만 이를 해석한다. 빈 값·알 수 없는 값·터널 종료는 기존 오류 처리를 유지한다.
- 완료 통지는 기존 채널을 sync.Once로 한 번만 닫는다. 먼저 온 완료 결과를 보존하고 Serve 시작 전 통지·중복 종료가 세션 lock을 붙잡고 기다리지 않게 한다.
- 범용 JSON 완료 schema/codec, 추가 완료 채널, optional 공통 interface, Session.Close/Serve의 오류 원문 전파 확장은 최종 PR에서 제외했다.
- 새 EdgeCore+새 CloudCore에서 개선된다. 구 EdgeCore+새 CloudCore는 unknown/error, 새 EdgeCore+구 CloudCore는 payload 무시 및 기존 동작이다. HTTP 상태 코드는 변경하지 않았다.
- 검증: 원래 CloudCore 코드에서 정상 완료 오류 RED 재현, 관련 두 패키지 단위·race 검사 PASS, make lint/verify PASS, Cloud·Edge 85개 패키지 PASS. 상세 명령은 [validation.json](validation.json), 최종 코드는 [patch.diff](patch.diff).
- 한계: host-level 통합시험은 cleanup에서 `sudo pkill edgecore`를 실행하므로 이 호스트에서 미실행. 실제 클러스터 배포·혼합 버전 운영 실험·maintainer 승인·병합은 미완료다. 이 기록은 기존 v1.23.1 운영 패치의 교체나 운영 검증이 아니다.
- 저장소 구분: upstream PR은 push 완료. 이 작업의 근거·체크포인트 문서는 edge-ai-workspace 로컬 변경이며 웹 배포하지 않았다.
