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
| `GET /metrics` | processing latency, backlog, throughput Prometheus metric |
| `POST /api/v1/inference` | `inference-server` 역할에서만 여는 versioned 추론 endpoint |

## 자원 증강 실행 경계

2026-08-18의 90-run CPU·메모리·요청률 실험에서 현재
`baseline-1.0.0` → `cuda-baseline-1.0.0` 후보가 성능 승격 기준을 통과한 조건은
0/15개였다. 따라서 Server1 endpoint가 Ready여도 현재 요청은 local에 유지한다. 실험 설계와
수치는 `docs/AI-서비스-자원-증강-부하-실험.md`를 따른다.

기본 `k8s/` 배포는 `REMOTE_INFERENCE_MODE=disabled`이며 Jetson 로컬 추론만 사용한다.
`k8s/server1-observed-only`는 운영 root에 포함된 observed-only server1 후보다. 모델
readiness와 endpoint를 준비하되 요청 전환은 활성화하지 않는다. HAMi가 GPU core와 memory를 배정하고 CUDA probe가 성공한 뒤에만
readiness가 통과한다. evaluator의 `RECOMMENDED` 이후 운영자가 승인한 경우에만
`k8s-overlays/server1-approved-offload`를 별도 GitOps 변경으로 사용한다.

Jetson 운영 이미지는 `scripts/build-edge-arm64-oci.sh`, server1 이미지는
`scripts/build-server1-oci.sh`로 플랫폼과 image repository를 분리해 빌드한다. Server1은
`sensor-anomaly-demo-server1` repository를 사용하여 Argo의 Device1 image override가 GPU
이미지를 덮어쓰지 못하게 한다. 두 digest를 서로 바꾸어 사용하지 않는다.

승인 overlay는 저장소 밖에서 만든 `sensor-anomaly-augmentation-approval` Secret의
`approval-id`가 없으면 시작되지 않는다. 활성화 후 원격 호출은 1초 timeout, 동일
`requestId` 최대 2회 retry를 사용하며 3회 연속 실패하면 15분 동안 로컬 추론으로
rollback한다. 로컬 모델은 원격 추론 중에도 계속 갱신된다. 이 경로는 단일 서비스의
승인된 요청 전환이며 자동 workload 증설이나 범용 동적 offloading이 아니다.

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
