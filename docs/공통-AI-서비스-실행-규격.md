# 공통 AI 서비스 실행 규격

> 기준일: 2026-09-11 · 규격 문서 v1 · 현재 checkout의 코드·manifest 기준.
> 이 문서는 서비스 인수·등록 시 확인할 공통 계약을 정한다. 새 범용 실행 API나 자동
> 오프로딩을 구현·활성화한 기록은 아니다. 현장 모델·입력·SLO의 미확정 값은 아래에 남긴다.

원격 최신 구현에는 `edge-orch/runtime-operator/`의 공통 `RuntimeService` 제어기가 있다.
이 규격은 센서 데이터·업무 모델의 인수 기준을 해당 실행 계약과 연결한다.
실행 변형·readiness·gateway·배치 정책은 [공통 서비스 Kubernetes 오케스트레이션](공통-서비스-Kubernetes-오케스트레이션.md),
현재 Llama의 추천·승인·복귀 범위는 [AI 서비스 증강 승인](AI-서비스-증강-승인.md)을 따른다.
이하 센서 전용 API와 과거 고정 Llama 시험값을 현재 공통 제어기의 API·정책으로 대체 해석하지 않는다.

## 쉽게 설명하면

AI 서비스를 장비에 맡기는 작업으로 보면, 입력은 작업 재료이고 모델은 작업 방법이다.
실행 장비와 자원은 작업 공간이며 출력은 결과 기록이다. 다른 장비에 일을 넘길 때는
그 장비가 빠른지만 보지 않고, 재료를 보내고 준비하는 시간까지 합쳐야 한다.
그래서 같은 입력·모델·부하에서 끝까지 걸린 시간과 실패 여부를 비교한다.

## 이번에 정한 공통 기준

| 항목 | 공통 기준 | 서비스별로 채워야 할 값 |
|---|---|---|
| 입력·출력 | 버전이 있는 JSON 계약, 원본 시각·식별자·단위·품질 보존, 결과와 실행 실패 분리 | 필수 signal, window, 출력 label·score 의미, 결과 저장 계약 |
| 모델 | 제공받은 모델과 전처리·후처리 버전을 고정하고 장비별 실제 실행을 검증 | 모델 파일·digest, backend, 정밀도, 상태 유지 여부 |
| 장비·자원 | 정확한 node·workload·architecture와 CPU/RAM/가속기/저장소 요구를 선언 | requests/limits, peak 실측, 동시성·지속 처리율 |
| EdgeX 연결 | Device/Profile/resource binding을 통해 읽기 전용 입력을 소비 | 물리 source와 등록 Device 관계, Local Data 또는 Core Data 소비 경로 |
| 오프로딩 | 입력·모델·대상 자격을 먼저 확인하고 지연·대기열·처리율·자원·전송·준비 비용을 함께 판단 | SLO, 진입·복귀 임계값, dwell/cooldown, 실패 대응·검증 근거 |

지표의 **의미와 필수 항목**은 공통으로 고정한다. 수치 임계값은 서비스와 모델·장비 조합별
시험 후 동결한다. 센서 기준선의 수치나 고정 8토큰 Llama 시험값을 옥동 서비스 전체에
공통 적용하지 않는다.

## 1. 입력·출력 형식

### 1.1 데이터 입력과 추론 요청을 구분한다

EdgeX Event/Reading은 수집 데이터이고, AI 입력은 이를 정렬·정규화한 분석 단위다.
원격 추론 요청은 그 분석 단위를 실행하는 API 계약이다. 세 형식을 같은 JSON으로 간주하지 않는다.

| 경계 | 현재 계약과 권위 구현 | 필수 의미 |
|---|---|---|
| 펌프·모터 데이터 | `okdong.pump-motor.telemetry/v1`, [contracts.py](../edge-orch/sensor-anomaly-demo/app/contracts.py) | `eventId`, `sourceType`, `deviceId`, `assetId`, `observedAt`, 가속도 X/Y/Z·온도 |
| 생산품질 데이터 | `okdong.production-quality.telemetry/v1`, 같은 파일 | `eventId`, `sourceType`, `lineId`, `observedAt`, `production.productionId`, 비어 있지 않은 `processValues` |
| 센서 원격 추론 | `InferenceRequest` / `InferenceResponse`, [models.py](../edge-orch/sensor-anomaly-demo/app/models.py) | 서비스·요청·모델 식별, `inputContract`, 정렬된 `frame`과 `temperature` |
| 신규 서비스 | 서비스 제공자가 제출하는 versioned schema와 adapter | 기존 센서 전용 `serviceId`·payload를 임의 확장하지 않고 별도 계약으로 검증 |

데이터 계약은 UTF-8 JSON을 기본으로 하고 Replay는 한 줄에 한 객체인 JSONL을 쓴다.
`observedAt`은 timezone을 포함한 원 관측 시각이다. `eventId`는 source 범위에서 유일해야 한다.
signal의 `value`는 유한 수이고 `quality`는 `good/uncertain/bad`다. 현재 schema에서 `unit`은
선택이지만, 현장 모델을 인수할 때는 단위·scale을 binding에서 명시해야 한다.
현재 Arduino의 raw 값을 임의로 m/s²나 °C로 바꾸어 부르지 않는다.

다음은 현재 데이터 schema에 맞는 **합성 예시**이며 실장비 측정값이 아니다.

```json
{
  "schemaVersion": "okdong.pump-motor.telemetry/v1",
  "eventId": "sample-001",
  "sourceType": "simulator",
  "deviceId": "example-source-001",
  "assetId": "example-pump-001",
  "observedAt": "2026-09-11T00:00:00Z",
  "signals": {
    "accelerationX": {"value": 12, "unit": "raw", "quality": "good"},
    "accelerationY": {"value": 18, "unit": "raw", "quality": "good"},
    "accelerationZ": {"value": 980, "unit": "raw", "quality": "good"},
    "temperature": {"value": 512, "unit": "raw", "quality": "good"}
  }
}
```

생산품질의 실제 PLC tag·MES column·단위·join 허용 시간은 현장 확정 대상이다.
`qualityLabel`은 사후 정답 label일 수 있으므로 온라인 추론 입력 feature에 섞지 않는다.
label 생성 시각과 학습·평가용 join 규칙은 모델 제공자가 별도로 제출한다.

### 1.2 실행 요청과 결과

현재 센서 서비스의 `POST /infer`와 `POST /api/v1/inference`는 같은 계약을 사용한다.
입력의 X/Y/Z 값과 온도 sample을 전달하며, 현재 API를 특징 벡터 전용 API로 설명하지 않는다.

| 구분 | 현재 필드 | 해석 |
|---|---|---|
| 요청 identity | `apiVersion`, `serviceId`, `requestId`, `modelVersion` | 현재 `apiVersion=v1`, `serviceId=sensor-anomaly-demo`; 모델 version 일치 필수 |
| 요청 데이터 | `inputContract`, `frame.origin/x/y/z`, `temperature.origin/value` | `origin`은 양의 epoch nanosecond 정수, 온도 정렬 허용차 확인 |
| 요청 문맥 | `timestamp`, `sourceNode` | 현재 선택 필드; 실행 대상 node의 실제 관측값과 구분 |
| 응답 추적 | `apiVersion`, `serviceId`, `requestId`, `timestamp`, `inputContract`, `origin`, `modelVersion` | 요청과 결과를 연결하며 timestamp를 완료 시각으로 해석하지 않음 |
| 판단 결과 | `status`, `anomaly`, `score`, `componentScores` | `status=warming_up/normal/anomaly`; score는 확률이 아님 |
| 판단 근거 | `vibrationFeatures`, `temperatureFeatures`, `modelState` | warmup 여부와 실제 사용한 특징·정렬 차이 |
| 처리 시간 | `processingTimeMs`, `serverProcessingMs` | 서버 측 처리 관측; 클라이언트 전체 지연과 구분 |

현재 응답은 `status`에 모델 판단 상태를 담는다. 신규 공통 adapter는 실행 성공·실패와
업무 판단을 분리해 제공해야 한다. 예를 들어 `warming_up`·입력 결측·timeout을 정상 제품이나
정상 설비 판정으로 바꾸지 않는다. 생산품질의 출력 label·score·판정 임계값과 output schema는
모델 제공 전까지 미확정이며, 현재 `InferenceResponse`를 생산품질 API로 재사용하지 않는다.

신규 서비스의 출력 계약에는 다음 항목을 필수 인수 항목으로 둔다. 이는 **추가 구현 요구**이며
기존 모든 API가 이미 지원하는 공통 필드명이라는 뜻은 아니다.

- 입력 event 또는 window ID, 서비스·요청 ID, 입력·출력 schema version
- 실제 model/artifact 및 전·후처리 version, 실제 실행 node·workload
- 업무 결과와 단위·score 범위, `unknown`을 포함한 판정 불가 사유
- 접수·시작·완료·저장 시각, 실행 오류 코드와 재시도 가능 여부
- 결과 ID, 저장 완료 여부, retention과 알림 발생·복귀 규칙

`origin`의 nanosecond 정수는 브라우저에서 부정확해질 수 있다. 신규 adapter의 browser 경계는
정밀도를 보존하는 문자열 등 별도 versioned 표현을 정하고 검증한다. 기존 v1 숫자 필드는
이 문서만으로 변경하지 않는다.

### 1.3 중복·오류·저장

현재 센서 추론 엔진은 동일 `requestId`·동일 payload에 캐시 응답을 반환하고, 같은 ID에
다른 payload가 들어오면 충돌로 거부한다. 캐시는 메모리 최대 1,000개이므로 재시작·퇴출 뒤의
영속 중복 방지를 보장하지 않는다. [inference_api.py](../edge-orch/sensor-anomaly-demo/app/inference_api.py)가 기준이다.

현재 SQLite 결과 저장은 `origin`을 기본 키로 중복을 억제하고 알림 transition을 함께 기록한다.
이 보장은 현재 단일 서비스·source 범위다. 여러 source·모델 version을 같은 저장소에 합칠 때는
source·window·model을 포함한 키와 영속 멱등성을 먼저 구현·시험해야 한다.

오프로딩 adapter는 timeout 후 실제 실행 여부가 불명확한 요청을 `unknown`으로 보존한다.
영속 중복 방지나 결과 조회가 검증되지 않았으면 무조건 재전송하지 않는다. 센서 전용의
제한된 retry/fallback 설정을 모든 서비스의 기본값으로 복사하지 않는다.
AI 파생 결과는 서비스 소유 저장소에 두며 EdgeX PostgreSQL 내부 schema를 직접 수정하지 않는다.
현재 결과·알림·retention API는 [옥동 데이터 계약](옥동-데이터-계약.md)을 따른다.

## 2. 사용할 모델·실행 장비·필요 자원

### 2.1 서비스별 선택 상태

| 서비스 | 모델 | 실행 장비 | 현재 결정·남은 조건 |
|---|---|---|---|
| 센서 연결·운영 기준선 | `online-baseline`, `baseline-1.0.0` | `etri-dev0001-jetorn`, arm64 CPU | 기준선 유지. 현장 학습 모델이나 GPU 추론으로 설명하지 않음 |
| 센서 원격 후보 | `cuda-online-baseline`, `cuda-baseline-1.0.0` | `etri-ser0002-cgnmsb`, amd64 NVIDIA GPU | 현재 성능 자격 `rejected`, 기본 원격 전환 비활성 |
| 옥동 펌프·모터 이상감지 | 외부 제공 모델 미확정 | 입력 수집과 추론 후보를 분리해 제출 | feature·단위·window, artifact, 정확도 및 장비별 실행 검증 필요 |
| 옥동 생산품질 판별 | 외부 제공 모델 미확정 | PLC/MES 접근·모델 요구에 따라 확정 | 데이터 schema만 존재. 모델·출력 계약·장비별 자원은 미확정 |
| 플랫폼 실행 연속성 시험 | 기존 Llama 3.2 1B 고정 요청 계약 | 실제 Nano·AGX는 edge, 실제 Spark는 server | 격리 시험 기준으로 재사용. 옥동 서비스 모델로 대체하지 않음 |

장비 이름만으로 실행 가능 여부를 판단하지 않는다. 같은 서비스라도 모델 파일·정밀도·입력 크기·
동시성·runtime이 달라지면 별도 실행 프로파일을 만든다. 장비별 실측은
[Llama 장비별 GPU 성능측정](Llama-장비별-GPU-성능측정.md), 연속성 시험 계약은
[서버·엣지 반복 오프로딩](서버-엣지-반복-오프로딩.md)을 참조한다.

### 2.2 모델 제공자와 플랫폼이 함께 채울 실행 프로파일

| 묶음 | 필수 선언 | 확인 방법 |
|---|---|---|
| 모델 | model ID/version, artifact 위치·digest, format, precision, 입력 shape·최대 크기 | 파일 digest와 실제 load/inference 결과 |
| 처리 계약 | 전처리·후처리 version, window, normalization, label·threshold | 계약 fixture의 입력·기대 출력 비교 |
| 실행체 | immutable container image, runtime·의존성 version, OS/architecture, accelerator 요구 | 정확한 image·node에서 startup·readiness·추론 시험 |
| 배치 | namespace, workload kind/name/selector, 기본 node, 허용 후보 node | manifest 및 실제 Pod node readback |
| CPU·메모리 | CPU requests/limits, RAM requests/limits, 모델 load/최대 입력 peak RSS | manifest와 같은 부하의 실측을 따로 기록 |
| 가속기 | 실제 extended resource key·수량, 모델 메모리 요구·peak·해제 후 잔량 | 장치 plugin 자원과 실제 가속 추론·메모리 관측 |
| 저장소 | 모델 cache 크기, 결과 PVC·접근모드·retention·복구 범위 | 용량·재시작·결과 readback |
| 동시성·상태 | 최대 동시 요청·queue·batch, stateless/stateful, warmup·drain 방식 | 포화점과 순서·중복·상태 일관성 시험 |
| 서비스 품질 | latency 측정 경계·p95 SLO, 지속 유입률, 허용 오류·손실, input freshness | 동일 workload 반복시험과 원본 기록 |
| 책임 | 모델 제공자, 입력 mapping 담당, 운영·rollback 담당, evidence 경로 | 검토 기록과 서비스별 인수표 |

현재 통계 기준선도 학습 분포·window 상태를 유지한다. 동일한 `modelVersion`만으로 로컬과
원격의 상태·판정이 같다고 보장하지 않는다. 상태 동기화 또는 독립 warmup 시 판정 허용차를
자격시험에서 확인한다. 진행 중 모델 상태나 LLM KV cache의 이동은 별도 구현 범위다.

### 2.3 현재 checkout의 자원 선언

아래 값은 **manifest 설정**이며 최소 필요량·현재 사용량·성능 보장치가 아니다.

| 실행체 | CPU request / limit | RAM request / limit | 가속기·저장소 |
|---|---|---|---|
| 센서 edge worker | `25m / 250m` | `64Mi / 128Mi` | GPU 요청 없음, 결과 PVC `1Gi` RWO |
| 센서 Server1 후보 | `250m / 2` | `256Mi / 1Gi` | `nvidia.com/gpu: 1` request/limit, `/tmp`는 임시 저장 |

원본은 [edge workload](../edge-orch/sensor-anomaly-demo/k8s/workload.yaml),
[결과 PVC](../edge-orch/sensor-anomaly-demo/k8s/pvc.yaml),
[Server1 resources](../edge-orch/sensor-anomaly-demo/k8s/server1-observed-only/resources.yaml)다.
과거 HAMi 20%·1,024MiB 설명과 달리 현재 확인한 Server1 manifest는 `nvidia.com/gpu: 1`이다.
실제 공유 방식·할당량은 cluster plugin과 Pod readback 없이 단정하지 않는다.
모델 메모리 해제와 Pod/GPU 예약 반환은 각각 확인해야 한다.

edge manifest는 `EXECUTION_MODE=SHADOW`, execution Lease 사용, `REMOTE_INFERENCE_MODE=disabled`를
선언한다. 이 파일이나 Pod Ready만으로 지금 결과를 저장하는 ACTIVE 소유자라고 판단하지 않는다.
실제 유효 Lease와 fresh 처리·저장 관측이 필요하다. 이 문서 작성에서는 live 상태를 측정하지 않았다.

## 3. EdgeX 데이터와 서비스 연결 방식

```text
물리 source → EdgeX Device Service ┬→ 중앙 Core Data → 원시 보관·운영 freshness
                                └→ Local Data → 정렬·검증 → AI 추론 → 서비스 결과 저장
                                                             ↓
                                                   state-aggregator → 대시보드
```

### 3.1 연결 계약

물리 inventory·state·telemetry·command의 권위는 EdgeX다. KubeEdge/Kubernetes는 node와
workload를 관리한다. `arduino-001`은 물리 source ID이고, 아래 등록 Device 4개와 구분한다.
기존 Device 이름의 `virtual-`은 실제 식별자이므로 유지하지만 simulator라는 뜻으로 해석하지 않는다.

| AI 입력 역할 | EdgeX 등록 Device | resource |
|---|---|---|
| X축 | `virtual-acceleration-x-001` | `acceleration_x_raw` |
| Y축 | `virtual-acceleration-y-001` | `acceleration_y_raw` |
| Z축 | `virtual-acceleration-z-001` | `acceleration_z_raw` |
| 온도 | `virtual-temperature-001` | `temperature_raw` |

현재 source binding은 [LocalDataClient](../edge-orch/sensor-anomaly-demo/app/local_data.py)와
[Service Catalog](../edge-orch/state-aggregator/app/config/service_catalog.json)의
`design_contract.inputs`가 근거다. 신규 binding에는 물리 source, Device/Profile/Device Service,
resource·type·unit·scale, 서비스 입력 역할과 source mode를 함께 검토한다.
관측 트윈과 서비스는 N:M 연결이며 node identity와 합치지 않는다.

### 3.2 소비 경로와 입력 준비 판정

1. **같은 노드의 저지연 센서 입력:** 현재 `source_mode=local_recent`를 유지한다.
   고정 Service DNS의 `GET /api/v3/localdata/device/name/{device}/resource/name/{resource}`에서
   `from/to/limit` 범위를 읽는다. 응답 identity·type·origin 순서를 검증한다.
2. **중앙 분석·Replay:** Core Data API 또는 검증된 MessageBus consumer를 별도 서비스 계약으로
   선언한다. 현재 Local Data client의 자동 fallback으로 추가하지 않는다.
3. **영상:** 승인된 AI Pod가 RTSP를 직접 구독한다. frame을 Core Data로 운반하지 않고,
   필요 시 분석 결과 metadata만 명시적 등록 계약을 통해 전달한다.
4. **준비 판정:** Metadata Device/Profile/Device Service와 resource type 일치, fresh input,
   window·정렬 충족, model·결과 sink 준비를 각각 확인한다. UI 관측과 실행 소유권도 구분한다.

현재 센서 기본값은 0.5초 poll, 입력 stale 기준 10초, X/Y/Z 동일 `origin`, 온도 skew 최대
2초, 진동 window 20개·온도 window 10개, warmup 30개다. 현재 Local Data sample 형식에는
개별 quality 필드가 없다. 신규 현장 adapter는 원본 quality를 보존하고 `bad/uncertain` 및
결측·중복·역순·미래 시각·window 부족의 처리 정책을 제출한다. 결측을 정상값으로 채우지 않는다.

원시 수집과 결과 저장은 요청 오프로딩과 분리한다. 현재 센서 경로에서는 edge 수집·정렬·저장을
유지하고 원격 추론만 요청한다. Device Service와 원시 데이터 저장소를 함께 이동하지 않는다.
설계 화면의 binding preview는 dry-run이며 실제 연결·배포·추론 성공의 증거가 아니다.

## 4. 오프로딩 판단에 사용할 지표

### 4.1 필수 지표와 측정 경계

| 지표 | 정의·단위 | 판단에서의 역할 |
|---|---|---|
| 입력 freshness·quality | 원본 관측 시각 기준 age 초, 필수 입력 completeness·quality | 부적합 입력은 추론·전환 준비로 판정하지 않음 |
| 요청 지연 p95 | 접수→결과 수신 ms; 센서는 별도로 관측→결과 저장 age도 기록 | 서비스별 SLO 위반·개선 확인 |
| 대기열·진행 요청 | queued 수, 가장 오래 대기한 시간 ms, inflight 수 | 일시 peak와 지속 적체 구분, drain 확인 |
| 유입률·처리율 | accepted/s, 성공 완료/s, 실패·timeout/s | 실제 유입량을 감당하는지 비교 |
| CPU 압력 | Pod 사용 core와 limit 대비 비율, throttling; node 사용률 별도 | 처리 성능 저하의 원인 조사 |
| 메모리 압력 | Pod RSS/limit, OOM·restart, node available·MemoryPressure | 후보 배제·부하 원인 확인 |
| 가속기 | GPU/NPU 사용률, 모델 메모리·할당 한도·실제 backend | 가속 실행 증거 및 후보 자원 검증 |
| 네트워크 비용 | 추론 요청·결과의 bytes, 왕복 ms, 실패율; 필요 시 유효 전송률 | 로컬 대비 실제 전송 부담 계산 |
| 준비 비용 | COLD/CACHED→실제 추론 가능 ms, 모델 load/probe 시간 | 전환 이득에 준비 지연 반영 |
| 후보 지속 용량 | 고정 모델·입력·동시성에서 SLO/오류 기준을 지킨 완료/s | 전체 전환 시 전체 유입량 수용 검증 |
| 관측 신뢰성 | source, observedAt, window, sample count, valid/stale | 미관측을 0% 사용·0ms 지연으로 처리하지 않음 |
| 전환 품질 | 손실·중복·unknown, fallback, 복귀 성공·drain·메모리 해제 | 왕복 완료와 실패 원인 평가 |

전력·열은 계측 환경이 있을 때 보조 지표로 추가한다. GPU 사용률이나 메모리 감소만으로
전력 절감 수치를 산출하지 않는다. CPU·GPU 사용률 하나만으로 전환을 실행하지 않는다.

현재 센서의 `sensor_anomaly_processing_latency_p95_ms`는 [runtime.py](../edge-orch/sensor-anomaly-demo/app/runtime.py)의
**poll 처리 구간** 지연이며 요청별 E2E p95가 아니다. `backlog`는 join/alignment의 미완성 frame 수다.
[performance.py](../edge-orch/sensor-anomaly-demo/app/performance.py)는 300초 window, 최소 3개 sample,
마지막 sample 30초 이내를 `metrics_valid` 조건으로 쓴다. 3개는 표시 가능 최소값이며 성능 자격시험
표본 수가 아니다. `/metrics`의 원격 network·inference 시간은 최신값이므로 p95로 부르지 않는다.
현재 공통 gateway에는 요청별 지연·실패·대기·진행 집계가 있다. 신규 서비스 adapter는
위 표의 측정 경계와 실제 제공 지표를 대조하고, 부족한 계측만 추가해야 한다.

LLM은 TTFT와 전체 완료 지연을 각각 기록한다. `gateway_ttft_ms`와 CLI의 scheduled-arrival
TTFT는 시작점이 다르므로 직접 비교하지 않는다. tokens/s도 요청/s와 구분한다.

### 4.2 판단 순서

1. **적격성:** 입력·관측 freshness, model/artifact/전처리 호환성, exact node·Pod·runtime,
   가속기·메모리, 결과 sink와 실행 책임을 확인한다. 자격이 `pending/rejected`이면 전환 보류다.
2. **지속 압력:** 서비스 SLO 악화·대기열 증가·유입 대비 처리율 부족이 서비스별 dwell 동안
   지속되는지 확인하고 CPU·메모리·가속기 지표로 원인을 연결한다. 입력 단절은 오프로딩으로 해결하지 않는다.
3. **예상 이득:** 같은 입력·모델·부하에서 로컬 유지와 후보 전환의 완료 시간을 비교한다.
   후보 준비 중 기존 장비가 처리할 요청, 전송·queue·추론·결과 반환 비용을 포함한다.
4. **실제 준비·전환:** 승인된 실행 경로에서 후보의 실제 추론 probe 후 신규 요청만 전환한다.
   접수·진행 요청의 소유권은 보존한다. read-only recommendation은 실행 승인이 아니다.
5. **복귀·해제:** 전체 유입량이 로컬 지속 용량의 복귀 기준 아래로 충분히 유지되는지 확인하고,
   로컬 probe→신규 요청 복귀→원격 drain→모델 메모리 해제 readback 순서로 검증한다.

공통 비교식은 `gain = (L_local - L_candidate) / L_local`이다. 두 L은 같은 측정 경계·workload의
완료 지연이어야 하며 `L_local > 0`이어야 한다. 준비·queue·네트워크 비용이 이미 포함된 E2E 값에
동일 비용을 다시 더하지 않는다. 구성요소별 p95를 단순 합쳐 E2E p95로 보고하지 않는다.
후보 모델이 다르면 성능 이득 전에 업무 출력의 허용 정확도·일관성을 별도로 검증한다.

### 4.3 기존 수치의 적용 범위

| 프로파일 | 기존 기준 | 적용 제한 |
|---|---|---|
| 센서 read-only recommendation | CPU/RAM high 85%, 자원 dwell 300초, 서비스 dwell 180초; poll p95 high 4,000ms, throughput floor 0.8/s, backlog high 1 | [catalog](../edge-orch/state-aggregator/app/config/service_catalog.json)의 설정. 범용 E2E SLO나 자동 전환 조건으로 승격하지 않음 |
| 센서 recommendation 복귀 | CPU/RAM 70%, poll p95 2,500ms, throughput 1/s, backlog 0, recovery 120초, cooldown 600초, metric fresh 60초 | 소비 측 freshness 60초와 생산 측 `metrics_valid`를 함께 확인 |
| 센서 Server1 성능 자격 | 지연 p95 10% 이상 개선, 처리량 감소 5% 이내, 오류·OOM 0 | 현재 정확한 version 쌍은 `rejected`, 통과 조건 0/15 |
| 센서 승인 요청 경로 | timeout 1초, 최대 2회 시도, 연속 실패 3회 시 900초 rollback cooldown, network 기준 250ms | 기본 remote disabled. 추천 cooldown 600초와 다른 설정 |
| 과거 고정 Llama 순차 시험 | 용량 85%·5초 압력, 준비 비용 포함 예측 이득 15%, cooldown 60초; 복귀는 이전 단계 용량 60% 이하·30초 | [반복 오프로딩](서버-엣지-반복-오프로딩.md)의 시험 이력. 현재 공통 제어기의 정책값이 아님 |
| 현재 공통 RuntimeService | 검토한 `spec.variants`의 검증 용량·지연과 `spec.policy`의 부하·지연·승인·복귀 조건 | [공통 제어기 계약](공통-서비스-Kubernetes-오케스트레이션.md)과 [AI 서비스 증강 승인](AI-서비스-증강-승인.md)을 기준으로 서비스별 값을 확인 |
| 옥동 서비스 2종 | 지표·측정 경계는 위 공통 기준, 수치는 미동결 | 현장 입력 주기·허용 지연·모델별 지속 용량 시험 후 각각 확정 |

## 5. 서비스 인수·검증 완료 기준

| 인수 항목 | 담당 | 완료 증거 |
|---|---|---|
| PLC·MES·센서 mapping | 현장 데이터 담당 + 플랫폼 연동 담당 | 실제 endpoint·tag/column·단위·주기·identity·품질 시점 계약, 최초 유효 입력 |
| 모델·입출력 | 모델 제공자 | artifact digest, input/output schema, 전·후처리·label·threshold, 정상·오류 fixture |
| 장비·자원 | 플랫폼 실행 담당 | 모델×장비별 load·추론·peak 메모리·지속 용량, 정확한 image와 resource manifest |
| 결과·관측 | 서비스 담당 + 운영 담당 | 입력→결과 추적, 저장·재시작·중복·알림 검증, metric freshness |
| 오프로딩 자격 | 플랫폼 시험 담당 + 서비스 담당 | 같은 입력·부하의 로컬/후보 반복 비교, 준비 비용·SLO·오류·출력 일관성 판정 |
| 전환·복귀 | 운영 담당 | 승인 범위·rollback 책임, 원격 실패·unknown·drain·복귀·해제 readback |

시험 전 workload, 반복 횟수·표본 수, warmup/steady/cooldown 구간, SLO와 허용 오차를 동결한다.
결과에는 model/image digest, node, 자원 설정, 입력 크기·주기·동시성, 측정 경계, 원본 요청 기록과
실패·중단 회차를 남긴다. 실제 옥동 AI 모델의 정확도는 모델 제공자의 업무 성능 검증이고,
플랫폼의 실행·연결·연속성 검증과 분리해서 보고한다.

문서 v1에서 확정한 것은 공통 계약 항목, EdgeX 연결 원칙, 지표의 정의와 판단 절차다.
옥동 모델 파일·현장 mapping·output schema·장비별 자원·수치 SLO는 아직 확정되지 않았다.
등록 절차는 [AI 서비스 등록 가이드](AI-서비스-등록-가이드.md), 현재/후속 실행 경계는
[프로젝트 범위](프로젝트-범위.md), 일정·산출물은 [단계별 추진계획](단계별-추진계획.md)을 따른다.
