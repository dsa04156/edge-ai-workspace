# 공통 서비스 Kubernetes 오케스트레이션

> 상태: 공통 Kubernetes 제어기와 NEXUS 데모 운영 중. 아래에 구성·등록·자동 전환 기준·화면 사용 순서를 정리했다. 실제 GPU 왕복 261/261과 합성 HTTP 왕복 173/173을 검증했으며 임의 AI 서비스 이전·운영 HA 완료를 뜻하지 않는다.

## 쉽게 설명하면

서비스는 해야 할 일과 필요한 장비 조건을 제출한다. 플랫폼은 현재 일을 맡을 수 있는
노드를 찾는다. 이동할 때는 새 작업자를 먼저 준비하고 새 요청을 넘긴 뒤 이전 작업자의
남은 요청이 끝나야 자원을 반납한다. Nano·Orin·Spark는 그 과정을 시험하는 장비 예시다.

## 지금 어떻게 구성해 두었나

**서비스 공급자는 실행 가능한 서비스와 조건을 등록하고, 플랫폼의 공통 Operator가 전체
노드를 살펴 배치·이동·복귀를 맡는다.** Nano·Orin·Spark를 순서대로 호출하는 코드는
플랫폼 정책에 없다. 아래 절차는 현재 구현된 HTTP JSON 서비스 기준이다.

### 구성 요소와 실제 요청 경로

```text
서비스 공급자 → 컨테이너 이미지 + 입출력·준비 상태 계약
운영자       → RuntimeService 등록 (Kubernetes API)
                         ↓
공통 Operator ← 노드 상태·예약 자원·서비스 요청 부하
       ↓ 후보 선택·배포·모델 준비 확인·경로 전환·반환
Kubernetes scheduler / kubelet / KubeEdge → 실제 Pod 실행·관리

클라이언트 → runtime-gateway 고정 주소 → 현재 준비된 실행체 → 응답
NEXUS      → 등록된 데모 입력으로 요청 + 실행 위치·전환·결과 조회
```

| 실제 구성 | 무엇을 하는가 | 확인 위치 |
|---|---|---|
| `platform-runtime/RuntimeService` | 서비스마다 실행 이미지·장비 조건·배치 정책을 보관 | `demo/services.yaml`, `demo/llama-resident.yaml` |
| `platform-runtime/runtime-operator` Deployment | 계약과 실제 상태를 반복 비교하고 필요한 동작 실행 | `runtime_operator/controller.py` |
| `platform-runtime/runtime-gateway` Service | 요청의 고정 진입점. 현재는 같은 Operator Pod의 API로 연결 | `runtime_operator/api.py` |
| 서비스별 실행체 | 새 Deployment로 실행하거나 명시적으로 연결한 기존 모델 Pod 사용 | `runtime_operator/kube.py`, `resident.py` |
| `runtime-journal` PVC | 요청 ID·결과·전환 상태·데모 실행 이력 저장 | `/data/runtime.sqlite3` |
| NEXUS `AI 서비스 → 클러스터 실행` | 서비스별 현재 위치, 준비·반환 대상, 판단 이유, 시험·결과 표시 | `state-aggregator/app/common_runtime*.py` |

오프로딩 정책 판단은 Kubernetes에 상주하는 공통 Operator가 맡고, scheduler는 선택된
조건에 맞춰 Pod를 배치한다. 운영자가 이동 스크립트를 계속 켜 놓을 필요는 없다.
gateway와 Operator는 현재 한 Pod 안에 있다. 이 구조를 이중화된 별도 gateway로
해석하지 않는다. EdgeX는 계속 물리 디바이스·센서 데이터의 권위를 맡는다.

### 서비스를 붙이는 순서

1. **공급자가 서비스 계약을 맞춘다.** 요청은 JSON object를 받고 JSON으로 응답한다.
   준비 상태 API는 모델까지 준비됐을 때 `ready: true`, 현재 처리 중 건수 `inFlight`,
   등록된 `ioContract`를 반환해야 한다. 모든 실행 변형은 같은 입출력 의미를 제공한다.
2. **운영자가 실행 변형을 등록한다.** ARM64/AMD64 이미지 digest, CPU·메모리·GPU/NPU
   요청량, 필요한 RuntimeClass와 selector, 검증된 동시 처리량을 `spec.variants`에 적는다.
   GPU라는 이름만 같다고 이미지·모델이 호환되는 것은 아니다.
3. **정책을 정한다.** `allowedRoles`는 허용할 엣지·서버 역할, `preferredRole`은 저부하 때
   선호할 역할이다. 이동·복귀 임계값과 지속 시간은 `spec.policy`에 둔다.
4. **Kubernetes에 등록한다.** 새 Pod 방식은 `demo/services.yaml`을 계약 예제로 사용한다.
   운영 서비스 이름과 공급자 이미지·입출력 계약·자원 요구량으로 수정한 뒤 검증·등록한다.
   기존 모델 Pod 인계 방식은 아래 ‘기존 runtime 연결과 모델 메모리 반환’의 운영 절차를 먼저 따른다.
5. **실제 준비 상태를 확인한다.** `Serving`과 NEXUS의 준비 상태를 확인한 뒤 요청한다.
   `Preparing`은 준비 중, `Blocked`는 후보·계약·자원 등의 이유로 진행할 수 없는 상태다.

저장소 루트에서, 검토한 파일이 `my-runtime-service.yaml`인 경우:

```bash
rtk proxy kubectl --context kubernetes-admin@kubernetes apply --dry-run=server -f my-runtime-service.yaml
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -f my-runtime-service.yaml
rtk proxy kubectl --context kubernetes-admin@kubernetes -n platform-runtime get runtimeservices
```

API server dry-run은 schema 검증이며 모델 실행 성공 검증은 아니다. 현재 등록 UI 대신
Kubernetes RBAC로 등록한다. `서비스 설계` 화면의 초안은 자동으로 배포되지 않는다.

### 어떤 기준으로 올렸다가 내리는가

먼저 전체 후보에서 **노드 정상 여부 → 역할·아키텍처·selector·RuntimeClass → 예약 가능한
CPU·메모리·가속기 → 실행 변형의 검증값**을 확인한다. 조건이 맞지 않으면 이유를 남기고
후보에서 제외한다. GPU 실사용 메모리와 Kubernetes가 이미 예약한 GPU 개수는 따로 본다.

아래는 **현재 데모에 등록한 값**이다. 플랫폼 모든 서비스에 강제로 적용하는 값은 아니다.

| 조건 | 현재 데모 값 | 판단과 다음 동작 |
|---|---|---|
| 요청 부하 증가 | `(진행 중 + 대기) / maxInFlight ≥ 0.8`가 4초 지속 | 더 큰 검증 처리 용량의 호환 후보 준비 |
| 낮은 부하 | 같은 비율이 `≤ 0.2`로 8초 지속 | 현재 부하를 받을 수 있는 선호 역할 `edge` 후보로 복귀 |
| 잦은 재이동 억제 | 전환 후 5초 | 정상 위치에서 부하에 따른 다음 이동을 바로 반복하지 않음 |
| Llama 지연 초과 | 20초 창, 성공 표본 최소 10개, p95 `> 900ms`가 4초 지속 | 더 낮은 검증 p95를 가진 적합 후보로 이동 |
| Llama 지연 회복 | p95 `≤ 700ms`와 낮은 부하가 각각 8초 유지 | 복귀 후보의 검증값까지 확인 후 엣지 복귀 |

부하 확대는 양쪽에 `qualifiedRps`가 있으면 같은 입력에서 검증한 처리율을 비교한다.
양쪽에 없으면 `maxInFlight`를 비교한다. 현재 Llama는 실제 동시성 1을 유지하고
검증된 RPS로 이동을 판단한다. 따라서 부하 비율은 CPU/GPU 사용률을 뜻하지 않는다.
지연 정책은 선택 사항이며 현재 합성 HTTP 데모에는 켜지 않았다.

적합 후보가 없으면 무조건 서버로 보내지 않고 현재 상태와 제외 이유를 보여준다.
복귀는 **처음 실행한 장비가 아니라 선호 역할의 적합한 장비**를 고르는 것이다.
실제로 합성 시험은 Tinker에서 시작해 서버를 거쳐 AGX 엣지로 돌아왔다.

### 요청을 끊지 않고 전환하는 순서

1. 기존 실행체가 요청을 처리하는 동안 새 실행체를 준비한다.
2. 새 Pod와 애플리케이션·모델이 실제로 준비됐는지 확인한다.
3. gateway가 **새 요청부터** 새 실행체로 보낸다. 진행 중인 요청은 원래 대상에 남는다.
4. 기존 실행체의 gateway 요청과 worker `inFlight`가 끝날 때까지 기다린다.
5. 새 Pod 방식은 이전 Deployment를 0 replica로 내려 예약을 반환한다.
   resident 방식은 모델을 해제하고 `CACHED`·모델 메모리 0을 확인하며 Pod와 GPU 예약은 유지한다.

준비가 실패하면 준비 중인 대상을 정리하고 기존의 정상 요청 경로를 유지한다.
이미 보낸 요청의 결과를 잃었을 때는 `unknown`으로 기록하고 자동 재실행하지 않는다.
이 방식은 계획된 요청 전환을 위한 것으로, 전체 노드가 갑자기 사라져도 진행 중인
모든 요청을 복원하거나 제어기 교체 중 접속 공백까지 없애는 방식은 아니다.

### 지금 화면에서 데모 실행하기

1. [NEXUS 클러스터 실행](http://aggregator.192.168.0.56.sslip.io/#runtime-services)을 연다.
2. 실행 가능한 서비스 행에서 **시험 요청 1건** 또는 **왕복 시험**을 누른다. 토큰 입력은 없다.
3. 왕복 시험은 고정 입력으로 최대 동시 6건, 25초 부하를 발생시킨 뒤 1초 간격의 요청으로
   최대 120초 회복을 관측한다. 총 요청은 최대 512건이다. 이동 자체는 위 정책이 판단한다.
4. 아래 `데모 실행·결과`에서 성공·실패·미확인 건수, 실행 위치 경로와 반환 중 개수를 확인한다.
   왕복은 요청이 모두 성공하고 역할 복귀와 반환 완료가 확인돼야 `검증 통과`다.
5. **새 시험 요청 중단**은 추가 시험 요청만 멈춘다. 이미 보낸 요청은 마무리하며 서비스는 계속 운영된다.

버튼은 `spec.demo`를 명시한 서비스에만 나타난다. 고정 입력을 사용하며 화면에서 임의
모델·명령·대상 노드를 넣지 않는다. 서비스당 한 시험, 전체 두 시험까지 진행하고 종료 후
10초를 기다린다. 버튼이 비활성이면 준비·반환 중인지, 관측이 오래됐는지, 시험이 이미 진행
중인지 확인한다. 접수 응답을 받지 못하면 표시된 **같은 실행 ID로 확인·재접수**를 사용한다.
결과 확인 없이 새 ID로 같은 시험을 반복 접수하지 않는다.

### 서비스 자체를 멈추거나 문제를 확인할 때

시험 중단과 서비스 중단은 다르다. 운영자가 서비스 자체를 멈추려면 해당 CR의
`spec.suspended: true`를 적용한다. 제어기가 신규 접수를 막고 기존 요청을 마친 뒤
자원을 반환하며 `Suspended`로 전환한다. 재개는 false로 바꾸고 다시 준비 완료를 기다린다.

| 화면·관측 | 확인할 것 |
|---|---|
| `Preparing` | 새 Pod 준비, 이미지·RuntimeClass·애플리케이션 readiness |
| `Blocked` / 후보 없음 | 서비스 행의 후보 제외 근거, 실제 자원 예약과 계약 조건 |
| 반환 중 대상이 남음 | 진행 요청·worker inFlight, Pod 종료 또는 모델 해제 확인 |
| `unknown` / `Interrupted` | 저장된 요청·실행 ID의 결과 확인. 제어기는 이를 임의 재실행하지 않음 |
| 현재 관측 확인 불가 | Operator/API 연결과 15초 freshness. 과거 위치를 현재 정상으로 해석하지 않음 |

요청별 자세한 결과는 공통 gateway의 `GET /services/{name}/requests/{request_id}`,
서비스별 상태는 `GET /services`로 확인한다. API 서버·전체 노드 장애 복구와 HA의 한계,
정확한 계약·실험 수치는 아래 절에 이어진다.

## 계약과 책임

| 구성 | 책임 |
|---|---|
| RuntimeService | 서비스 ID, I/O 계약 버전, immutable image별 실행 변형, readiness, CPU·메모리·가속기 요구량, 노드 조건과 배치 정책 |
| Kubernetes Node/Pod | Ready, taint, architecture, allocatable과 이미 예약된 requests의 권위 |
| 공통 제어기 | 호환 후보 선별, Deployment 생성, 준비 확인, 요청 단위 전환, drain, 자원 반환, 반복 reconcile와 상태 이력 |
| Kubernetes scheduler/kubelet | 제어기가 지정한 affinity와 resources를 만족하는 실제 Pod 배치·시작·재시작 |
| 요청 gateway | 서비스별 고정 진입점, 요청 ID 중복 방지, 대상 고정, 전환 중 기존 요청 유지 |
| EdgeX | 물리 source·디바이스·telemetry 권위. 이 제어기의 수정 대상 아님 |

노드 이름의 접두사로 역할을 추정하지 않는다. 기본 노드의 edge role label과 서비스별
selector를 읽는다. 하드웨어 이름이나 메모리 크기만으로 성능 순위를 만들지 않는다.
서로 다른 실행 변형은 같은 I/O 계약을 구현해야 하며 검토한 backend selector와
확장 자원 요청을 함께 선언한다. CUDA 모델과 ARIES NPU artifact는 자동 호환되지 않는다.

## 최초 지원 경계

첫 실행 방식은 외부 상태를 직접 이전할 필요가 없는 bounded HTTP JSON 요청이다.
같은 서비스의 모든 배포 변형은 같은 입출력 계약을 제공하고 readiness는 실제 처리 준비를
뜻해야 한다. 장시간 Job, streaming, StatefulSet·checkpoint·DB 이전은 별도 실행 adapter가
필요하며 이 계약으로 등록할 수 없다. 일반적인 AI 서비스를 무조건 무중단 이전한다고
주장하지 않는다.

Kubernetes Service는 gateway의 고정 주소를 제공한다. 요청 대상은 gateway가 요청마다
고정하므로 클라이언트 keep-alive 연결과 workload 전환을 분리한다. 준비된 대상이 없으면
명시적으로 접수를 거절한다. 접수 전 거절과 이미 전송한 요청의 결과 불명을 구분하고,
후자는 자동 재실행하지 않는다. SQLite 원장과 단일 프로세스 파일 잠금을 사용한다.
복수 제어기 HA와 네트워크 분할 중 fencing은 후속 범위다.

기본 자원 반환은 기존 Deployment를 0 replica로 내려 Kubernetes 예약도 반환하는 방식이다.
기존 runtime을 연결한 `resident` 변형은 Pod와 GPU 예약을 유지하고 모델 메모리만 반환한다.
Pod 자원 반환과 모델 메모리 반환은 다른 결과이며 아래에 별도 실측 근거를 기록한다.

## 합격 기준과 증거

1. 고정 장비 이름 없이 서로 다른 서비스의 후보 선별과 배치가 가능하다.
2. NotReady·pressure·taint·CPU/메모리/가속기 부족·아키텍처/런타임 불일치는 후보 제외 이유로 남는다.
3. 대상 Pod Ready와 서비스 readiness 확인 전에 신규 요청을 넘기지 않는다.
4. 준비 중 실패하면 기존 요청 경로를 유지한다. 전환 후 이전 요청이 끝나기 전에 이전 Pod를 내리지 않는다.
5. 부하 증가·저부하 복귀의 dwell/cooldown을 적용하고 후보가 없으면 차단 이유를 보인다.
6. 제어기 재시작 시 원장의 전송 중 요청은 결과 불명으로 복구하며 중복 전송하지 않는다.
7. 실제 Kubernetes 배치·전환·drain·자원 반환 결과와 단위시험을 별도 기록한다.

과거 [서버·엣지 반복 오프로딩](서버-엣지-반복-오프로딩.md)의 전용 제어기 결과는
이력으로 구분한다. 이 문서 하단의 210/210 실장비 결과는 공통 제어기로 새로 측정한 증거다.

## Kubernetes 근거

- [Operator 패턴](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/): 사용자 정의 리소스의 의도와 실제 상태를 제어 루프로 조정한다.
- [Pod 노드 배치](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/): affinity/selector와 실제 scheduler 역할을 분리한다.
- [Pod 종료](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination): 종료 유예만으로 application 요청 완료를 보장하지 않으므로 gateway drain을 확인한다.

## 구현과 운영 진입점

- 구현: `edge-orch/runtime-operator/runtime_operator/`의 `contract.py`, `placement.py`,
  `controller.py`, `kube.py`, `journal.py`, `api.py`. 이전 Llama 고정 순서 제어기를 호출하지 않는다.
- 배포: `edge-orch/runtime-operator/k8s/kustomization.yaml`. Argo CD가 관리하는 EdgeX·센서
  Service selector를 수정하지 않는다. 신규 RuntimeService UID가 소유한 Deployment·Service만 변경한다.
- 등록: 운영자가 검토한 `RuntimeService`를 Kubernetes RBAC로 apply한다. JSON 입력에 임의
  command, hostPath, privileged Pod spec을 넣는 경로는 없다. 데모도 장비 이름 없이
  `demo/services.yaml`의 실행 변형과 역할 정책만 사용한다.
- 조회: `kubectl -n platform-runtime get runtimeservices` 및 gateway `GET /services`.
  현재 NEXUS 등록 화면과 연계하지 않았으며 기존 서비스 설계 화면은 dry-run이다.
- 실행: `POST /services/{name}/invoke`, JSON object와 필수 `X-Request-ID`. 동일 ID·내용은
  저장 결과를 반환하고, 다른 내용은 409로 거절한다. 접수 대기 128개·본문 크기·처리
  시간 제한이 있으며 큐가 찼거나 준비된 대상이 없으면 접수 전 거절임을 표시한다.
- 결과: `GET /services/{name}/requests/{request_id}`에서 completed/dispatched/unknown을 조회한다.
- 중단: `spec.suspended: true`는 신규 접수를 막고 drain 후 0 replica로 내린다. 삭제 시에도
  finalizer가 같은 절차를 기다린다. 강제 finalizer 제거는 정상 종료 절차가 아니다.

서비스 공급자는 다음 adapter 계약을 구현한다.

```json
{"ready": true, "inFlight": 0, "ioContract": "my.service.v1"}
```

`readyPath` GET은 위 정보를 반환한다. ready는 모델 로드·실제 처리 준비까지 완료한
상태여야 한다. `inFlight`는 해당 프로세스에서 아직 끝나지 않은 모든 gateway 요청 수다.
`requestPath` POST는 JSON 입력·출력을 사용하고 `X-Request-ID`를 받는다. 모든 변형은 같은
I/O 계약을 구현해야 하며 공급자가 이를 검증한다. 플랫폼은 의미가 다른 모델 두 개를
같은 서비스로 자동 간주하지 않는다. 요청은 gateway를 통해서만 보내는 운영 계약이다.

배치 자원 검사는 allocatable에서 다른 Pod의 requests·init container·sidecar·overhead를
차감한다. 현재 revision 자신의 한 Pod 예약만 같은 namespace·service UID 확인 후
인정한다. 이는 scheduler 사전 필터이며 동시 예약 경합의 최종 판단은 Kubernetes가 한다.
Prometheus 실사용량이나 Llama 장비별 벤치마크를 이 예약량과 혼동하지 않는다.

부하 판단은 서비스별 실행 중+대기 요청 수와 검토한 변형별 `maxInFlight`를 사용한다.
고부하가 `pressureSeconds` 이상 지속되면 더 큰 검증 동시성의 호환 후보를 준비한다.
`qualifiedRps`가 양쪽 변형에 있으면 동일 입력 계약에서 검증한 처리율로 후보를 비교한다.
Llama에서는 실제 worker 동시성을 1로 유지하며 AGX 4.8 rps·Spark 6 rps 자격을 사용한다.
저부하가 `returnSeconds` 이상 지속되면 `preferredRole`의 수용 가능한 후보로 돌아간다.
같은 역할·같은 용량의 노드끼리 낮은 부하만으로 이동하지 않는다. 초기 v7은 동시 요청 수 기반이며, 후속 선택적 지연 정책은 아래 절을 따른다. 전력·가격 최적화와 일반 GPU/NPU 성능 우열 판단은 미구현이다.

## 2026-09-10 실배포 증거

두 서비스는 `quality-api-demo`와 `telemetry-transform-demo`다. 서로 다른 I/O 계약을
가진 **합성 HTTP 처리 fixture**이며 실제 품질 판별·AI 추론 서비스가 아니다.

| 시험 | 결과 | 근거 |
|---|---|---|
| 최초 부하 시험(v3) | 142/142 요청 성공, 정해진 관측 시간 안의 엣지 복귀 실패 | `results/2026-09-10-general-v3/http-round-trip.json` |
| 복귀 정책 수정 후(v5) | 134/134 요청 ID·출력 일치, edge→server→edge 관측 | `results/2026-09-10-general-v5/http-round-trip.json` |
| 최종 배포 버전 재검증(v7) | 135/135 요청 ID·출력 일치, AGX→x86 Server1→Tinker의 edge→server→edge 관측 | `results/2026-09-10-general-v7/http-round-trip.json` |
| 실제 선택 노드(v5) | Tinker Edge R→x86 Server1→AGX Orin | 고정 순서·hostname selector 없는 CR과 응답 node 값 |
| 서비스 격리 | 다른 서비스는 Tinker Edge R에서 실행 위치 유지 | 같은 원본의 isolation-before/after와 상태 snapshot |
| 반환 | 이전 revision 0 replica, 종료 Pod 없음, retiring 0; 서비스당 활성 Pod 1개 | `results/2026-09-10-general-v5/after-round-trip.json` |

위 결과 경로는 모두 `edge-orch/runtime-operator/` 기준이다. 이전 v3 실패를 지우지 않고
복귀 정책 변경의 원인으로 보존한다. 준비 전 무응답 후보를 제외하고 다른 노드에서
서비스를 준비하는 것도 실제 클러스터에서 관측했다. 노드 Ready만으로 애플리케이션
실행 가능을 선언하지 않는다.

재시작 이후에도 서비스 2개가 Serving으로 복구됐고, 이미 내려간 Tinker revision에서
완료한 요청을 동일 ID로 재요청했을 때 저장된 원래 결과를 반환했다. 최종 v7 이미지의
실제 Pod imageID와 결과는 `results/2026-09-10-general-v7/restart-replay.json`에 보관한다.
제어기 재시작 중 무중단 HTTP 접속을 검증한 결과는 아니다. 단일 gateway 교체 중에는
접속 공백이 있으며 Pod 안에서 진행 중이던 결과 불명 요청은 자동 재전송하지 않는다.

HTTP 제어기 v7 시점의 단위·배포 계약 시험 33개가 통과했다. 저장소 전체와 함께 실행한 결과는 148 통과·1 실패다.
실패는 기존 sensor-anomaly Argo CD `targetRevision`이 `agent/edgex-central-docs`인 반면
시험이 `main`을 기대하는 기존 불일치다. 원격 기준 커밋에도 같은 설정이 있음을 확인했고, 해당 manifest·시험의 의미를 이번 변경으로 수정하지 않았다. 공통 실행 제어기 시험과 문서 생성 검증은 통과했다.

## 현재 한계와 다음 연결

- 현재 클러스터 내부 ClusterIP gateway다. 외부 공개·사용자 인증·NEXUS 등록 UI는 연결 전이다.
- CPU/GPU/NPU 확장 자원과 RuntimeClass 필터를 구현했고, 아래 resident 계약으로 실제
  AGX·Spark GPU Llama 왕복을 검증했다. 공통 NPU 모델 전환은 아직 실측하지 않았다.
- 신규 Pod를 만들려면 예약 가능한 가속기가 필요하다. 기존 Llama Pod의 모델 메모리만
  비웠다고 다른 Pod가 그 GPU 예약을 얻는 것으로 보지 않는다. 기존 runtime 연결·메모리
  해제 adapter는 아래 계약으로 구현했다. 이 경우 GPU 예약은 해당 기존 Pod에 남는다.
- 현재 bounded HTTP JSON만 지원한다. streaming, 장시간 Job, checkpoint·state migration,
  API 서버·gateway·전체 노드 장애 중 무손실 및 다중 gateway HA는 검증 완료가 아니다.
- 원장은 local-path PVC에 있으므로 제어 노드의 영구 손실은 별도 복구·백업이 필요하다.
  실행 중 재시작은 결과 불명으로 기록하고 worker가 이전 요청을 끝냈는지 확인한다.
- 합성 왕복은 v5·v7에서 각각 수행한 약 70초 시나리오다. 장시간·대규모·실공장 SLA 합격으로 확대하지 않는다.

## 기존 runtime 연결과 모델 메모리 반환

`Variant.resident`는 공급자가 이미 배포한 runtime을 가리킨다. 현재 adapter는
`llama-worker-v1`이며 `resident.py`가 기존 worker의 health·metrics·activate·deactivate·
generate API를 공통 제어기 계약으로 변환한다. 대상 선택과 drain·복귀는 공통 제어기가
담당하며 Nano→Orin→Spark 같은 순차 제어기를 호출하지 않는다.

- 같은 namespace의 Service selector와 유일한 Pod, 정확한 runtime container image,
  실제 실행 node, Pod Ready, RuntimeClass와 예약량을 검증한다. 새 GPU 예약은 요구하지 않는다.
- `previousControllers`의 Deployment가 0 replica이고 해당 Pod가 완전히 사라져야 제어를
  인계한다. 다른 RuntimeService 또는 두 변형이 같은 resident Pod를 중복 선언하면 차단한다.
- 서비스의 공통 `inference` 계약은 정확한 model digest·prompt·maxTokens를 고정한다.
  현재 자격은 8토큰 조건이며 512/128 벤치마크를 자동 전용하거나 임의 입력을 허용하지 않는다.
- 모델 준비는 별도 async 작업으로 수행한다. AGX 준비에 약 23초가 걸려도 제어기의
  다른 서비스 관측·요청 처리 루프를 막지 않는다.
- 이전 gateway 요청과 worker 자체 queue·active 요청이 모두 0일 때 모델을 해제한다.
  해제 후 CACHED·model_loaded=false·model_vram_mib=0을 확인해야 retiring을 끝낸다.
- resident Pod와 GPU 예약을 scale/delete하지 않는다. 계약 버전 변경이 같은 resident를
  가리키는 경우에도 새 active 모델을 이전 revision 정리로 해제하지 않는다.

### 실장비 결과

`demo/llama-resident.yaml`로 `platform-runtime/llama-inference`를 등록했다. 기존 두
전용 제어기가 켜져 있을 때 차단되는 것을 먼저 확인하고, 실행 중이 아닌 상태에서
`llama-continuity-test/ordered-offload-controller`와 `continuity-controller`를 0 replica로
내려 인계했다. 이 둘은 현재 중단 상태이며 Llama 실행·복귀는 공통 제어기가 담당한다.

| 검증 | 실제 결과 | 원본 |
|---|---|---|
| 기존 제어기와 중복 제어 차단 | previous_controller_not_stopped로 배치 차단 | `handoff-blocked.json` |
| 실제 모델 요청 | 210/210 ID·model digest·출력·토큰 수 검증 통과 | `round-trip.json` |
| 자동 왕복 | AGX(edge)→Spark(server)→AGX(edge) | `round-trip.json`, `after.json` events |
| Pod 유지 | AGX·Spark Pod UID 동일, 두 Pod 모든 container restart 0 | `before.json`, `after.json` |
| 최종 모델 상태 | AGX ACTIVE 1348.45 MiB, Spark CACHED 0 MiB | `after.json` |
| Spark GPU process | nvidia-smi exit 0, compute process 없음 | `spark-gpu-processes.json` |
| GPU 예약 | 기존 Pod의 GPU/GPU.shared 요청 각 1 유지 | `after.json` pod resources |

원본 경로는 `edge-orch/runtime-operator/results/2026-09-10-resident-v1/`이다. 이 시험은
실제 GPU 모델 추론이며 앞의 CPU 합성 HTTP fixture와 구분한다. Nano는 현재 runtime이
정상 준비되지 않아 이 인계 계약에 넣지 않았다. 전체 노드 장애·gateway HA·임의 LLM
입력 및 NPU artifact 이전을 검증한 결과는 아니다.

### 운영 절차

기존 제어기의 실행 여부와 worker active/queue=0을 확인한 뒤 기존 제어기를 중단하고
Pod 종료까지 기다린다. 그다음 다음 계약을 적용한다. 공통 제어기는 인계 조건이
충족되지 않으면 실행하지 않는다. 운영자는 gateway를 통하지 않는 직접 generate나
activate/deactivate를 병행하지 않는다.

```bash
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -f edge-orch/runtime-operator/demo/llama-resident.yaml
rtk proxy kubectl --context kubernetes-admin@kubernetes -n platform-runtime get runtimeservices
```

예제 실부하 스크립트 `scripts/smoke-resident.py`는 명시한 gateway·서비스에만 고정
계약 요청을 보낸다. 서비스 중단은 RuntimeService의 suspended=true로 접수를 막고
모델 해제를 기다린다. 이전 제어기로 돌아가려면 공통 서비스 drain·모델 해제 확인 후
기존 제어기를 복원해야 한다. 기존 토큰 없는 순차 데모 웹은 인계로 중단 상태이며
공통 운영 관측은 NEXUS의 서비스 → 클러스터 실행으로 연결한다. 계약 등록은 Kubernetes 계약을 사용한다. 아래 토큰 없는 데모 실행 절에 한해 등록된 시험 입력을 NEXUS에서 보낼 수 있다.

최종 resident-v2에서는 기존 Pod가 계약에 적힌 가속기·CPU·메모리 예약을 실제 보유하는지
검사한다. 제어기 교체 후 저장 요청 재조회에서는 worker completed_requests가 증가하지
않았고 새 GPU 요청에서는 AGX 처리 건수가 정확히 1 증가했다. 이 근거는
`results/2026-09-10-resident-v2/restart-and-reservation-gate.json`에 보관한다.
공통 제어기의 단위·배포 계약 시험은 현재 39개 통과다. 전체 시험의 기존 센서 Argo CD
브랜치 불일치는 위 v7 기록과 같은 별도 문제다.


## NEXUS 공통 실행 관측 (2026-09-10)

[서비스 → 클러스터 실행](http://aggregator.192.168.0.56.sslip.io/#runtime-services)에서
장비 이름에 고정되지 않은 서비스별 실행 위치를 확인한다. 현재 두 합성 HTTP 서비스와
qualified 8-token Llama 추론 서비스가 같은 공통 제어기에 등록되어 있다.

- `/state/runtime-services`는 고정된 내부 operator `/services`만 읽는 typed projection이다.
  EdgeX inventory·센서 서비스 catalog와 별도로 관리한다. Kubernetes write 권한을 추가하지 않는다.
- 현재 요청을 받는 실행체, 새 준비 대상, drain·반환 중 대상과 후보 제외 이유를 표시한다.
  마지막 전환의 이전/다음 노드·이유·시각은 현재 배치 유지 이유와 구분해 보존한다.
- 모델 메모리와 실행 중 요청은 실제 worker probe에서 가져온다. Pod Ready로 모델 준비를
  추측하지 않는다. 15초 이상 오래된 snapshot·service·worker 관측은 현재 정상으로 표시하지 않는다.
- 5초마다 관측하며 조회 실패 시 경고와 과거 위치를 유지하되 현재 모델 메모리는 숨긴다.
  마지막 모델 해제는 시각이 붙은 과거 기록이다. GPU 예약 반환 또는 현재 대기 모델 상태로
  해석하지 않는다. 메모리만 해제하는 resident 방식은 Pod/GPU 예약을 유지한다.
- 서비스 등록·정책 변경은 `RuntimeService`와 Kubernetes RBAC가 담당한다.
  NEXUS 서비스 설계는 기존 dry-run이다. 클러스터 실행 탭의 별도 데모 버튼은 명시적으로 허용된 고정 입력만 공통 gateway로 보낸다.

검증: API·operator 관련 Python 42개, 전체 JavaScript 245개 통과.
독립 실행한 root+operator는 154개 통과·기존 센서 Argo CD 브랜치 기대값 1개 실패,
state-aggregator는 417개 통과·기존 `virtual-device-runtime` 디렉터리 누락 시험 1개 실패다.
서로 다른 서비스의 `app` 패키지를 같은 pytest 프로세스에 섞으면 import 충돌이 있어
두 suite를 분리 실행했다. 실패를 없애기 위한 테스트 삭제·skip은 하지 않았다.
1440px desktop·390px mobile에서 확인했으며 모바일 document 폭은 390px,
860px 표는 312px 내부 컨테이너에서 스크롤한다. 브라우저만 503 응답으로 가로챈
관측 장애 시험에서 경고·현재 메모리 숨김을 확인했다. 실제 cluster 서비스는 중단하지 않았다.

추가 실장비 재검증은 **201/201 요청 성공**, AGX → Spark → AGX의 왕복이며
고정된 qualified 8-token 계약을 유지했다. `results/2026-09-10-nexus/round-trip.json`에
요청별 결과를, `runtime-services.json`에 NEXUS가 실제 받은 위치·마지막 전환·해제
관측을 보관했다. `running-images.json`은 operator와 aggregator의 실제 Ready Pod
imageID다. operator `597e6145…`, aggregator `1c8e3f8b…`를 확인했다.
이 실험은 무손실 일반 장애 복구·HA·임의 서비스 SLO 보장의 근거가 아니다.


## 선택적 요청 지연 정책 (2026-09-10)

ELI5: 줄이 길어졌다는 신호뿐 아니라 손님이 실제로 얼마나 기다렸는지도 본다.
잠깐 느렸다는 이유로 바로 옮기지 않는다. 여러 요청이 계속 늦고, 같은 서비스를 실행할
검증된 후보가 있을 때 새 실행체를 준비한다. 돌아올 때는 더 엄격한 회복 기준을 적용한다.

`policy.latency`는 기본 비활성이다. 활성 서비스만 서비스 UID·실행 revision별로 최근
window의 p95를 사용한다. 유효한 새 요청의 gateway 접수 대기부터 worker 응답 수신까지
monotonic clock으로 측정한다. 네트워크가 포함되지만 클라이언트에서 gateway까지의
전송과 응답 이후 브라우저 렌더링은 포함하지 않는다. 저장 결과 replay는 새 표본이 아니다.

- `maxP95Milliseconds`: 이 값을 초과하는 유효 p95가 `breachSeconds` 동안 지속되면
  automatic 모드에서 후보를 찾는다. 동시 요청 수가 낮아도 적용한다.
- `returnP95Milliseconds`: 이동 임계값보다 낮아야 한다. 현재 실행체 p95 회복과 낮은
  동시 부하가 각각 `returnSeconds` 동안 유지되어야 선호 역할로 복귀한다.
- `windowSeconds`, `minSamples`: 창 안의 성공 표본 수가 부족하면 판단 대기다. worker
  실패·결과 불명·접수 queue 포화·접수 timeout이 있으면 성공 p95만 보고 회복으로 판단하지 않는다.
- `qualifiedP95Milliseconds`: 후보별 검증 결과다. 이동 후보는 이동 기준, 복귀 후보는
  복귀 기준을 만족해야 한다. 지연 초과로 이동할 때는 현재 실행 변형보다 검증 p95가 더 낮아야 한다(현재 검증값이 없으면 검증된 후보만 허용). 같은 후보의 최근 실측이 나쁘거나 실패가 있으면 재선택을 막는다. serial qualification보다 높은 부하에서는 이동 뒤에도 기준을 초과할 수 있으며, 더 나은 검증 후보가 없으면 이를 그대로 표시한다.
  정상 호환성·자원·readiness·drain 검사는 그대로 적용한다.
- 모델 준비/노드 장애에 의한 기본 failover는 계속 별도 근거다. 지연 정책이 없는 서비스의
  동시 부하 기반 동작은 유지한다. 정책 변경은 dwell 시각을 초기화하고 건강한 Pod를
  정책 자체만으로 교체하지 않는다.

표본은 서비스/revision별 최근 최대 2,048개, 최대 600초의 process-local 상태다.
제어기 재시작 후 새 표본이 쌓여야 지연을 판단한다. 원장에 저장된 과거 p95로 자동 이동을
재개하지 않는다. 최근 표본 창은 작은 기준선이며 장기 SLO 달성률·통계적 신뢰구간은 아니다.
NEXUS와 RuntimeService status에는 p95·표본 수·실패 수·측정 범위를 함께 표시한다.

실장비 후보 검증은 `scripts/qualify-latency.py`의 같은 qualified 8-token 입력에 대해
직렬 20회씩 수행했다. 엣지 AGX 20/20 성공·p95 **531.578ms**, 서버 Spark 20/20
성공·p95 **456.092ms**다. 이는 port-forward를 포함한 client↔gateway 왕복이며,
분리된 과부하 상황의 p95 보장이 아니다. 원자료는 `results/2026-09-10-latency/`의
`edge-qualification.json`, `server-qualification.json`에 있다.

데모는 900ms 초과 4초 지속, 복귀 700ms 이하·낮은 부하 8초 지속, 20초 창·최소 10개
성공 표본으로 설정했다. 다른 서비스는 같은 숫자를 복사하지 않고 자신의 입력·모델·부하로
검증해야 한다. 공통 제어기는 장비 이름 순서를 사용하지 않는다.


첫 지연 전환 시험 `round-trip-v1.json`은 409/409 요청 성공이지만 **복귀 gate 실패**다.
서버도 과부하인 동안 이전 엣지의 나쁜 표본이 window에서 사라지자 엣지를 다시 지연
전환 후보로 고른 것이 원인이다. 두 전환 모두 `sustained_latency_breach`였으며
회복·복귀로 기록하지 않는다. 수정은 현재 실행 변형보다 검증 p95가 더 낮은 후보만
지연 확대 대상으로 허용한다. 느린 변형으로의 복귀는 별도 낮은 부하·지연 회복 조건을
통과해야 한다. 실패 원자료를 유지하고 이 상황을 재현하는 단위 회귀 검사를 추가했다.

제어기 재시작 직후 `restart-warmup.json`은 정상 실행 위치를 재검증한 상태에서도
latency 표본 수 0·valid=false임을 보여준다. 상태 조회 경로가 살아 있다는 사실을
새 지연 측정이 완료된 것으로 해석하지 않는다.


수정 후 `round-trip-v2.json`은 **383/383 요청 성공**, `sustained_latency_breach`에
의한 AGX → Spark, `sustained_low_load_return`에 의한 Spark → AGX와 retiring=0을
확인했다. 시험 중 동시성 pressure dwell은 3,600초로 두어 900ms 지연 조건이 전환
원인임을 분리했다. 종료 후 Git 데모 계약의 4초로 복원했다. 이 값과 지연 조건은
서비스별 선언이며 노드 이름을 조건문으로 사용하지 않는다.

과부하 중 Spark의 p95도 900ms를 넘었고 `latency_no_qualified_target`을 표시했다.
이는 숨기지 않은 미달 구간이다. 검증 결과는 지연 기반 전환·회복 후 복귀와 요청 결과
연속성의 근거이며, 부하 전 구간의 900ms SLO 달성 증거가 아니다.
`after-runtime-services.json`, `final-contract.json`, `resident-workers.json`과
`running-images.json`에 최종 실행 위치·해제·정책·기존 Pod restart=0·실제 imageID를
보관한다. operator `d71a4e8b…`, aggregator `88e7b02f…`를 확인했다.

현재 operator 단위/배포 49개, aggregator API 4개, 전체 JavaScript 246개 통과다.
root+operator는 164개 통과·기존 Argo 브랜치 기대값 1개 실패,
aggregator 전체는 418개 통과·기존 virtual-device-runtime 디렉터리 누락 1개 실패다.


## 토큰 없는 제한형 데모 실행 (2026-09-10)

ELI5: 서비스 옆 버튼으로 미리 정해 둔 시험 요청을 보낸다. 왕복 시험은 잠시 요청을
늘렸다가 줄인다. 어디로 옮길지는 전체 클러스터 후보와 서비스 정책으로 결정한다.
HTTP 응답만 성공하고 복귀하지 못하면 화면에 **검증 미완료**로 남는다.

NEXUS의 [AI 서비스 → 클러스터 실행](http://aggregator.192.168.0.56.sslip.io/#runtime-services)에서
`시험 요청 1건`, `왕복 시험`, `새 시험 요청 중단`을 제공한다. 실행 토큰 입력은 없다.
등록·정책 편집은 Kubernetes 계약을 사용하며 서비스 설계 화면의 dry-run 경계는 유지한다.

- 운영자가 `RuntimeService.spec.demo`에 명시한 고정 JSON 입력만 보낸다.
  브라우저에서 임의 payload·대상 URL·노드·Kubernetes 명령을 입력할 수 없다.
  resident Llama는 qualification과 동일한 prompt·8-token 계약을 강제한다.
- 현재 demo 설정은 최대 512건, 동시 6건, 부하 25초 후 회복 관측 최대 120초다.
  회복 요청 간격은 1초다. 합성 HTTP 입력에는 0.5초 응답 지연을 넣어 빠른 응답이
  부하 단계에서 요청 한도를 소진하지 않도록 했다. AI 성능 측정값은 아니다.
- 서비스 UID당 진행 시험 1개, 전체 2개, 종료 후 10초 대기를 적용한다.
  런타임 snapshot이 오래되거나 준비·반환 중이면 새 시험을 받지 않는다.
- aggregator는 `COMMON_RUNTIME_DEMO_ENABLED`와 같은 Origin·전용 요청 헤더를 검사한다.
  이는 LAN 데모의 제한된 실행 경로이며 사용자별 인증·권한 관리의 대체가 아니다.
  공통 gateway는 내부 ClusterIP를 유지한다. EdgeX·actuator 제어 권한은 추가하지 않는다.
- 실행 ID와 자식 요청 ID를 PVC SQLite 원장에 기록한다. 접수 응답이 불명확하면
  같은 ID로 확인·재접수한다. 이미 접수된 ID는 과거 결과를 반환한다.
  서비스 삭제·재등록으로 UID가 바뀌면 새 서비스로 요청을 넘기지 않는다.
- 중단은 새 요청 생성을 멈추고 이미 보낸 요청을 마무리한다. 서비스 자체를 중단하지 않는다.
  controller 재시작 시 진행 시험은 `Interrupted`로 남기며 자동 재실행하지 않는다.
  미확인 요청은 성공으로 합산하지 않는다. 완료 결과의 경로·반환 개수는 종료 시점 기록이다.

실제 브라우저 버튼으로 실행한 결과:

| 시험 | 결과 | 경계 |
|---|---|---|
| 실제 GPU Llama 단일 요청 | 1/1 성공 | 동일 ID 재접수도 원장 자식 요청은 1개 |
| 실제 GPU Llama 왕복 | **261/261 성공**, 엣지 AGX → 서버 Spark → 엣지 AGX, 반환 중 0 | 모델 메모리만 해제, GPU 예약과 resident Pod 유지 |
| 합성 HTTP 왕복 | **173/173 성공**, Tinker → 서버 cg0msb → 엣지 AGX, 반환 중 0 | 시작 장비와 다른 엣지 복귀도 허용하는 전체 후보 선택 |
| 합성 HTTP 사용자 중단 | 410/410 응답 완료 후 `Stopped` | 종료 당시 반환 중 1개; 왕복 통과로 집계하지 않음 |

브라우저 접수 일부는 5초 안에 응답을 받지 못했다. Llama 왕복은 원장에서 기존 ID를
찾아 확인했고, 합성 중단 시험은 같은 ID 재접수 후 진행했다. 중복 실행으로 성공률을
부풀리지 않았다. 원장에는 네 실행에 해당하는 자식 요청 **845개**가 모두 completed로
기록되어 있다. 1440px desktop과 390px mobile을 확인했으며 mobile 문서 폭은 390px다.

근거는 `edge-orch/runtime-operator/results/2026-09-10-token-free-demo/`의
`runs.json`, `same-id-replay.json`, `durable-journal.json`, `running-images.json`이다.
새 operator 이미지 `4bb7abaa…`, aggregator 이미지 `799f8ab1…`의 실제 Pod imageID를 확인했다.
Python root+operator 171개 통과·기존 센서 Argo CD 기대 브랜치 불일치 1개 실패,
aggregator 420개 통과·기존 virtual-device-runtime 경로 누락 1개 실패,
JavaScript 249개 통과다. 공통 operator 자체는 56개 통과다.
이 결과는 streaming·stateful 서비스, NPU 모델 호환, 제어기 HA 또는 모든 장애에서
무중단을 보장하는 근거가 아니다. 접수 지연 원인도 이 시험만으로 확정하지 않았다.


## 공통 오케스트레이션 완료 검수 (2026-09-10)

위에 정의한 최초 지원 계약과 7개 합격 기준을 코드·시험·실배포 근거로 다시 대조했다.
장비 이름을 정책 순서로 사용하는 부분은 없으며, resident 예제의 장비 연결은 기존 Pod의
소유권·모델 자격을 확인하기 위한 명시적 binding이다. 새 서비스 등록은 Kubernetes
`RuntimeService` apply로 제공한다. 서비스 등록 UI가 있어야만 등록할 수 있는 구조가 아니다.

| 합격 기준 | 확인 근거와 측정 경계 | 판정 |
|---|---|---|
| 1. 임의 서비스·노드 이름으로 배치 | arbitrary names 단위시험, 고정 selector 없는 live 합성 CR, 173/173 Tinker→서버→AGX 왕복 | 충족 |
| 2. 비정상·자원·호환성 제외 | NotReady/pressure/taint/CPU·메모리 부족, GPU≠NPU, RuntimeClass 검사 시험 및 live 후보 제외 목록 | 충족; NPU 실제 모델 실행 검증과 구분 |
| 3. Pod·애플리케이션 준비 후 전환 | `test_never_switch_until_pod_and_application_ready`, resident 실제 모델 준비 관측 | 충족 |
| 4. 준비 실패 시 경로 유지·진행 요청 drain | `test_failed_prepare_preserves_active_and_releases_unrouted_pod`, `test_pressure_switch_drain_return_and_scale_retry`, 실제 왕복·retiring 0 | 충족; 전체 노드 강제 장애 무손실 보장은 아님 |
| 5. dwell/cooldown·복귀·후보 부재 | pressure/return 및 latency 시험, 지연 v2 383/383과 데모 GPU 261/261, 후보 제외 이유 UI | 충족 |
| 6. 재시작 결과 불명·중복 방지 | 원장 재개·timeout 단위시험, general-v7/restart-replay 및 resident-v2 재접수 시 처리 건수 불변 | 충족; 재시작 중 gateway 접속 공백은 존재 |
| 7. 실제 Kubernetes 배치·전환·반환과 시험 분리 | general-v7, resident-v2, latency, token-free-demo의 요청 원장·Pod UID·imageID·상태 JSON | 충족 |

추가 요구인 모델 메모리만 반환, 토큰 없는 단일/왕복 요청·중단·결과 조회, docs 공개와
main 반영도 앞 절의 실측 근거를 따른다. 최종 읽기 전용 점검에서 세 서비스 모두 Serving,
실제 readiness true, 준비 대상 없음, retiring 0이고 네 데모 실행은 모두 종료 상태였다.
CRD는 API 서버가 생략한 `default: null`을 제외하면 저장소 schema와 동일했다.
운영 operator·aggregator의 Ready imageID도 선언한 digest와 일치했다.

검수 중 README의 operator 단독 pytest 명령이 import 수집 순서에 의존하는 결함을 발견했다.
경로 초기화를 테스트 공통 `conftest.py`로 옮겼고 CPU 부족 제외 회귀를 추가했다.
수정 후 operator 단독 57개, root+operator 172개가 통과했다. 후자의 기존 센서 Argo CD
브랜치 기대값 실패 1개는 그대로 남아 있다. 앱 실행 코드는 바꾸지 않아 이미 검증한
이미지와 845개 요청 원장 근거를 재사용한다. 점검 snapshot은
`edge-orch/runtime-operator/results/2026-09-10-completion-audit/`에 보관한다.

이 완료 판정은 명시한 공통 bounded HTTP 오케스트레이션과 데모의 합격 기준에 대한 것이다.
전체 플랫폼 상용화, 일반 NPU 모델 변환·전환, streaming·state migration·HA까지 완료했다는
뜻이 아니다. 이 항목들은 최초 지원 경계와 현재 한계 절에서 계속 후속 범위로 유지한다.
