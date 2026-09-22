# EdgeX AI 최소 E2E

> 이 문서는 단건 선행 구현 당시의 범위와 증거다. 이후 승인된 서비스별 자동 입력·전환은
> [AI 서비스 공통 운영](AI-서비스-공통-운영.md)의 실제 EdgeX 입력 절을 따른다.

2026-09-14 14:05 KST · 실제 EdgeX → Orin Nano 추론 → SQLite 저장 → API readback 1건 성공.

## 쉽게 설명하면

EdgeX에 보관된 센서 숫자를 공통 작업표로 바꾸고, Orin Nano의 Llama에 요약을 맡긴다.
완료된 작업표는 기존 서비스 실행 원장에 보관하고 API로 다시 꺼낸다. raw 센서 숫자는
보정된 온도나 이상 판정이 아니다. Llama 출력은 연결 시험용 요약이다.

## 기존 구조와 재사용

- EdgeX Device 조회: `state-aggregator/app/edgex.py`의 `get_devices()` → Core Metadata
  `/api/v3/device/all`. Profile: `/api/v3/deviceprofile/name/{name}`. 최신 Event:
  `get_latest_event()` → Core Data `/api/v3/event/device/name/{name}?offset=0&limit=1`.
  기존 flatten/typed-value 검증을 재사용한다.
- state-aggregator는 FastAPI router를 조합하고 `common_runtime.py`에서 Runtime Operator의
  `/services`를 운영 projection으로 제공한다. 이번에는 대시보드 쓰기 API를 추가하지 않는다.
- sensor-anomaly-demo는 Local Data → 정렬 → 통계 기준선 → 서비스 소유 SQLite 경로를 유지한다.
  `InferenceRequest/Response`는 sensor 전용이며 새 모델 공통 계약으로 덮어쓰지 않는다.
- Resource Profile은 Kubernetes requests/limits와 Prometheus CPU/RAM 실측을 분리한다.
  Runtime Recommendation의 관측·추천·승인과 공통 RuntimeService placement가 존재한다.
  기존 8-token 성능 수치는 새로운 센서 입력의 자격으로 사용하지 않는다.
- `qualification/llama-offloading/worker.py`의 기존 `/generate`를 재사용한다.
  worker 입력은 `request_id/prompt/max_tokens`, 출력은 `node_id/model/model_digest/response`,
  `queue_wait_ms/inference_ms/actual_e2e_ms/eval_count`다. qualification 코드를 수정하지 않는다.
- 결과 저장은 기존 Runtime Operator `Journal`의 PVC `/data/runtime.sqlite3`,
  `(service UID, request ID)` 키를 그대로 사용한다. 새 DB·EdgeX 내부 schema 수정은 없다.
- Nano는 `etri-dev0001-jetorn`, AGX는 `etri-dev0005-jetagx`, Spark는 `etri-ser0003-cg0ms0`다.
  node/Pod/이미지 검증과 resident runtime 수명주기는 Kubernetes 공통 Runtime Operator가 소유한다.

## API와 설정

기존 내부 API를 확장한다. 별도 `/api/ai-services/...` 별칭은 만들지 않는다.

- `POST /services/llama-inference/invoke`, 필수 header `X-Request-ID`와 body ID 일치.
- `GET /services/llama-inference/requests/{request_id}`: 저장 state/status/result 조회.
- 같은 ID·같은 payload는 결과 재조회, 다른 payload는 409. 재시작/응답 유실은 `unknown`이며
  자동 재전송하지 않는다. worker 응답 검증 실패도 성공으로 저장하지 않는다.

`examples/llama-three-tier/common-ai.json`은 기존 RuntimeService에 적용하는 merge patch다.
`spec.commonAI`에 service, placement, resources, input, monitoring, offload를 선언한다.
`offload.enabled`는 현재 false만 유효하다. default_node는 등록된 variant여야 하며,
활성 대상이 해당 edge 노드·model digest와 다르면 실행하지 않는다. candidate_nodes는
후속 대상 선언이며 오늘 순회·활성화하지 않는다. 자원 예약의 실제 권위는 기존 variant와
Pod spec이며 commonAI.resources는 이 입력 서비스의 선언이다. monitoring은 기존 worker
metrics/Prometheus와 공통 결과 latency를 연결하는 선언이며 새 exporter 설치를 뜻하지 않는다.

공통 계약은 `schema_version=edgeai.execution/v1`이다. 요청에는 `request_id/service_id`,
`source.type/device_id/event_id/profile_id/origin_ns`, timezone 포함 `timestamp`,
`input.type`(sensor/text), `input.data`를 담는다. origin_ns는 문자열로 보존한다.
센서 데이터는 `measurements: [{name,value,unit}]`이며 EdgeX 원본 JSON은 worker에 전달하지 않는다.
`ai_input.py`는 단위·유한 숫자·Device 상태·identity와 120초 freshness를 확인한다.

공통 결과에는 원 요청 source/input/input_timestamp, model name/version(digest),
`result.status/output/reason`, `execution.node/location/offloaded/runtime_target/pod_uid`,
`performance.queue_ms/inference_ms/total_ms`, 완료 `timestamp`, 원 worker 결과가 저장된다.
실행 불명은 `unknown`과 null 미측정값으로 남긴다. 저장된 node는 요청자가 지정한 임의 값이
아니라 Kubernetes 검증 target과 worker 응답이 일치한 값이다.

queue_ms는 gateway admission 대기와 worker queue 합, inference_ms는 worker의 Ollama
호출 구간, total_ms는 gateway 접수부터 결과 생성 직전까지다. SQLite commit과 네트워크
응답 전달 시간은 total_ms 밖이며 E2E 증거의 client_roundtrip_ms가 저장 후 응답까지 포함한다.
원본 관측 시각부터의 데이터 나이는 추론 latency에 섞지 않는다.

## 기존 API 사용

이미 저장된 결과는 기존 조회 API로 가져온다. 조회를 위해 센서 재수집이나 추론 재실행은
필요하지 않다. 이번에 검증한 결과의 경로는 다음과 같다.

```http
GET /services/llama-inference/requests/req-bb5aa2498d894c3a9238d4f395755a7d
```

신규 추론이 필요한 소비자는 기존 `EdgeXClient`로 데이터를 읽고 `ai_input.common_ai_request()`로
변환한 요청을 기존 `POST /services/{name}/invoke`에 보낸다. 이 연결 모듈과 공통 규격·저장
코드는 유지한다. 실제 1건 검증에 사용했던 별도 단건 실행 CLI는 사용자 요청에 따라 제거했다.
아래의 원본·요청·결과·readback 증거는 당시 실제 실행 기록으로 보존한다.

## 후속 offload 연결 위치

`common_ai.check_target()`와 `placement.default_node/candidate_nodes`가 신규 요청 대상 선택 경계다.
기존 Operator의 READY 확인·inflight drain·resident activate/deactivate를 연결할 수 있다.
오늘 common 요청은 기존 8-token latency qualification 표본에 넣지 않는다. 다음 단계에서는
새 입력 크기·동시성에 맞는 별도 부하/지연 profile과 server 준비/전환/복귀 검증이 필요하다.
공통 schema는 그대로 유지하고 target 선택과 `execution.offloaded/location` 기록을 확장한다.
이번 코드에서 false를 true로 바꾸는 것만으로 자동 offload를 활성화할 수 없다.

## 실제 실행 결과와 증거

[검증 결과](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/e2e-01/verified.json),
[원본 Event/Reading](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/e2e-01/edgex-event.json),
[공통 요청](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/e2e-01/request.json),
[공통 결과](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/e2e-01/response.json),
[API readback](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/e2e-01/readback.json),
[SQLite 읽기 전용 대조](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/persistent-readback.json)를 보관했다.

| 항목 | 실제 측정 |
|---|---|
| request_id | `req-bb5aa2498d894c3a9238d4f395755a7d` |
| EdgeX Event | `a754e21f-bc36-4e82-9b20-6a6b748c8805` |
| Device / resource | `virtual-temperature-001 / temperature_raw` |
| 원본 입력 | `344 raw`, `1789362358375121200` ns |
| 실행 node | `etri-dev0001-jetorn` (Orin Nano) |
| 모델 | `llama3.2:1b-instruct-q8_0` |
| 모델 version/digest | `baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878` |
| 원문 출력 | `The temperature reading is 344 degrees raw.` |
| queue / inference | `4.500 / 465.859 ms` |
| gateway total / client 저장 후 응답 | `496.566 / 511.067 ms` |
| 실행 상태 / offloaded | `success / false` |
| API / SQLite 대조 | HTTP 200, 동일 결과, 기존 PVC 원장 행 일치 |

**출력 품질 한계:** 모델이 원본에 없는 `degrees`라는 단어를 덧붙였다. 단위는 계속
`raw`이며 섭씨·화씨로 변환한 값이 아니다. 실행 성공은 추론·영속 저장·추적 성공을 뜻하고,
문장의 의미적 정확도나 현장 AI 판정의 합격을 뜻하지 않는다. 원문을 수정해서 성공 증거로
바꾸지 않았다. 추후 단위/출력 schema 검증 또는 제공 모델 인수가 필요하다.

[Nano runtime 증거](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/nano-runtime.json)는
동일 model digest, inference_ready와 GPU resident 메모리 1,413,952,307 bytes를 확인한다.
GPU resident bytes는 모델 로딩 관측이며 이 1건의 전용 GPU utilization 측정은 아니다.
[변경 전후 대조](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/verification-summary.json)에서
EdgeX·Llama Pod UID가 모두 유지됐고, RuntimeService는 commonAI 외 기존 spec이 동일하다.
기존 센서·물리 디바이스 workload는 수정하지 않았다.

## 배포·회귀 검증

공통 Operator 이미지 `sha256:c518ea3d654c6e56a291359bd093dcf1c156a4eb03d6f8cf8710ace8105190d7`를
배포했고 rollout Ready, 실제 코드 SHA-256과 API 응답을 검증했다. 이번 image는 당시 운영
`e7af71fa...`에 변경 모듈 4개만 덧씌웠다. 운영 중인 controller.py는 다른 worktree의
`11232619`에 있는 최신 idle-return 구현이며 현재 작업 checkout `d6f40257`보다 새롭다.
그 동작을 덮어쓰지 않았다. [이미지·소스 기록](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/image.json)과
[정확한 overlay 빌드 스크립트](../edge-orch/runtime-operator/results/2026-09-14-edgex-common-ai/release-overlay.py)를 남긴다.
다음 전체 이미지 빌드 전 해당 controller 변경을 작업 branch에 통합해야 하며,
이번 배포를 예전 checkout 전체를 다시 올리는 방식으로 재현하면 안 된다.

- Runtime Operator 전체 자동시험: **84 passed** (기존 및 신규 계약 포함).
- 운영 controller와 이번 변경을 조합한 별도 복사본: **84 passed**.
- EdgeX reader와 새 입력 adapter: **11 passed**.
- CRD generated-schema 일치, Kubernetes server dry-run, 배포 후 관련 manifest 검사 통과.
- 실제 runtime 결과는 위 E2E 1건이며 mock 기반 테스트 횟수와 합산하지 않는다.

## 변경 파일

- `runtime-operator/runtime_operator/common_ai.py`: 공통 계약·Llama adapter·응답 검증.
- `runtime-operator/runtime_operator/api.py`, `journal.py`, `contract.py`: 기존 API·원장·RuntimeService 확장.
- `runtime-operator/k8s/crd.yaml`, `operator.yaml`: 생성 schema·운영 image digest.
- `runtime-operator/examples/llama-three-tier/common-ai.json`: opt-in service 설정 merge patch.
- `state-aggregator/app/ai_input.py`: 기존 EdgeX typed reader 결과의 공통 입력 변환.
- `runtime-operator/tests/test_common_ai.py`, `state-aggregator/tests/test_ai_input.py`: 자동시험.
- 이 문서와 프로젝트 범위·저장소 구조·단계별 추진계획: 승인 범위와 검증 경계.
- `runtime-operator/results/2026-09-14-edgex-common-ai/`: 원본·요청·결과·readback·배포 증거.

위 구현 경로는 저장소 `edge-orch/` 기준이다. 대시보드 버튼은 추가하지 않았으며
결과 조회는 위의 기존 내부 API를 사용한다. 기존 원장은 단일 writer·PVC SQLite이며
HA·무한 보관이나 대용량 운영 retention을 새로 보장하지 않는다.
