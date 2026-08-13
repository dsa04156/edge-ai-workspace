# AI 서비스 등록 가이드

## 목적

대시보드는 Kubernetes Pod 이름이나 컨테이너 이미지를 보고 AI 서비스의 의미를 추측하지
않는다. Git에서 검토한 `ServiceDescriptor`를 서비스 정의의 기준으로 사용하고,
Kubernetes·EdgeX·서비스 API에서 읽은 값은 실행 상태의 관측 근거로만 결합한다.

현재 첫 등록 서비스는 `sensor-anomaly-demo`다. 정의 파일은
`edge-orch/state-aggregator/app/config/service_catalog.json`이며, 대시보드의 서비스 목록과
실행 DAG는 `GET /state/services` 응답의 descriptor를 사용해 만든다.

```text
Git ServiceDescriptor
  ├─ 서비스 정체성·설명
  ├─ Kubernetes workload identity
  ├─ EdgeX 입력 계약
  ├─ 실행 DAG 단계와 Device1/Server1 target
  └─ 읽기 전용 관측 API 경로
       ↓
state-aggregator /state/services
       ↓
서비스 목록 + 선택 서비스 실행 DAG
```

이 경로는 서비스 등록과 운영 가시화다. 동적 Workflow 실행, Kubernetes apply/delete,
자동 offloading 또는 EdgeX metadata 변경을 수행하지 않는다.

## 서비스가 무엇인지 판단하는 기준

| 질문 | 기준 |
|---|---|
| 어떤 서비스인가? | descriptor의 `service_id`, `display_name`, `description` |
| 어디에 배포되는가? | `workload.namespace`, `kind`, `name`, `selector` |
| 어떤 센서 입력을 쓰는가? | `input_contract`와 `design_contract.inputs` |
| 어떤 단계로 보이는가? | `graph.stages`와 `graph.targets` |
| 어디에서 상태를 읽는가? | `observability`의 `/state/...` 상대 경로 |
| 실제로 정상 실행 중인가? | 서비스 API의 input/model/result와 Kubernetes·Prometheus 관측 |

물리 Device/Profile과 telemetry freshness의 권위는 계속 EdgeX Core Metadata/Core Data다.
workload identity와 실행 상태는 Kubernetes/KubeEdge 관측을 사용한다. descriptor는 두
권위 소스를 대체하지 않고 연결 관계만 선언한다.

## 등록 절차

### 1. 입력·결과 계약을 먼저 확정한다

서비스를 등록하기 전에 다음 항목을 코드와 실제 endpoint 기준으로 확정한다.

- 입력 schema version
- 필수 resource와 EdgeX Device/DeviceResource binding
- 입력 freshness와 누락 처리 기준
- 모델 readiness 기준
- 결과·알림 API와 저장 위치
- processing latency, backlog, throughput metric
- 실행 workload와 기본 node/target

실제 계약이 없는 서비스는 목록에 완료 상태로 등록하지 않는다.

### 2. ServiceDescriptor를 추가한다

`service_catalog.json`의 `services` 배열에 한 항목을 추가한다. 비밀번호, token, URL
userinfo, 임의 image/command/hostPath는 넣지 않는다.

```json
{
  "service_id": "sensor-anomaly-demo",
  "display_name": "펌프·모터 진동·온도 이상감지",
  "description": "테스트베드 가속도 3축·온도 기반 기준선 서비스",
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
  "graph": {
    "topology": "linear-inference-split-v1",
    "title": "Sensor signal → AI decision",
    "stages": [
      {"stage_id": "collect", "slot": "Input", "label": "센서 수집", "kind": "source", "depends_on": []},
      {"stage_id": "align", "slot": "Alignment", "label": "전처리", "kind": "transform", "depends_on": ["collect"]},
      {"stage_id": "features", "slot": "Features", "label": "특징 추출", "kind": "features", "depends_on": ["align"]},
      {"stage_id": "inference", "slot": "Inference", "label": "AI 추론", "kind": "inference", "depends_on": ["features"]},
      {"stage_id": "store", "slot": "Result", "label": "결과 저장", "kind": "sink", "depends_on": ["inference"]}
    ],
    "targets": [
      {"target_id": "device1", "slot": "Device1", "label": "Device1", "node": "etri-dev0001-jetorn", "mode": "edge-local", "description": "Jetson · edge-local"},
      {"target_id": "server1", "slot": "Server1", "label": "Server1", "node": "etri-ser0001-cg0msb", "mode": "approval-gated", "description": "승인 기반 endpoint"}
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

실제 파일에는 서비스 설계 화면이 사용하는 versioned `design_contract`도 함께 둔다.
가중치, window 크기, 입력 binding이 바뀌면 기존 계약을 조용히 덮어쓰지 말고 새 contract
version을 만든다.

### 3. v1 DAG 계약을 지킨다

현재 자동 렌더러는 `linear-inference-split-v1`을 지원한다.

```text
Input → Alignment → Features → Inference ┬→ Device1 ┐
                                        └→ Server1 ┴→ Result
```

`Input`, `Alignment`, `Features`, `Inference`, `Result` slot은 각각 한 번 필요하고,
`Device1`, `Server1` target도 각각 한 번 필요하다. 중복 stage ID, 없는 단계 참조, cycle은
애플리케이션 시작 전에 차단된다.

다른 형태의 DAG가 필요하면 HTML을 서비스마다 복사하지 않는다. 새 versioned topology와
공용 renderer를 먼저 추가하고 descriptor가 그 topology를 선택하게 한다.

### 4. 관측 API를 연결한다

`observability`에는 state-aggregator가 제공하는 상대 `/state/...` 경로만 허용한다. 외부 URL은
SSRF와 권위 혼선을 막기 위해 거부한다. 현재 지원 adapter는 `sensor-anomaly-v1` 하나다.

| 경로 | 역할 |
|---|---|
| `state_path` | 입력 freshness, 모델 readiness, 최신 판정, 실행 target |
| `results_path` | 최근 결과와 Device1/Server1 처리 비율 |
| `alerts_path` | 설비 이상 발생·복귀 이벤트 |
| `augmentation_path` | 자원 증강 evaluator 상태·gate·지표·전환 이력 |

새 서비스가 같은 응답 계약을 구현하면 descriptor 경로 변경만으로 상세 화면을 재사용할 수
있다. 응답 구조가 다르면 state-aggregator에 새 versioned adapter와 테스트를 먼저 추가한다.
adapter가 연결되지 않은 descriptor도 목록과 DAG 정의에는 나타나지만 실행 상태는
`degraded/unavailable`로 표시한다.

### 5. 검증하고 배포한다

이미지 build, immutable digest 반영, Git push, Argo CD 동기화와 Traefik 확인은
[대시보드 배포](ops/대시보드-배포.md)를 따른다.

```bash
cd edge-orch/state-aggregator
.venv/bin/python -m pytest -q tests/test_service_catalog.py tests/test_service_demo.py
node --test tests/test_service_demo_dashboard.js
kubectl kustomize k8s >/dev/null
```

배포 뒤 다음을 확인한다.

1. `GET /state/services`에 descriptor와 `definition_source`가 보인다.
2. 서비스 목록의 이름·입력·node·model·추론 target이 실제 관측과 일치한다.
3. DAG 단계와 target label이 descriptor와 일치한다.
4. 센서 stale, model not ready, metric stale이면 정상처럼 표시되지 않는다.
5. 설비 anomaly와 자원 증강 상태가 독립적으로 표시된다.
6. Argo CD가 `Synced/Healthy`, Pod가 Ready이고 브라우저 console 오류가 없다.

## 자동화 범위와 한계

descriptor 추가만으로 자동화되는 범위:

- 서비스 목록 행 생성
- 서비스 이름·설명·입력 계약·workload identity 표시
- 표준 v1 DAG 단계와 Device1/Server1 target label 생성
- 등록 출처와 catalog version 표시
- 지원 adapter의 read-only 관측 API polling

추가 구현이나 승인이 필요한 범위:

- 새로운 응답 구조를 위한 adapter
- 새로운 DAG topology renderer
- 실제 모델/endpoint readiness 검증
- 승인 기반 server1 offloading 활성화
- retry, timeout, rollback의 운영 승인과 실환경 검증
- Kubernetes 또는 EdgeX mutation

따라서 “Pod가 생기면 AI 서비스가 자동으로 완성된다”가 아니라, “검토된 descriptor가
서비스 의미를 선언하고 실제 관측 증거가 그 상태를 채운다”가 현재 자동 생성 원칙이다.
