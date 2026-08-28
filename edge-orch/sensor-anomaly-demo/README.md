# Sensor anomaly service baseline

이 서비스는 Jetson에서 EdgeX Serial Device Service의 Local Data API를 읽어 가속도 3축과
온도를 정렬하고, 현재 검증용 통계 기준선으로 펌프·모터 이상 점수를 계산한다.

현재 구현은 옥동 실장비 AI 모델이 아니다. Device1의 `online-baseline`과 Server1의
`cuda-online-baseline`을 지원하며 model backend, version과 accelerator를 구분한다.
Server1 backend는 같은 통계 기준선의 점수 계산을 CUDA에서 실행한다. 옥동 실제 모델은
`PumpModelAdapter` 계약을 구현한 뒤 별도 시험을 통과해야 한다.

## 제공 기능

- `okdong.pump-motor.telemetry/v1`, `okdong.production-quality.telemetry/v1` JSON Schema
- 실데이터 없이 Local Data v3 입력을 재현하는 JSONL simulator/replay server
- 시간 정렬, feature 추출, 모델 adapter, 결과 및 alert transition 생성
- application-owned SQLite 결과 저장과 Pod 재시작 복구
- 1Gi `local-path` RWO PVC를 사용하는 Jetson 배포
- 중앙 `state-aggregator`를 통한 상태, 결과, 알림 이력 조회
- processing p95 latency, backlog, throughput과 승인된 inference routing 상태 조회
- 선택적 server1 inference endpoint와 timeout/retry/로컬 rollback 경로

## API

| API | 용도 |
|---|---|
| `GET /api/v1/status` | 입력·모델·최신 결과 상태 |
| `GET /api/v1/results` | 영속 결과 조회와 anomaly/origin 필터 |
| `GET /api/v1/alerts` | 이상 발생·정상 복귀 transition 이력 |
| `GET /api/v1/storage` | SQLite 결과·알림 건수와 보존 설정 |
| `GET /api/v1/contracts` | 지원 입력 계약 JSON Schema |
| `GET /metrics` | processing latency, backlog, throughput, inference mode와 offload/fallback Prometheus metric |
| `POST /infer`, `POST /api/v1/inference` | `inference-server` 역할에서만 여는 동일한 idempotent 추론 endpoint; 요청 ID·model version·timestamp와 서버 처리 시간을 검증 |
| `POST /api/v1/inference-routing` | 승인 overlay의 edge worker에서만 별도 control token을 `X-Offload-Approval`로 제출해 LOCAL/REMOTE를 명시적으로 전환 |

## Lease 기반 실행 권한

`sensor-anomaly-demo` workload는 Git에 고정된 Kubernetes Lease의 holder만 production
polling·inference·SQLite 결과 저장을 수행한다. 설정 모드는 `ACTIVE`, `STANDBY`, `SHADOW`이며
실제 동작 모드는 Lease 관측 결과로 fail-closed 결정한다.

- `ACTIVE`: 현재 holder identity와 Pod identity가 정확히 일치하고 Lease 갱신 CAS가 성공한 동안만
  production 결과를 저장한다. SQLite commit 직전에도 Lease를 다시 확인한다.
- `STANDBY`: 입력 polling과 inference를 수행하지 않는다. Lease 조회 실패, 만료, holder 불일치와
  resourceVersion 충돌은 모두 이 모드로 수렴한다.
- `SHADOW`: 유효한 다른 holder가 있는 동안만 입력·모델·inference를 검증하고 결과를 메모리에만
  보관한다. production SQLite, 결과 counter와 alert side effect는 변경하지 않는다.

승인된 Execution Controller가 source에서 candidate로 Lease holder를 CAS 전환한 뒤에만
candidate가 ACTIVE가 된다. Lease는 실행 권한만 결정하며 Service/Endpoints 기반 traffic routing과
별도다. source와 candidate는 각각 replica 1, `Recreate` strategy와 서로 다른 holder identity를
사용한다.

현재 KubeEdge edge Pod에서는 `kubernetes.default` Service VIP가 routable하지 않고 예약된
`KUBERNETES_SERVICE_HOST`가 빈 값으로 덮어써진다. 따라서 Git workload 계약은 전용
`EXECUTION_KUBERNETES_API_URL`로 Lease API endpoint `192.168.0.56:6443`을 고정하며
NetworkPolicy는 해당 `/32`와 port만 허용한다.
권한은 계속 이름이 고정된 단일 Lease의 `get/update`로 제한한다.

## 자원 증강 실행 경계

2026-08-18의 90-run CPU·메모리·요청률 실험에서 현재
`baseline-1.0.0` → `cuda-baseline-1.0.0` 후보가 성능 승격 기준을 통과한 조건은
0/15개였다. 따라서 Server1 endpoint가 Ready여도 현재 요청은 local에 유지한다. 실험 설계와
수치는 `docs/AI-서비스-자원-증강-부하-실험.md`를 따른다.

기본 `k8s/` 배포는 `REMOTE_INFERENCE_MODE=disabled`이며 Jetson 로컬 추론만 사용한다.
`k8s/server1-observed-only`는 운영 root에 포함된 observed-only server1 후보다. 모델
readiness와 endpoint를 준비하되 요청 전환은 활성화하지 않는다. 현재 NVIDIA device plugin이
GPU 1개를 배정하고 CUDA probe가 성공한 뒤에만 readiness가 통과한다. evaluator의
`RECOMMENDED` 이후 운영자가 승인한 경우에만
`k8s-overlays/server1-approved-offload`를 별도 GitOps 변경으로 사용한다.

Jetson 운영 이미지는 `scripts/build-edge-arm64-oci.sh`, server1 이미지는
`scripts/build-server1-oci.sh`로 플랫폼과 image repository를 분리해 빌드한다. Server1은
`sensor-anomaly-demo-server1` repository를 사용하여 Argo의 Device1 image override가 GPU
이미지를 덮어쓰지 못하게 한다. 두 digest를 서로 바꾸어 사용하지 않는다.

승인 overlay는 저장소 밖에서 만든 `sensor-anomaly-augmentation-approval` Secret의
`approval-id`와 별도 `control-token`이 없으면 시작되지 않는다. `approval-id`는 감사용 식별자라
상태 API에 보일 수 있고, mutation credential인 `control-token`은 상태에 노출하지 않는다. Pod는
승인 overlay에서도 LOCAL로 시작하며 control token을 header로 제출한 명시적 API 호출 뒤에만
REMOTE가 된다. 원격 호출은 1초 timeout,
동일 `requestId` 최대 2회 retry를 사용하며 3회 연속 실패하거나 latency 한계를 지속 위반하면
15분 동안 로컬 추론으로 rollback한다. 성공한 REMOTE 경로에서는 local model을 먼저 실행하지
않으므로, 전환 전 local warm-up 완료가 fallback precondition이다. 이 경로는 단일 서비스의
승인된 요청 전환이며 자동 workload 증설이나 범용 동적 offloading이 아니다.

2026-08-26 격리 smoke test에서는 새 ARM64 edge image와 AMD64 server image로
LOCAL → REMOTE → server 장애 → LOCAL_FALLBACK을 확인했다. 첫 REMOTE 결과는 전환 요청 후
약 543ms 안에 관측됐고, 한 sample의 remote total 33.46ms(관측 network 33.12ms, server
processing 0.34ms), 장애 후 fallback 결과는 scale 요청 뒤 약 1.08s 안에 관측됐다. 이 smoke
server는 GPU 자격과 무관한 CPU backend로 protocol·network·fallback만 검증했으며, 기존
Server1 GPU 후보의 성능 자격 `rejected`를 변경하지 않는다. 격리 workload는 시험 후 삭제했다.

## Replay 실행

```bash
cd edge-orch/sensor-anomaly-demo
PYTHONPATH=. python3 -m app.simulator --count 120 --output /tmp/pump-replay.jsonl
REPLAY_FILE=/tmp/pump-replay.jsonl REPLAY_REBASE_TO_NOW=true \
  PYTHONPATH=. uvicorn app.replay:create_app_from_env --factory --port 59910
```

다른 터미널에서 서비스 입력을 replay server로 바꾼다.

```bash
LOCAL_DATA_BASE_URL=http://127.0.0.1:59910 \
RESULT_DB_PATH=/tmp/sensor-anomaly-demo-results.db \
PYTHONPATH=. uvicorn app.main:app --port 8080
```

```bash
curl -sS http://127.0.0.1:8080/api/v1/status
curl -sS 'http://127.0.0.1:8080/api/v1/results?limit=20'
curl -sS 'http://127.0.0.1:8080/api/v1/alerts?limit=20'
```

세부 계약과 운영 경계는
[`docs/옥동-데이터-계약.md`](../../docs/옥동-데이터-계약.md)를 따른다.

## 제한

- SQLite는 이 서비스의 파생 결과 전용이다. EdgeX Core Data의 원시 Event/Reading을
  대체하거나 직접 수정하지 않는다.
- PVC는 단일 Jetson 노드의 Pod 재시작을 견디지만 중앙 HA 결과 저장소가 아니다.
- replay server는 개발·시험 도구이며 root 운영 Kustomize에 배포하지 않는다.
- 원시 데이터 통신 단절 구간을 재전송하는 outbox는 아직 구현하지 않았다.
- `server1-observed-only` GPU 후보는 운영 root에 포함되지만 요청을 전환하지 않는다.
- `server1-approved-offload` overlay와 승인 Secret은 운영 root Kustomize에 포함되지 않는다.
