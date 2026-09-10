# 공통 서비스 Kubernetes 오케스트레이션

> 상태: 공통 HTTP 실행 제어기 구현 및 격리 Kubernetes 배포. 2026-09-10 합성 요청의 역할 간 왕복을 검증했다. 실제 AI 모델 전환·운영 HA 완료를 뜻하지 않는다.

## 쉽게 설명하면

서비스는 해야 할 일과 필요한 장비 조건을 제출한다. 플랫폼은 현재 일을 맡을 수 있는
노드를 찾는다. 이동할 때는 새 작업자를 먼저 준비하고 새 요청을 넘긴 뒤 이전 작업자의
남은 요청이 끝나야 자원을 반납한다. Nano·Orin·Spark는 그 과정을 시험하는 장비 예시다.

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

현재 실장비 Llama 왕복 결과는 [서버·엣지 반복 오프로딩](서버-엣지-반복-오프로딩.md)의
전용 제어기 증거다. 공통 제어기 검증으로 전용하지 않는다.

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
같은 역할·같은 용량의 노드끼리 낮은 부하만으로 이동하지 않는다. latency SLO 최적화,
전력·가격 최적화나 실제 GPU/NPU 성능 우열은 이 초기 정책의 구현 범위가 아니다.

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
공통 운영 화면 연결은 후속 작업이다.

최종 resident-v2에서는 기존 Pod가 계약에 적힌 가속기·CPU·메모리 예약을 실제 보유하는지
검사한다. 제어기 교체 후 저장 요청 재조회에서는 worker completed_requests가 증가하지
않았고 새 GPU 요청에서는 AGX 처리 건수가 정확히 1 증가했다. 이 근거는
`results/2026-09-10-resident-v2/restart-and-reservation-gate.json`에 보관한다.
공통 제어기의 단위·배포 계약 시험은 현재 39개 통과다. 전체 시험의 기존 센서 Argo CD
브랜치 불일치는 위 v7 기록과 같은 별도 문제다.
