# Llama 오프로딩 라이브 시연

## ELI5

Nano를 작은 계산대로 생각한다. 손님이 몰리면 원격 계산대를 준비하고,
준비가 끝난 다음 새 손님부터 나눠 보낸다. 이미 계산 중인 손님은 옮기지 않는다.
손님이 줄어들면 원격 계산대의 모델을 내린다. 화면의 처리 건수는 실제 worker 응답의
요청 ID·노드 ID·모델 digest를 확인한 결과만 센다.

## 발표자가 바로 보여주는 순서

### 실제 버튼 시연 — GPU 자동 준비

`Cached On-Demand`와 `RTX 5080`을 선택하고 **시연 시작** 확인창을 승인한다.
센서 수집은 유지하고 서버 추론 후보만 잠시 중지한다. GPU 확보·Pod 준비가 끝나면
1→12→2 req/s의 고정 40초 부하가 자동 시작된다. 부하 수동 슬라이더는 제공하지 않는다.
Nano 대기열 상승 → 압력 2초 지속·예상 이득 15% 통과 → 원격 모델 READY → 신규 요청
전환 → 낮은 부하에서 Nano 복귀 → 30초 유휴 모델 반환을 확인한다.
마지막에는 원격 Pod replica=0, 센서 후보 desired=1/Ready=1 및
`/healthz`·`/api/v1/augmentation-readyz` HTTP 200을 확인해야 복원 완료다.

**요청 중단**은 신규 도착/미전송 요청을 취소하고 이미 전달한 요청은 기다린 뒤 복원한다.
브라우저를 닫아도 서버가 계속 실행·정리한다. Controller 재시작 시 PVC의 GPU 세션을
읽고 부하를 재생하지 않고 복원만 재시도한다. API/노드/PVC 장애 동안은 복원 미완료이며
무조건 복원 시간을 보장하지 않는다. 운영자는 `GPU 확보·복원 기록`과 실제 상태를 확인한다.
원격 Pod는 부하 시작 전 준비하며 **부하 임계값은 Pod 생성이 아니라 모델 활성화와
신규 요청 전달을 유발한다**. 준비 비용과 활성화 비용을 섞지 않는다.

Kueue 컨트롤러는 기존대로 유지하되 이 버튼은 Kueue Job/ClusterQueue admission으로
제출하지 않는다. 기존 GPU의 승인된 임시 양보와 Kubernetes Deployment scale을 사용한다.
이것은 일반 GPU 선점 시스템이 아니다. 자동 준비 대상은 RTX 5080 한 대로 제한한다.

### 실측 기록 재생

1. `http://llama-demo.192.168.0.56.sslip.io`를 연다.
2. **발표용 실측 기록**에서 `Cached On-Demand · 오후 2:57:50 · 270건`을 고른다.
3. **실측 시연 재생**을 누른다. 4배속으로 실제 저장된 요청·관측·이벤트를 재생한다.
4. 슬라이더 14초 부근: Nano 압력 감지와 활성화 시작.
5. 32~35초: 원격 READY와 RTX 5080의 실제 응답, 모델 GPU 메모리 적재.
6. 마지막 시점: CACHED 복귀와 모델 GPU 메모리 0 MiB, 원격 검증 완료 116건.
7. 같은 회차 비교 문장과 아래 결과표로 Nano-only와 차이를 설명한다.

REPLAY는 현재 LIVE 상태가 아니다. 재생은 GET만 사용하며 새 요청이나 모델 제어를
실행하지 않는다. **현재 LIVE로 돌아가기**로 실제 상태를 확인한다. 센서 GPU는 반납한
상태라도 자동 준비 배포에서는 시작 버튼이 원격 Pod를 준비한다. 수동 로컬 모드에서만
원격 관리 API가 없으면 시작 버튼이 비활성이다. 재생과 신규 실행을 동일하게 설명하지 않는다.

## 현재 검증 상태 — 2026-09-07

- 로컬 시연 서버와 실제 Nano API의 읽기 전용 연결 확인.
- 관련 Python 자동시험 39개 통과, JavaScript 문법 검사와 Kustomize render 통과.
- 1440px 데스크톱과 390px 모바일 화면 확인. 모바일 문서 폭 390px, 장비 카드 3개.
- 시연 Deployment 1/1 Ready, 공개 URL의 `/health` 정상 및 실제 브라우저 접근 확인.
  화면에 Nano의 ACTIVE·모델 VRAM 1348.45 MiB가 표시된다. 원격 2대는 replica 0이다.
- 실제 Orin Nano + RTX 5080 GPU의 Nano-only/Cached 비교를 두 회차 실행했다.
  총 1,080개 요청 모두 성공, 실제 노드·모델 identity와 전송 1회를 독립 검증했다.
- 배포 장애였던 Kueue 승인 Pod를 사용자 승인 후 서버에 한정했다.
  서버1 disk pressure 재발 후 단일 서버 고정을 두 서버 allowlist affinity로 보강했고,
  정상 서버2에서 Ready로 복구했다. 엣지 노드에는 스케줄되지 않는다.
  webhook endpoint·Pod Ready·server dry-run 정상 확인. 승인 기능을 우회하지 않았다.
- CloudCore를 기존 설정으로 재기동해 엣지 4대와 서버 2대 모두 Ready를 확인했다.
  이 사실은 센서/EdgeX 데이터 정상 여부를 대신 증명하지 않는다.
- Nano worker 갱신 후 모델을 다시 활성화했다. Ollama 100% GPU, 17/17 layers GPU,
  요청 `recovery-nano-gpu-20260907`의 실제 응답·노드·동일 digest를 확인했다.
- 서버 imagefs 여유가 15% 경계에 걸려 기존 프록시가 Pending이었다.
  재다운로드 가능한 pip 캐시 1,906개(약 5.6GB)를 정리해 파일시스템 여유를
  약 71GiB에서 76GiB로 확보했다. 설치 패키지·모델·결과는 삭제하지 않았다.
  kubelet의 안정화 대기 후 DiskPressure=False·taint 해제를 확인했고,
  기존 `llama-offloading-proxy`도 1/1 Ready로 복구됐다. 경고 기준을 낮추거나
  taint를 강제로 제거하지 않았다. 남은 여유는 약 16.1%이므로 대형 image 추가 전
  용량을 다시 확인한다.
- 센서 서비스 `edgex-edge/sensor-anomaly-inference-server1`은 리허설 동안만 승인된
  임시 Argo replica override로 중지했다. 종료 후 override 제거, 원래 desired=1 및
  ready=1, healthz/augmentation-readyz HTTP 200, 원격 worker replica=0을 확인했다.

## 실측 결과와 결론

### 실제 버튼·자동 복원 검증 — 2026-09-07 후속

- 브라우저 시작 버튼 → 승인 확인 → GPU 준비 6.253초 → 고정 부하 실행을 확인했다.
  `0f4848822014`: 270/270 성공, Nano 154건·RTX 5080 116건, p95 지연 13.262초,
  처리량 6.795 req/s. 원격 Ollama `ps`는 100% GPU였다.
- 부하 시작 후 약 14.24초 압력 감지, 활성화 17.364초, 약 32.36초 첫 원격 응답,
  약 37.58초 Nano 복귀, 약 67.66초 CACHED·모델 VRAM 0 MiB를 확인했다.
  이어 원격 Pod replica=0, 원 센서 후보 Ready·health 정상으로 자동 복원했다.
- 원 서비스 health URL 오기와 Scale API의 zero replica 필드 생략을 실제 사전점검에서
  발견·수정했다. 둘 다 실패 이력을 보존했고 해당 계약을 회귀시험에 넣었다.
- `76290995ebdc`: 준비 중 중단 후 원격 추론 없이 센서 후보가 자동 복원됐다.
  당시 배포본은 중단을 failed로 기록했으며 후속 코드에서는 stopped로 구분한다.
- `742657700de1`: 원격 활성화 중 Controller rollout을 시작해 재시작 후 영속 소유권을
  복구하고 원격 replica=0, 센서 1/1·health 정상까지 자동 복원했다. 실험은 interrupted다.
  주기 저장 중 재시작으로 270건 중 완료 기록은 269건만 남았다. 누락을 성공으로
  만들거나 요청을 재전송하지 않는다. 이는 완전한 crash-safe 요청 원장 증거가 아니다.
- 중복 시작 HTTP 409, 승인 대상 외 worker scale RBAC 거부를 확인했다.
  Python 자동시험 53개와 문서 시험 14개 통과. 원본은 `results/button-demo-20260907/`.
- 최종 배포본 재시험 `1763e50ff634`도 270/270 성공, Nano 154·RTX 5080 116건이었다.
  p95 지연 13.408초, 처리량 6.776 req/s, 모델 활성화 17.497초였다.
  GPU 준비 6.178초, 버튼 승인부터 센서 복원까지 약 79.94초였다. 최종 상태는
  원격 replica=0, 센서 desired=Ready=1, 두 health endpoint 200, 임시 override·owner 제거다.
  두 정상 회차 모두 독립 verifier의 요청·모델·READY·Nano 복귀·유휴 반환·GPU 복원 검증을 통과했다.
  390px 모바일 폭 검증, 데스크톱 화면 검사, REPLAY 중 POST 0건과 LIVE 복귀 후
  시작 버튼 활성화를 확인했다. 문서 HTML은 로컬 재생성했으며 문서 사이트 재배포는 별도다.

```bash
rtk python3 qualification/llama-offloading/verify_demo_run.py --require-release-snapshot --require-gpu-return qualification/llama-offloading/results/button-demo-20260907/cached-button.json
```

### 이전 수동 GPU 준비 비교

| 회차 | Nano-only p95 지연 | Cached p95 지연 | 처리량 Nano→Cached | 원격 처리 | Cached 활성화 |
|---|---:|---:|---:|---:|---:|
| 1 | 26.576초 | 4.605초 | 4.390→6.742 req/s | 139건 | 1.916초 |
| 2 · 원격 Pod 재생성 후 | 26.624초 | 13.445초 | 4.386→6.794 req/s | 116건 | 17.494초 |

각 셀은 같은 270개 도착 스케줄의 단일 실행이다. 두 회차 모두 신규 요청 오프로딩과
30초 유휴 반환이 확인됐지만 activation 편차가 크므로 Cached가 항상 2초 안에 켜진다고
설명하지 않는다. 회차2는 model download 0ms였고 model load 구간 17.484초였다.
CUDA 초기화·디스크 읽기 구간은 별도로 분리되지 않아 원인을 단정하지 않는다.
TTFT 1,500ms 초과 요청은 회차1 248→67건, 회차2 248→235건이다. p95 개선과
모든 요청의 SLO 만족은 다르며, 두 회차만으로 일반 성능 개선율을 주장하지 않는다.

회차2에서 모델 GPU 메모리 최대 1348.45 MiB, 반환 뒤 0 MiB와 runner 미실행을
기록했다. 이는 모델 footprint이며 다른 프로세스·관측 지연을 포함할 수 있는 전체
GPU 메모리 값과 다르다. GPU scheduler 예약은 별도 Pod scale-to-zero로 반납했다.

원본: `results/live-demo-20260907/{nano,cached}-{first,second}.json`.
화면 JSON/CSV 다운로드와 아래 독립 검증 명령으로 재확인한다.

```bash
rtk python3 qualification/llama-offloading/verify_demo_run.py --require-release-snapshot qualification/llama-offloading/results/live-demo-20260907/nano-second.json qualification/llama-offloading/results/live-demo-20260907/cached-second.json
```

## 구성과 범위

- `demo.py`: HTTP API, 노드별 독립 관측, 고정 도착 스케줄, 신규 요청 배치,
  활성화, 유휴 반환, SQLite 기록, CSV/JSON 다운로드.
- `demo-web/`: 별도 시연 화면. 운영 `state-aggregator`에는 연결하지 않는다.
- `demo-k8s/`: 시연 서버·결과 PVC·Service·Ingress.
- `gpu_session.py`: RTX 5080 고정 대상, SQLite write-ahead 의도 기록,
  파일 lock·Argo annotation/UID/resourceVersion 비교, 자동 보상 및 재시작 복원.
- `demo-k8s/gpu-access.yaml`: 별도 승인 설치하는 exact-name RBAC와 센서 health 접근.
  RBAC는 Application 내 특정 필드까지 제한하지 못하므로 코드와 테스트가 replica
  override/소유권 annotation만 변경하도록 고정한다. 테스트베드 신뢰 경계 전용이며
  인터넷 공개·다중 사용자 RBAC는 제공하지 않는다. 임의 URL/manifest/command 입력은 없다.
- 원격 model-cache PVC는 실제 scale-to-zero/재생성 후 동일 digest를 유지했다.
  CACHED 준비 시 download=0ms·model load=0ms, 준비 1.619ms를 확인했다.
- Nano는 실제 Orin Nano, `agx` 역할은 RTX 5060 Ti, `spark` 역할은 RTX 5080이다.
  대체 서버 결과를 AGX Orin/DGX Spark 실장비 결과로 설명하지 않는다.
- 현재 화면의 각 실행은 **Nano + 선택한 원격 1대**다. 세 노드 전체 Always-On 및
  AGX→Spark 연쇄 배치 비교가 구현·검증됐다는 뜻이 아니다.

## 실행 전 조건

1. 클러스터 승인 webhook과 대상 노드가 정상인지 확인한다.
2. 동일 모델 digest와 GPU backend, worker API 버전을 각 장비에서 확인한다.
3. 원격 GPU의 기존 예약 소유자를 확인한다. 유휴 GPU 사용률만 보고 빌리지 않는다.
4. 기존 서비스를 일시 중지할 경우 승인된 대상과 원래 replica·Ready 상태를 기록한다.
   시연 종료·실패 뒤 원래 상태를 복구하고 실제 replica와 Ready를 함께 확인한다.
5. Nano와 선택 원격의 관리 API가 살아 있고 active_requests·queue_length가 0이어야 한다.

## 로컬 화면 점검

저장소 루트에서 별도 결과 디렉터리를 사용한다. 이 서버는 실제 worker 주소를 조회한다.
시연 시작은 모델 activate/deactivate와 실제 inference를 수행하므로 단순 화면 확인 시
시작 버튼을 누르지 않는다.

```bash
rtk env HOST=127.0.0.1 PORT=18102 DEMO_DATA_DIR=/tmp/llama-demo-local python3 qualification/llama-offloading/demo.py
```

브라우저에서 `http://127.0.0.1:18102`를 연다. 서버 종료는 실행 터미널에서 Ctrl+C.
진행 중 서버가 종료되면 기록은 interrupted로 표시되며 자동 요청 재전송은 없다.
worker의 잔여 요청과 모델 상태는 별도로 확인해야 한다.
자동 준비 배포에서는 영속 GPU 세션이 있는 경우 잔여 원격 요청을 기다리고 복원한다.

## 배포 명령

아래는 승인 webhook 복구와 GPU 소유권 확인 **후** 수행한다. dry-run 실패 시 중단한다.

```bash
rtk kubectl --context=kubernetes-admin@kubernetes apply --dry-run=server -f qualification/llama-offloading/demo-k8s/gpu-access.yaml
rtk kubectl --context=kubernetes-admin@kubernetes apply -f qualification/llama-offloading/demo-k8s/gpu-access.yaml
rtk bash -o pipefail -c 'rtk kubectl kustomize --load-restrictor=LoadRestrictionsNone qualification/llama-offloading/demo-k8s | rtk kubectl --context=kubernetes-admin@kubernetes apply --dry-run=server -f -'
rtk bash -o pipefail -c 'rtk kubectl kustomize --load-restrictor=LoadRestrictionsNone qualification/llama-offloading/demo-k8s | rtk kubectl --context=kubernetes-admin@kubernetes apply -f -'
rtk kubectl --context=kubernetes-admin@kubernetes rollout status -n llama-offload-eval deployment/llama-demo --timeout=60s
```

배포 주소: `http://llama-demo.192.168.0.56.sslip.io`.
Deployment Ready와 HTTP 응답을 확인하기 전에는 배포 완료로 안내하지 않는다.
자동 준비 배포의 전용 SA만 승인된 worker scale과 센서 Application 임시 override를 변경한다.
중간에 RBAC·PVC를 제거하지 않는다. 복원 완료를 먼저 확인하고 기능을 비활성화한다.

## 시연 절차와 합격 증거

1. Nano-only → Cached 비교를 선택한다. 두 실행 모두 1→12→2 req/s,
   10→20→10초, 동일 prompt와 최대 8토큰의 270개 도착 스케줄을 사용한다.
2. 평시 Nano 응답과 원격 CACHED를 관측한다.
3. 부하 구간에서 대기열·TTFT·tokens/s 압력의 2초 지속과 예상 이득 15% gate를 확인한다.
4. pressure_detected → activation_started → ready → first_remote_response 순서를 확인한다.
5. 원격 응답의 실제 노드 ID·모델 digest·요청 ID와 전송 1회를 JSON에서 대조한다.
6. 요청이 모두 끝난 후 원격의 마지막 완료 시점을 기준으로 30초 유휴를 기다린다.
   released 이벤트, 모델 미적재와 CACHED/COLD 상태를 확인한다.
7. 성공·오류 수와 계획 요청 수를 대조하고 p95 지연·처리량을 비교한다.
   오프로딩 동작 성공과 성능 향상은 별도로 판정한다.
8. CSV/JSON을 내려받고, 빌린 GPU가 있다면 원 소유 서비스를 복구한다.

## 측정 경계와 남은 검증

- 실제 지연은 예정 도착→응답 완료다. 부하 생성기의 스케줄 지연과 컨트롤러 대기도 포함한다.
- TTFT는 worker 측 첫 토큰 시간 + 컨트롤러 대기다. 네트워크 전달 구간은 제외하며
  브라우저 스트리밍 TTFT가 아니다. 스트리밍 E2E TTFT는 후속 계측이 필요하다.
- 오류 요청은 지연 분위수에서 제외하고 오류 수로 반드시 함께 표시한다.
- CACHED는 모델 runner/GPU 적재 해제이며 관리 API·Pod·Kubernetes GPU 예약 해제와 다르다.
- activation 예측값은 이전 대체 서버 시험의 추정치다. 실제 activation 이벤트 값과
  혼동하지 않으며 현재 환경 재측정과 break-even 비교가 필요하다.
- 현재 검증은 Nano+RTX 5080의 두 회차와 기록 재생이다. 실제 AGX Orin/DGX Spark,
  세 노드 연쇄 배치, Always-On/Cold live 비교, 활성화 도중 장애·강제 종료 복구,
  스트리밍 E2E TTFT는 후속 범위다. 버튼·자동 예약 반환 검증은 아래 후속 기록과 구분한다.
