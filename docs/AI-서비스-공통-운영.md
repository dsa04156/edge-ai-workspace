# AI 서비스 공통 운영

서비스를 고르면 현재 어디서 요청을 처리하는지 보여준다. 요청이 쌓이거나 응답 지연이
지속되면 준비된 큰 실행체로 신규 요청을 보내고, 부하가 줄면 작은 실행체로 돌아온다.
서비스 부하 버튼은 선택 서비스에 시험 요청을 만들고 제거 버튼은 그 시험만 종료한다.

## 등록 계약

`platform-runtime`의 `RuntimeService`에 다음을 등록한다. 모델 종류나 서비스 이름을
UI·제어기 코드에 추가할 필요가 없다. 현재 resident 어댑터는 `llama-worker-v1`이며,
그 밖의 AI는 `http-json-v1` worker 계약을 구현한 immutable 이미지로 등록한다.

| 필드 | 책임과 의미 |
|---|---|
| `serviceKind: ai` | AI 운영 대상으로 명시한다. 합성 HTTP fixture는 `test`다. |
| `ioContract` | worker readiness가 반환하는 동일 입출력 계약 식별자 |
| `readyPath`, `requestPath` | 기본 `/ready`, `/infer`. 입력은 JSON, 응답은 해당 서비스 계약이다. |
| `variants` | 후보별 immutable image, architecture, CPU/메모리/GPU requests·limits, 노드 제약 |
| `maxInFlight`, `qualification` | 검증한 동시 처리 한도와 검증 근거 |
| `qualifiedRps`, `qualifiedP95Milliseconds` | 같은 입력 조건으로 측정한 운용점. 최대 처리 용량이라는 뜻이 아니다. |
| `policy.mode: automatic` | 지속 부하/지연에 따른 자동 이동 |
| `policy.approvalRequired: false` | 매 이동의 수동 승인을 요구하지 않는다. |
| `policy.stages` | 선택 사항. 모든 variant를 중복 없이 순서대로 나열하고 검증 요청률이 증가해야 한다. |
| `policy.latency` | p95 상한·복귀 기준·측정 창·최소 표본·지속 시간 |
| `demo.payload`, `demo.concurrency` | 서비스별 고정 시험 입력과 제한된 동시 요청 수 |

준비된 일반 worker는 GET readiness에 `ready`, `ioContract`, `inFlight`를 반환해야 한다.
부하 생성과 운영 요청은 공통 gateway를 지나야 서비스별 대기·처리·지연 측정에 포함된다.
외부에서 worker로 직접 보낸 요청의 지연이나 유입률을 gateway 실측으로 표시하지 않는다.
실행 중 학습 상태·스트림 세션·임의 프로세스 메모리 이전은 이 HTTP 추론 계약 범위가 아니다.

## 제어 흐름과 관측

브라우저 → state-aggregator 제한 API → runtime-operator → Kubernetes/등록 worker 순서다.
서비스 실행/중지는 UID·resourceVersion으로 `suspended`를 변경한다. 부하 시작/제거는
UID와 실행 ID로 시험 원장을 제어한다. 부하 중단은 queued 요청을 취소하고 이미 실행된
요청을 마무리한다. 노드 변경 뒤에도 서비스 부하는 제거할 때까지 유지된다.

자동 배치는 현재 실행체 readiness, 노드 호환성·예약 여유·조건과 후보 검증을 확인한다.
후보 준비 → 신규 요청 경로 전환 → 이전 요청 drain → 자원 반환을 순서대로 수행한다.
Pod 방식은 replica를 축소하고 resident 방식은 모델 메모리를 해제하며 GPU 예약은 유지한다.
장애 감지 시 가능한 대체 후보를 고르며 후보가 없으면 보류 사유를 표시한다. 이미 실행한
요청을 임의 재시도하지 않으며 노드 고장 시 모든 요청의 무손실 성공을 보장하지 않는다.

복귀는 저부하 유지와 후보 자격을 요구한다. 지연 정책이 있으면 충분한 성공 표본으로
낮은 지연을 확인하거나, 정상 readiness·gateway/worker 처리 0·측정 창 내 유입/완료/실패
없음·추가 무부하 유지 시간을 모두 확인한다. 새 요청·관측 공백·재시작은 대기를 초기화한다.

## 현재 연결 범위

`llama-inference`는 Nano → Orin → Spark의 실제 추론 실행 경로다. 두 HTTP 시험 서비스는
합성 응답이며 별도 목록에 둔다. 기존 센서 이상감지 서비스는 기존 실행 권한과 후보 검증을
표시하는 관측 항목이다. 공통 worker/입력 계약 연결과 후보 자격 검증을 마쳐야 같은 제어를
활성화할 수 있다. 목록에 있다는 이유만으로 자동 이동 가능하다고 표시하지 않는다.

운영 범위·책임·검증 기준은 [프로젝트 범위](프로젝트-범위.md)의 최신 AI 서비스 목록 절을 따른다.


## 2026-09-14 검증

Llama의 실제 부하 시작/제거 버튼으로 Nano → Orin → Spark → Orin → Nano 자동 왕복과
상위 모델 정리를 확인했다. 477건 전송 중472건 성공, 제거 시 대기5건 취소, 실패·미확인0건이다.
최종 operator97개, aggregator projection12개, 브라우저 로직25개 시험이 통과했다.
일반 HTTP AI의 단계 유무별 자동 증강/무요청 복귀 및 노드 장애 대체는 자동시험으로 검증했다.
최종 이미지 readiness·코드 hash·전체 시험 종료·센서 수집기 Ready는
`edge-orch/runtime-operator/results/2026-09-14-ai-operations/final-live.json`에 기록했다.
실장비 왕복 후에는 전환 직후 지표를 새 실행체 기준으로 갱신하는 수정만 추가했으며
그 변경은 회귀시험과 최종 배포 hash로 검증했다.
