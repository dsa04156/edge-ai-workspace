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

노드별 시험 버튼은 실행 경로의 각 노드 아래에 항상 표시한다. 현재 서비스 실행 노드에서
시작할 수 있고, 부하 제거는 해당 노드 시험만 종료한다. 자동 이동하면 이전 노드 시험은
종료되며 새 실행 노드의 부하 버튼을 사용할 수 있다. 단계 미지정 HTTP AI도 동일하다.

## 실제 EdgeX 입력의 자동 운영

`examples/edgex-sensor/`는 기존 `llama-inference` 한 개를 센서 입력 계약으로 전환하는
운영 overlay다. 서비스 실행/중지와 시험 부하의 권한·원장은 기존 경로를 유지한다. `llama-three-tier`의 8-token 시험 설정과 동시에 적용하지 않는다.
첫 연결은 `virtual-temperature-001` / `etri-arduino-temperature` / `temperature_raw`다.
이 이름은 기존 EdgeX 등록 이름이며, 물리 source는 Arduino다.

별도 `edgex-ai-input` 소비자가 공통 RuntimeService의 유효한 입력 binding을 읽는다.
기존 `EdgeXClient`로 Device 상태·최신 Event·Reading을 검증하고, 새로운 Reading을
기본 5초마다 확인해 공통 gateway에 보낸다. 서비스별 요청 ID는 서비스 UID·모델·입력
binding·Event·resource·origin으로 결정한다. 재시작 후 기존 원장을 먼저 조회하며,
이미 저장된 성공·실패·unknown 요청을 새 worker에서 재실행하지 않는다.
서비스가 중지되거나 관측이 오래되면 해당 서비스의 새 입력 전송을 중단한다.

이는 **최신 관측값을 주기적으로 처리하는 경로**다. polling 사이 중간 Event 전수 수집,
지속 큐, 장애 기간의 전체 재전송은 별도 기능이다. EdgeX 수집과 원본 데이터 보관은
기존 Device Service·Core Data가 계속 담당한다. 소비자는 EdgeX에 쓰지 않는다.

### 입력에 맞는 자격과 전환

- 공통 센서 요청도 서비스 UID와 실행 revision별 유입률·대기·지연 표본에 포함한다.
- `qualifiedInputProfile`은 모델 digest·adapter·입력 profile/resource/unit/범위·prompt 버전·
  출력 token 상한의 SHA-256이다. 이전 8-token 수치로 새 64-token 입력을 자동 이동시키지 않는다.
- 첫 허용 입력은 단일 `temperature_raw`, 단위 `raw`, 값 0~1023, 생성 prompt 최대 512 bytes,
  출력 최대 64 tokens다. 범위·단위·모델 또는 측정 profile이 다르면 요청 또는 후보를 거부한다.
- 후보 노드는 명시된 resident variant와 일치해야 하며 모두 같은 입력 profile의 실측값을
  가진다. 노드별 모델 등록 이름이 달라도 명시한 alias와 동일 digest를 함께 검증한다.
- READY 확인 뒤 신규 요청만 새 노드로 전환한다. 접수 대기 요청은 새 경로를 따르고,
  이미 전송한 요청은 원래 worker에서 끝낸다. 결과에는 실제 node·edge/server 위치와
  기본 노드 대비 `offloaded`를 기록하며 원장 readback으로 확인한다.
- 저부하 센서가 계속 들어와도 복귀할 수 있다. 후보 운용점의 80% 이하 유입률, 지연 회복,
  대기 0건과 후보가 감당할 수 있는 처리 중 요청 수를 지속 확인한다. 한 개의 짧은 추론이
  관측 순간 실행 중이라는 이유만으로 저부하 대기를 초기화하지 않는다.

기존 부하 버튼은 등록된 센서 입력 **재생 시험**으로 유지한다. 실시간 소비와 같은
입력 profile·gateway를 사용하지만 별도 demo 요청 ID로 추적한다. 버튼 없이 들어오는
실제 서비스 입력만으로도 부하 조건이 충족되면 자동으로 판단한다.

### 다른 서비스 연결

일반 HTTP AI는 기존 `http-json-v1` 요청 계약과 service UID별 자동 정책을 재사용한다.
실제 소비 서비스의 요청을 공통 `/services/{name}/invoke`로 보내고 모델·입출력·노드별
성능 자격을 등록한다. 위 센서 요약 adapter를 다른 모델에 임의 적용하지 않는다.
`quality-api-demo`·`telemetry-transform-demo`는 합성 시험, `sensor-anomaly-demo`는
기존 실행 경로와 후보 자격 거부 상태를 유지한다. 옥동 품질·펌프/모터 AI 모델과
해당 실제 입력 계약은 확보 후 별도로 연결한다.

Llama의 문장 출력은 연결 검증용이다. raw를 Celsius로 잘못 표현한 응답도 있어
현장 판정·단위 변환의 정확성을 검증한 서비스로 사용하지 않는다. 실행 성공·지연 측정과
모델 출력의 의미적 정확도를 구분한다.

### 실제 입력 연결 검증 결과

센서 입력 전용 부하261/261 성공, 실제 자동 왕복 시험391건 성공·미전송3건 취소,
동일 구간 실제 EdgeX 입력64건 성공을 확인했다. 모든455건의 READY 선행과 원장
dispatch를 대조했으며 시험 부하를 제거한 뒤에도 센서 입력을 유지하며 역순 복귀했다.
현재 정책은 관측30초·최소 성공표본3개·증강p95 3,600ms/10초·복귀p95 2,400ms,
복귀조건60초·cooldown60초다. 시험 뒤 병행 진단 배포와 후속 admission_timeout2건은
별도 기록으로 구분한다. 상세 수치·출력 품질 한계·배포 버전은
[실제 입력 자동 운영 검증](../edge-orch/runtime-operator/results/2026-09-14-service-auto-input/README.md)을 따른다.
