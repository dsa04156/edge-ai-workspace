# AI 노드 부하 지속과 용량 기반 복귀 검증

기존 `agent/edgex-central-docs` 브랜치에서 구현·배포했다. 코드 커밋은 `3fb8fb18`이며 새 브랜치는 만들지 않았다.

## 적용 및 자동시험

- AI의 중복 서비스 부하 시작 버튼 제거. 노드별 시작/제거 버튼 3쌍 유지.
- 노드에서 시작한 시험은 서비스 이동 후에도 같은 UID/run ID로 지속. 제거 버튼은 현재 실행 노드에 연결.
- Llama 대기/p95 초과 10초, 복귀 조건 유지 60초, 전환 후 대기 60초. window 20초·표본 10개·p95 증강 900ms/복귀 750ms.
- 하위 후보의 검증 요청률 80% 이하 유입만 복귀 허용: Nano 1.6건/s, Orin 3.84건/s.
- Operator 109개, aggregator Python 13개, 브라우저 JS 26개 검사 통과.
- 배포 이미지 digest와 9개 변경 소스의 실제 Pod 파일 SHA-256 일치. Argo CD Synced/Healthy 확인.

## 실장비 브라우저 시험

| 시각(KST) | 관측 |
|---|---|
| 16:20:52 | Nano 부하 버튼 클릭, 동시 요청 6건 유지 |
| 16:21:29 | etri-dev0001-jetorn → etri-dev0005-jetagx, sustained_pressure |
| 16:22:35 | etri-dev0005-jetagx → etri-ser0003-cg0ms0, sustained_pressure |
| 16:25:55 | etri-ser0003-cg0ms0 → etri-dev0005-jetagx, sustained_idle_return |
| 16:27:43 | etri-dev0005-jetagx → etri-dev0001-jetorn, sustained_idle_return |

Spark 부하 제거 시각: 16:24:06. 시험 ID `71af307f214b411ab3945a6d1b49abfa`.

Spark에서 60초 cooldown이 끝난 뒤에도 같은 시험이 Running이었다. Orin·Spark의 제거 버튼이 같은 실행 ID를 유지했고, 실제 Spark 제거 클릭 후 새 요청은 늘지 않았다. 제거 이후 무부하 관측과 각 단계 60초 유지, 모델 준비와 상위 모델 해제를 거쳐 Nano로 복귀했다.

전송 1,371건 = 성공 1,364건 + 제거 시 미전송 취소 5건 + 실패 2건. 미확인 0건.
부하 중 실패 2건의 개별 gateway 응답은 최근 5개 공개 응답 관측에 남지 않아 정확한 사유를 확정하지 않았다. 전송 원장의 해당 시험 요청은 성공 응답 1,364건이다. 이번 결과는 이동·지속·제거·복귀 검증이며 무오류 처리량이나 지연 SLO 달성 근거가 아니다.

종료 상태는 Nano Serving, 대기/처리 0건, 시험 Stopped, 이전 모델 해제 완료다. 센서 Device Service 두 개는 Ready 1/1이고 기존 legacy controller 둘은 replicas 0이다.

## 화면·원시 근거

- `images.json`: 불변 이미지와 변경 파일 해시
- `verification.json`: 시험 결과·전환·최종 상태 및 검사 요약
- `observations.json`: 4초 간격 API 관측(네트워크 지연에 따라 실제 간격은 다름)
- `spark-running.png`: Spark 지속 부하와 활성 제거 버튼
- `mobile.png`: 모바일 복귀 대기, 가로 페이지 넘침 없음
- `desktop.png`: 최종 Nano 복귀 및 정책 표시, 가로 페이지 넘침 없음

브라우저 콘솔 오류/경고 0건. 브라우저 정적 파일 대체를 종료하고 실제 배포 URL에서 검증했다.
