# AI 서비스 등록 가이드

## 먼저 답: 배포한 서비스를 대시보드가 어떻게 아는가

대시보드는 Pod 이름이나 image 이름으로 서비스 의미를 추측하지 않는다. Git에서 검토한
`ServiceDescriptor`가 workload identity, EdgeX 입력 계약, 실행 DAG와 관측 API를 선언한다.
`state-aggregator`의 `/state/services`가 이 정의와 live evidence를 결합하고, 대시보드는
공용 목록과 DAG를 자동 생성한다.

```text
Kubernetes workload + EdgeX input + ServiceDescriptor
                         ↓
                /state/services
                         ↓
              서비스 목록 + 실행 DAG
```

서비스마다 화면을 새로 만들 필요는 없다. 응답 계약이 다른 서비스만 versioned adapter와
테스트를 추가한다.

현재 등록된 서비스가 실제로 무엇을 입력받아 어떻게 판단하는지는
[펌프·모터 이상감지 서비스](펌프-모터-이상감지-서비스.md)를 먼저 확인한다.

## 등록 순서

### 1. 입출력 계약을 먼저 고정한다

- versioned input schema와 필수 resource
- 입력 freshness, window, 결측·시각 정렬 기준
- model readiness와 model version
- 결과·알림 API와 저장 위치
- processing latency, backlog, throughput metric
- workload와 기본 실행 target

현장 mapping이나 모델 계약이 없으면 `deployed`로 등록하지 않는다.

### 2. 안정적인 workload identity를 둔다

```json
{
  "namespace": "edgex-edge",
  "kind": "Deployment",
  "name": "sensor-anomaly-demo",
  "selector": {"app": "sensor-anomaly-demo"}
}
```

Pod 이름처럼 rollout마다 바뀌는 값을 사용하지 않는다.

### 3. ServiceDescriptor를 추가한다

현재 파일은 `edge-orch/state-aggregator/app/config/service_catalog.json`이다.

```json
{
  "service_id": "sensor-anomaly-demo",
  "display_name": "펌프·모터 진동·온도 이상감지",
  "category": "ai_inference",
  "lifecycle": "deployed",
  "execution_mode": "fixed",
  "workload": {
    "namespace": "edgex-edge",
    "kind": "Deployment",
    "name": "sensor-anomaly-demo",
    "selector": {"app": "sensor-anomaly-demo"}
  },
  "input_contract": {
    "authority": "EdgeX",
    "schema": "okdong.pump-motor.telemetry/v1",
    "required_resources": [
      "acceleration_x_raw",
      "acceleration_y_raw",
      "acceleration_z_raw",
      "temperature_raw"
    ]
  },
  "observability": {
    "adapter": "sensor-anomaly-v1",
    "state_path": "/state/service-demo",
    "results_path": "/state/service-demo/results?limit=12",
    "alerts_path": "/state/service-demo/alerts?limit=10",
    "augmentation_path": "/state/service-demo/augmentation"
  }
}
```

외부 URL, 비밀번호, token, URL userinfo와 임의 image/command/hostPath는 허용하지 않는다.

### 4. DAG 계약을 선언한다

현재 renderer는 `linear-inference-split-v1`을 지원한다.

```text
Input → Alignment → Features → Inference ┬→ Device1 ┐
                                        └→ Server1 ┴→ Result
```

중복 stage ID, 없는 단계 참조, cycle, 표준 slot 누락은 애플리케이션 시작 전에 차단한다.
다른 topology가 필요하면 화면을 복사하지 말고 versioned renderer를 먼저 추가한다.

### 5. 관측 adapter를 연결한다

`observability`는 같은 `state-aggregator`의 상대 `/state/...` 경로만 사용한다. adapter는
입력·모델·결과·alert·증강 상태를 공용 서비스 응답으로 변환한다. 연결되지 않은 descriptor도
목록에서 숨기지 않고 `degraded/unavailable`로 표시한다.

### 6. 검증하고 배포한다

```bash
cd edge-orch/state-aggregator
.venv/bin/python -m pytest -q tests/test_service_catalog.py tests/test_service_demo.py
node --test tests/test_service_demo_dashboard.js
kubectl kustomize k8s >/dev/null
```

배포 후 확인한다.

1. `/state/services`에 descriptor와 `definition_source`가 보인다.
2. 서비스 이름·입력·workload·node·model이 실제 관측과 일치한다.
3. DAG 단계와 target이 descriptor와 일치한다.
4. stale input, model not ready, metric stale이 정상처럼 표시되지 않는다.
5. 설비 anomaly와 자원 증강 판단이 독립적으로 표시된다.
6. Argo CD `Synced/Healthy`, Pod Ready, Traefik HTTP 200과 브라우저 오류 0을 확인한다.

이미지 build, immutable digest, Git push와 Traefik 검증은
[대시보드 배포](ops/대시보드-배포.md)를 따른다.

## 자동화 경계

descriptor가 자동화하는 것은 목록·DAG·read-only 관측 연결이다. Kubernetes workload 생성,
EdgeX metadata 변경, command 실행, migration과 offloading은 자동 실행하지 않는다.
