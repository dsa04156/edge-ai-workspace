# 컨테이너 가상 디바이스 최소 시험 구현

**2026-09-07 실제 시스템 연동 완료:** 기존 대시보드 반영, 서버 Pod 실행, 실제 Jetson 요청,
Pod 교체·오류 관측·정지를 확인했다. 최종 상태는 정의 1개/실행체 0개다.
[실시스템 검증 결과와 현재 실행 명령](실시스템-검증.md)을 우선 참고한다.

`vd-demo-001`은 필요할 때 CPU 모델을 서버 Pod 안에서 실행하는 기능 실행·관리
프로토타입이다. 정지하면 실행 Pod는 없어지고 Git 정의·ID·연결 설정은 남는다.
하드웨어 전체 에뮬레이션, EdgeX 물리 디바이스, 자동 오프로딩 또는 GPU 분할 기능이 아니다.
기존 EdgeX 센서와 운영 서비스, Argo CD `edgex-telemetry`의 manifest는 수정하지 않는다.

쉽게 말하면 **등록부는 남겨 두고 계산 담당자만 출근·퇴근시킨다.**
출근 예정 서버와 실제 출근 서버, 출근 여부와 모델 준비 여부, 연결 신청과 실제 업무
처리 영수증을 각각 확인한다. 조회가 끊겼으면 퇴근했다고 단정하지 않는다.

## 기존 구현과 재사용 경계

현재 checkout에는 `device-augmentation/`의 실행 파일 및
`virtual_resources.py`·`virtual_resource_registry.py`가 없었다.
`7419060d` 이전 이력에서 다음 계약을 확인하고 역할을 재사용했다.

- AugmentationResource: `metadata.name`, `displayName`, `resourceType`,
  `nodeSelector`, `stageTypes`, `capabilities`, `runtimeRef.namespace/podSelector`
- DeviceAugmentation: `targetDevice`, `bindings.inferenceResource`, `workloadPolicy`
- 새 선택 필드: `runtimeRef.workloadRef`·`port`, `model`. 구형 필드는 보존하지만
  workload 참조와 정확한 ID 라벨이 없는 정의는 관측을 **확인 불가**로 반환한다.

정의 권위는 기존 aggregator의 Git 설정 방식에 맞춘
[`virtual_devices.json`](../state-aggregator/app/config/virtual_devices.json)이다.
CR 형태의 파일 registry이며 CRD 등록·legacy controller 재설치는 하지 않는다.
과거의 Pod 이름·개수로 Ready를 추정하거나 가짜 Pod ID를 만드는 코드는 재사용하지 않는다.
현재 센서 서비스 모델은 시계열 윈도우 계약에 종속돼 있어 변경하지 않았다.

## 모델과 API

내장 모델은 sklearn Fisher Iris 150개 중 고정 층화 train/test 120/30개로 학습한
3-class nearest-centroid 분류기다. hold-out 정답률은 27/30(0.90)이며 공장 품질 판단
성능을 의미하지 않는다. 학습된 평균 벡터는 `models/iris-centroids.json`에 포함된다.
추론은 이 벡터와 입력 사이의 Euclidean distance를 계산해 가장 가까운 클래스를 고른다.
고정 응답, 난수 점수 또는 confidence로 위장한 거리는 없다.

| API | 의미 |
|---|---|
| GET /healthz | 프로세스 생존. 모델 파일이 없어도 200 |
| GET /readyz | 모델 준비 + 오류 없음 + draining 아님. 실패 시 503 |
| GET /status | 논리 ID, Pod UID, boot ID, 모델 ID·버전·SHA256, inFlight, succeeded/failed/rejected, 마지막 처리 시각·성공 요청, 실측 usage |
| POST /infer | 입력 검증 후 실제 모델 실행. 검증 실패 422, 모델 오류·종료 중 503, 동시 처리 한도 초과 429 |

입력은 cm 단위 `[sepal length, sepal width, petal length, petal width]`다.
정확히 4개 유한 숫자, 각 0..30 범위이며 알 수 없는 필드는 거절한다.

```json
{"requestId":"jetson-test-001","clientId":"etri-dev0001-jetorn","features":[5.1,3.5,1.4,0.2]}
```

이 예제의 label은 `setosa`다. 결과에는 요청 ID·clientId, input SHA256, 모델
identity·artifact SHA256, Pod UID, boot ID, 계산 결과, 완료 시각과 처리시간이 포함된다.
`/status.lastSuccess`는 반환된 같은 결과다. 클라이언트는 두 결과와 증가한 건수를 검증한다.

- 카운터는 **프로세스 부팅 단위**이며 Pod 내 재시작에도 초기화된다. `bootId`로 구분한다.
- `failed`는 실제 모델 실행 실패, `rejected`는 입력·준비·용량 조건에 의한 거절이다.
- 중복 요청 ID도 다시 실행한다. 자동 재전송·idempotency·영속 요청 감사는 v1 범위 밖이다.
  검증 클라이언트는 기본 UUID를 사용하며 동시 요청 없이 before/after를 비교한다.
- `clientId`는 클라이언트의 선언이다. 물리 Jetson 신원 인증이나 네트워크 도달성 보증이
  아니다. 실제 Jetson 터미널에서 실행한 결과를 별도 확보해야 현장 요청 전달로 검증된다.
- 마지막 성공 결과 1개만 메모리에 둔다. 정지 전 클라이언트 JSON을 저장해야 이력이 남는다.

교체할 모델은 `vd_runtime/model.py`의 `ModelAdapter`를 구현하고
`load_adapter`에 명시적으로 등록한다. 새 artifact와 ID·버전, registry 계약도 함께
변경한다. `MODEL_PATH`가 없거나 파일·차원·algorithm이 잘못되면 자동 대체하지 않고
503 readiness와 오류를 반환한다. 모델은 런타임에 내려받지 않는다.

## 로컬 빌드와 자동시험

아래 명령은 저장소 루트 기준이다. 셸 명령은 저장소 규칙대로 `rtk proxy`로 실행한다.

```bash
rtk proxy python3 -m venv /tmp/vd-demo-venv
rtk proxy /tmp/vd-demo-venv/bin/pip install -r edge-orch/virtual-device-runtime/requirements-dev.txt
rtk proxy /tmp/vd-demo-venv/bin/python edge-orch/virtual-device-runtime/scripts/train_model.py
rtk proxy env PYTHONPATH=edge-orch/virtual-device-runtime /tmp/vd-demo-venv/bin/python -m pytest -q edge-orch/virtual-device-runtime/tests

# 기존 aggregator 가상환경(requirements.txt 설치 상태)
rtk proxy env PYTHONPATH=edge-orch/state-aggregator edge-orch/state-aggregator/.venv/bin/python -m pytest -q edge-orch/state-aggregator/tests
rtk proxy bash -c 'node --test edge-orch/state-aggregator/tests/*.js'

rtk proxy docker build -t virtual-device-runtime:local edge-orch/virtual-device-runtime
rtk proxy docker run --rm --name vd-demo-local -p 127.0.0.1:18081:8080 virtual-device-runtime:local
# 다른 터미널
rtk proxy python3 edge-orch/virtual-device-runtime/scripts/jetson_client.py --url http://127.0.0.1:18081 --expected-label setosa
rtk proxy docker stop --time 35 vd-demo-local
```

컨테이너를 사용할 수 없는 환경에서는 같은 코드를 직접 실행할 수 있다.

```bash
rtk proxy env PYTHONPATH=edge-orch/virtual-device-runtime POD_UID=local-qa-pod PORT=18081 /tmp/vd-demo-venv/bin/python -m vd_runtime
```

SIGTERM 수신 즉시 draining으로 바꾸고 신규 추론을 거절한다. 이미 시작한 모델 thread가
실제로 완료된 뒤에만 inFlight를 줄인다. Uvicorn은 최대 25초 graceful wait,
Pod는 35초 termination grace를 둔다. 내장 모델은 작은 bounded 계산이다.
장시간 모델 어댑터로 교체할 때는 최대 추론시간과 취소 계약, 두 grace 기간을 재검증한다.
SIGKILL·노드 단절의 요청 무손실 복구를 보장하지 않는다.

## 배포 전 준비: 변경 없는 렌더

실클러스터 변경은 **context, 서버, image digest와 아래 대상·명령을 운영자가 승인한 뒤**
수행한다. 이 문서나 render 실행만으로 승인을 받은 것으로 간주하지 않는다.
초기 로컬 구현 뒤 사용자 승인을 받아 실제 배포·Jetson 시험까지 수행했다.
세부 대상과 결과는 실시스템 검증 문서를 따른다.

1. 실제 서버의 OS·CPU architecture, CPU/memory 여유와 이미지 접근 경로를 확인한다.
   GPU를 요청하지 않는다. 서버가 ARM64라면 해당 architecture로 이미지를 빌드해야 한다.
2. 빌드 이미지를 시험 registry에 전달하고 digest를 확보한다.
3. 명시적 노드 selector와 자원값으로 리뷰할 파일을 만든다.

```bash
rtk proxy docker tag virtual-device-runtime:local REGISTRY/virtual-device-runtime:vd-demo-v1
rtk proxy docker push REGISTRY/virtual-device-runtime:vd-demo-v1
# 출력된 immutable digest 사용. 아래 대문자 placeholder는 실제 검증값으로 치환한다.
rtk proxy /tmp/vd-demo-venv/bin/python edge-orch/virtual-device-runtime/scripts/render.py \
  --image REGISTRY/virtual-device-runtime@sha256:DIGEST \
  --node-selector kubernetes.io/hostname=APPROVED_SERVER \
  --cpu-request 100m --cpu-limit 1 --memory-request 64Mi --memory-limit 256Mi \
  --output /tmp/vd-test
rtk proxy cat /tmp/vd-test/manifest.json
```

render는 로컬 `kubectl kustomize`만 실행하며 Kubernetes에 연결하지 않는다.
출력은 독립 namespace, 모델 설정 ConfigMap, replicas=0 Deployment, ClusterIP Service,
등록 정의 ConfigMap과 aggregator용 파일 registry다. 기본 base는 opt-in 노드 라벨을
요구한다. 위 예제는 노드를 변경하는 label 명령 없이 exact hostname 조건으로 바꾼다.
NodePort·Ingress·GPU·hostPath·write RBAC는 만들지 않는다.

## 승인 후 등록·기동·요청·정지

대상은 `virtual-device-test` namespace의 `vd-demo-001` Deployment·Service,
`vd-demo-001-settings`와 `virtual-device-registry` ConfigMap으로 제한한다.
기존 운영 namespace에는 apply하지 않는다.

```bash
# 등록: replicas=0 유지
rtk proxy kubectl --context APPROVED_CONTEXT apply -f /tmp/vd-test/manifest.json
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get deployment vd-demo-001 -o json
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get pods -l edge-ai.io/virtual-device-id=vd-demo-001 -o json
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get configmap virtual-device-registry -o json

# 기동: 수동 scale만 수행
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test scale deployment/vd-demo-001 --replicas=1
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test rollout status deployment/vd-demo-001 --timeout=120s
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get pods -l edge-ai.io/virtual-device-id=vd-demo-001 -o wide
```

서버 로컬 API 시험은 다음 port-forward로 수행한다. Jetson에서 같은 명령을 실행하면
Jetson→Kubernetes API tunnel→Service 경로 시험이며 실제 클러스터 Service 네트워크
시험과는 구분한다.

```bash
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test port-forward service/vd-demo-001 18081:8080 --address 127.0.0.1
# 다른 터미널: 로컬 API readback
rtk proxy curl --fail http://127.0.0.1:18081/healthz
rtk proxy curl --fail http://127.0.0.1:18081/readyz
rtk proxy curl --fail http://127.0.0.1:18081/status
rtk proxy python3 edge-orch/virtual-device-runtime/scripts/jetson_client.py \
  --url http://127.0.0.1:18081 --request-id jetson-test-001 --expected-label setosa
```

Jetson에 `scripts/jetson_client.py`만 복사하면 Python 표준 라이브러리로 실행된다.
직접 Service DNS가 Jetson에서 실제로 해석·라우팅되는 경우에만 다음 주소를 사용한다.
EdgeMesh/DNS가 된다고 가정하거나 운영 네트워크 설정을 자동 변경하지 않는다.

```bash
# Jetson 터미널에서 실행; 결과 JSON을 시험 증거로 보관
python3 jetson_client.py \
  --url http://vd-demo-001.virtual-device-test.svc.cluster.local:8080 \
  --client-id etri-dev0001-jetorn --expected-label setosa
# curl 원시 요청 예
curl --fail http://vd-demo-001.virtual-device-test.svc.cluster.local:8080/infer \
  -H 'Content-Type: application/json' \
  -d '{"requestId":"jetson-curl-002","clientId":"etri-dev0001-jetorn","features":[5.1,3.5,1.4,0.2]}'
```

정지할 때는 시험 클라이언트의 신규 요청을 먼저 중단한다. Kubernetes가 SIGTERM을
보내면 기존 요청을 정리한다. scale 응답 자체는 자원 반환 증거가 아니다.

```bash
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test scale deployment/vd-demo-001 --replicas=0
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test wait --for=delete pod \
  -l edge-ai.io/virtual-device-id=vd-demo-001 --timeout=90s
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get pods -l edge-ai.io/virtual-device-id=vd-demo-001 -o json
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get deployment vd-demo-001 -o json
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get configmap virtual-device-registry -o json
```

정상 API 조회의 Pod `items: []`, Deployment `spec.replicas: 0`, registry의
`vd-demo-001` 유지와 대시보드 실행체 0을 함께 확인한다. wait 실패, terminating Pod,
API timeout·403 또는 오래된 화면이면 종료·자원 반환을 **미확인**으로 기록한다.
namespace/Deployment/registry는 삭제하지 않는다.

## 기존 대시보드 연결

기존 aggregator에 `GET /api/virtual-devices`와 `#virtual-devices` 탭을 추가했다.
별도 프런트엔드 플랫폼이나 workload 변경 API·버튼은 없다.
사용자 승인 후 기존 aggregator를 Argo CD 이미지 override로 갱신했다.
최종 digest와 보존 범위는 실시스템 검증 문서를 따른다. 후속 rollout도 변경 범위를 검토한다.

- 기본 registry는 aggregator image에 포함된다. 서버 selector를 바꿨다면 render가 출력한
  `virtual_devices.json`을 aggregator의 읽기 전용 설정 파일로 배포하고
  `VIRTUAL_DEVICE_REGISTRY_PATH`로 지정한다. Git 파일도 검토 후 같은 내용으로 유지한다.
- 시험 namespace의 registry ConfigMap은 등록 보존 증거이며 API가 몰래 읽거나 쓰는
  두 번째 권위가 아니다. 다른 namespace의 ConfigMap을 직접 volume mount할 수 없으므로
  aggregator의 기존 namespace에 설정 파일을 전달하는 배포는 별도 검토가 필요하다.
- 기존 reader 권한으로 nodes, 시험 namespace의 Deployment·ReplicaSet·Pod를 읽을 수
  있는지 확인한다. 부족할 경우에만 `k8s/observer-rbac.yaml`의 namespace 한정
  get/list RoleBinding을 별도 승인 후 적용한다. 기본 Kustomization에는 포함하지 않았다.
  SA는 현재 `default/state-aggregator`이며 다른 설치에서는 subject를 검토해 수정한다.
- aggregator→실제 Pod IP:8080의 `/status` 접근이 필요하다. Service 응답을 임의 Pod에
  귀속하지 않는다. 정확한 Deployment UID→ReplicaSet UID→Pod UID와 ID 라벨을 확인하고
  런타임 응답의 Pod UID·logical ID도 일치해야 한다.

```bash
# 모두 조회 명령. 실제 context를 지정한다.
rtk proxy kubectl --context APPROVED_CONTEXT auth can-i list pods -n virtual-device-test --as system:serviceaccount:default:state-aggregator
rtk proxy kubectl --context APPROVED_CONTEXT auth can-i list replicasets.apps -n virtual-device-test --as system:serviceaccount:default:state-aggregator
rtk proxy kubectl --context APPROVED_CONTEXT auth can-i get deployments.apps -n virtual-device-test --as system:serviceaccount:default:state-aggregator
# 추가 reader 권한이 승인된 경우에만:
rtk proxy kubectl --context APPROVED_CONTEXT apply -f edge-orch/virtual-device-runtime/k8s/observer-rbac.yaml
# 새 aggregator가 배포된 주소에서 readback:
rtk proxy curl --fail AGGREGATOR_URL/api/virtual-devices
```

상단은 Kubernetes Node 객체 수(하드웨어 진위 판별 아님), 등록 정의 수, 관측 실행체 수다.
왼쪽에는 **실제 관측한 Pod의 nodeName**만 배치하고 예정 노드를 대체값으로 쓰지 않는다.
검색·실제 노드 필터·새로고침·10초 갱신을 제공한다. 등록만 된 항목은 전체 목록에 남고
특정 실제 실행 노드 필터에서는 제외된다.

- Pod Ready와 모델 Ready, 실행 상태와 연결 상태는 별도다.
- 최근 30초 성공 요청은 최근 요청 증거이며 과거 성공은 현재 연결 정상으로 표시하지 않는다.
- 누락·30초 만료·미래 시각·조회 실패는 확인 불가다. 브라우저도 30초 만료를 적용한다.
- CPU는 메인 프로세스 CPU time / 관측 간격, 메모리는 Linux 현재 RSS 실측이다.
  Pod 전체 cAdvisor 사용량이나 GPU 사용량으로 표시하지 않는다. requests/limits는
  Kubernetes 선언이다. 측정하지 못한 값은 null→N/A다.
- Ready 아닌 Pod도 존재 관측에는 포함하되 모델/API 실패를 정상 실행으로 표시하지 않는다.
  Failed/Succeeded Pod는 종료 기록으로 별도 보이며 실행체 수에서 제외된다.

## 자동시험과 수동 시연 대응

| 시나리오 | 자동 근거 | 승인된 클러스터 시연 |
|---|---|---|
| 1. 등록만, 실행체 0 | lifecycle·dashboard registered-only 시험 | apply replicas=0, registry ID와 Pod 빈 목록 |
| 2. 기동·실제 노드·모델 Ready | identity reader + 실제 HTTP 통합시험 | scale=1, Pod UID/nodeName, /readyz 및 /status 일치 |
| 3. 요청 ID·결과·건수 | 실제 Jetson client→HTTP→status, aggregator lastSuccess 일치 | Jetson 실행 JSON과 dashboard lastSuccess 비교 |
| 4. Pod 교체·논리 ID 유지 | pod-1→pod-2 교체 시험 | 아래 rollout restart 뒤 새 UID, 동일 logical ID |
| 5. 정상 정지·정의 유지 | lifecycle 0개·registry 유지 + 실제 SIGTERM drain | scale=0→wait 삭제→정상 get 빈 목록 |
| 6. 모델 오류·API 단절 | 파일 누락·오류 latch·stale·실제 서버 종료 시험 | 별도 오류 설정 또는 tunnel 단절, Ready 오표시 없는지 확인 |
| 7. 무관한 같은 노드 Pod 제외 | 다른 label/owner Pod 혼합 시험 | 기존 무관 Pod 유지 상태에서 exact label/owner 결과 비교 |

```bash
# Pod 교체 시험도 승인된 시험 Deployment에만 적용
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test rollout restart deployment/vd-demo-001
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test rollout status deployment/vd-demo-001 --timeout=120s
rtk proxy kubectl --context APPROVED_CONTEXT -n virtual-device-test get pods -l edge-ai.io/virtual-device-id=vd-demo-001 -o json
```

모델 파일 오류를 로컬에서 시연하려면 `MODEL_PATH=/missing/model.json`로 새 로컬
프로세스를 실행한다. 클러스터 모델 오류 시연을 위해 운영 ConfigMap을 변경하지 않는다.
API 단절 시 Pod Ready가 남아 있어도 aggregator의 모델 준비는 확인 불가다.

로컬 브라우저 QA를 재현할 때는 위 직접 실행 명령(`POD_UID=local-qa-pod`, port 18081)과
다음 **Kubernetes 배치 fixture**를 사용한다. Kubernetes에는 접속하지 않으며 이름에
`LOCAL-QA-SIMULATED-SERVER`를 표시한다. 다른 운영 API는 의도적으로 404/503을 반환한다.

```bash
rtk proxy env PYTHONPATH=edge-orch/state-aggregator:edge-orch/state-aggregator/tests \
  edge-orch/state-aggregator/.venv/bin/uvicorn virtual_device_browser_fixture:app --host 127.0.0.1 --port 18082
# http://127.0.0.1:18082/#virtual-devices
# /tmp/vd-qa-state 파일에 running / stopped / error를 쓰면 배치 fixture만 전환한다.
# fixture의 stopped는 실제 프로세스 종료 시험이 아니다.
```

## 검증 상태

2026-09-07 로컬 검증: runtime·manifest 17개, aggregator 신규 시험 12개,
aggregator 전체 329개(신규 12개 포함), JavaScript 전체 172개 통과.
실제 HTTP 추론→status→aggregator 요청 증거 일치와 SIGTERM 중 요청 완료·프로세스 종료를 확인했다.
브라우저 1440px/390px, 등록 유지·미관측 표시를 로컬 fixture에서 확인했다.
추가 권한 확보 후 `virtual-device-runtime:vd-demo-20260907` 이미지(AMD64)의 Docker 빌드와
비루트·읽기 전용 filesystem 컨테이너 실행을 검증했다. 정상 추론·요청 결과/status 일치,
모델 파일 누락 시 readiness 503, 정지 후 포트 닫힘·컨테이너 제거·Git 등록 정의 보존의
두 Docker smoke 시나리오를 통과했다. 로컬 image ID는
`sha256:e752b4e791796e908ba892572cf901aff5cf8646b6e075b6cb6a1971e2704315`다.
이는 registry에 push한 배포 digest나 ARM64 빌드 증거가 아니다.
후속 승인 시험에서 실클러스터 apply·스케줄링·Pod 교체·종료, Jetson의 Service IP 요청과
기존 대시보드 rollout을 확인했다. 초기에는 Jetson 호스트 Service DNS 해석이 실패했지만,
후속 승인 수정에서 FQDN 조회와 실제 추론까지 성공했다.
[호스트 DNS 검증](Jetson-호스트-DNS-검증.md)에 설정·복구·재부팅 미검증 범위를 기록했다.

Docker socket에 관리자 권한이 필요한 환경의 재현 명령(비밀번호는 sudo 프롬프트에서 입력):

```bash
rtk proxy sudo docker build --progress=plain -t virtual-device-runtime:vd-demo-20260907 edge-orch/virtual-device-runtime
rtk proxy sudo env PATH="$PATH" python3 edge-orch/virtual-device-runtime/scripts/container_smoke.py \
  --image virtual-device-runtime:vd-demo-20260907 --output /tmp/vd-container-report.json
```

smoke 스크립트는 임의 포트의 localhost에서 자신이 생성한 컨테이너 두 개만 시험하고
제거한다. Pod UID는 로컬 시험용 선언값이므로 Kubernetes 관측으로 사용하지 않는다.
