# Nano–AGX 서비스 연속성 기준과 실행 절차

**최신 판정(2026-09-08): SD 기반 v2의 실제 왕복 10회·Nano 단독 비교 10회 합격.**
총 17,520건이 정상 완료됐으며, 아래의 v1·SD smoke·v2 첫 실패는 당시 상태를 보존한 이력이다.
최종 수치와 범위는 [v2 결과](results/2026-09-08-nano-agx-v2/attempt-02/README.md)와
이 문서 마지막 절을 따른다. 이번 결과는 격리된 시험 CLI의 자격이며 운영 gateway 완료를 뜻하지 않는다.

## 목표와 현재 구현 경계

Llama 3.2 1B 데모로 Nano → 실제 AGX Orin → Nano의 **신규 요청 전체 전환**을
검증한다. AGX는 CACHED에서 시작하고 모델을 GPU에 올린 뒤에만 신규 요청을 받는다.
Nano에서 이미 시작한 요청은 완료한다. 부하 감소 후 Nano로 복귀하고 AGX 요청을
모두 마친 뒤 모델 메모리를 해제한다. 모델 해제는 Pod 또는 GPU 공유 슬롯 반환이 아니다.

이번 구현은 실측 기준 수립과 자격시험용 CLI다. 외부 서비스용 범용 gateway, NEXUS의
자동 오프로딩, Nano 전원/네트워크 전체 장애, 실행 중 LLM/KV-cache 이전을 완료한 것이 아니다.
기존 `demo.py`와 RTX 버튼 시연의 대상·기록을 바꾸지 않는다. 새 엔진은 기존 `worker.py`의
동일 모델·생성 API를 재사용하며 격리 Service 경로에서 동작한다.

ELI5: Nano가 혼자 일을 감당하기 어려워지면 AGX를 준비한다. 준비가 끝나야 새 일을
AGX에 맡긴다. 일이 줄어 Nano 혼자 감당할 수 있으면 다시 돌려준다. 여기서 성공은
불이 켜졌다는 표시가 아니라 실제 요청의 결과가 나왔다는 기록으로 확인한다.

## 파일과 운영 책임

- `continuity_policy.py`: 실측 baseline 검증·immutable 정책 동결·상태 전이.
- `continuity_runner.py`: Service 접속, 실제 스트리밍 TTFT, 부하 발생·단일 대상 dispatch,
  baseline/왕복 실행, SQLite WAL 기록·중단 복구. 한 요청은 한 번만 전송한다.
- `continuity_report.py`: 요청 ID·모델·실제 노드·전환/복귀/해제·지연 합격 판정 및 대응 비교.
- `nano-agx-k8s/`: `llama-continuity-test` 전용 별도 수동 배포. 운영자는 시험 시작·정지와
  원장 회수를 소유한다. Argo CD/EdgeX/기존 센서 운영 경로에는 연결하지 않는다.

Kubernetes Service `llama-nano`와 `llama-agx`는 고정 selector를 사용한다. EndpointSlice,
Service selector, production route를 동적으로 수정하지 않는다. 시험 client가 정책에 따라
두 Service 중 하나를 선택한다. API 준비 probe는 관리 API 생존이며 모델 READY는 별도다.
Nano 전용 측정 API는 기존 Nano Ollama loopback runtime을 사용하며 `CONTINUITY_SOURCE=1`로
모델 unload/CACHED 전환을 차단한다. 기존 RTX 시연은 시험 동안 실행하지 않는다.
AGX는 실제 `etri-dev0005-jetagx`에 고정하고 `nvidia.com/gpu.shared=1`을 요청한다.
두 worker는 고정 hostNetwork와 ClusterFirstWithHostNet을 사용한다. 중앙→AGX Pod CIDR
직접 경로의 timeout 때문에 기존 Llama의 host-network 경계를 재사용하며 접속은 Service DNS다.
서비스 워크로드에 privileged·hostPath를 추가하거나 호스트 runtime 설정을 바꾸지 않는다.
AGX 모델은 SD local PV의 `llama-agx-cache-sd` PVC(100Gi 요청)를 사용한다. 기존 eMMC의
`llama-agx-cache` PVC(6Gi)는 복구용 원본으로 보존한다. 중앙 요청 원장 PVC는 2Gi다.

## 측정 및 고정 조건

모델 digest, 노드별 Ollama image digest, 실제 노드 identity, 동일 prompt, 최대 8토큰,
seed 42, temperature 0, context 2048, worker concurrency 1을 `CONTRACT`로 고정한다.
배포 이미지ID는 live Pod 상태로 별도 확인한다. GPU 계측 결측을 0으로 바꾸지 않는다.
GPU residency 근거가 없는 baseline은 정책으로 승격하지 않는다. Nano는 공식 이미지,
AGX는 같은 ARM64 원본에서 `cuda_v12`, `cuda_v13`, `cuda_jetpack5`만 제외한 이미지를 쓴다.
남은 실행 파일·`cuda_jetpack6` 라이브러리는 원본 바이트 그대로이며 버전은 모두 0.33.2다.
실제 AGX JetPack 7 호스트에서 Orin CUDA 발견과 모델 17/17 레이어 GPU 적재를 확인했다.
이 단일 모델의 확인을 모든 JetPack 7 모델·라이브러리 호환성으로 일반화하지 않는다.

측정값은 client의 monotonic clock을 사용한다. `/generate/stream`의 NDJSON `token`을
실제로 수신한 시점과 마지막 `result`를 받은 시점을 기록한다. 입력 예정 도착 시각부터
측정하여 client 대기·네트워크·worker 대기가 모두 포함된다. 기존 `/generate` JSON API는
유지한다. EOF/오류/identity 불일치는 `unknown`이며 성공 또는 자동 재전송으로 바꾸지 않는다.
HTTP 200만으로 추론 성공을 판단하지 않는다. 최종 result와 ID·node·model을 검증한다.

- Nano/AGX 시험 추론 후 노드별 저부하 30건을 **4초 간격(0.25 req/s)**으로 3회 측정한다.
  연속 직렬 호출은 GPU가 계속 예열된 상태이므로 유휴 뒤 지연을 포함하는 저부하 기준선으로 쓰지 않는다.
  예정 도착 간격과 최소 120초 표본 구간을 검증해 잘못 표시된 연속 호출 표본을 거부한다.
- 저부하 측정을 마친 뒤 0.25/0.5/1/2/4/8/12/16 req/s 순서로 각 3회 측정한다.
  노드별 첫 불합격 단계의 세 반복까지 보존하고 더 높은 부하는 생략한다. 이미 찾은 처리 한계
  위로 불필요한 거절 부하를 추가하지 않으며, 이 종료 규칙도 측정 계약에 고정한다.
- AGX의 마지막 통과 단계가 Nano C×120%보다 작으면, 그 **정확한 요청률**을 별도 admission
  표본으로 3회 측정한다. 예를 들어 양쪽 4 req/s 통과·8 req/s 불합격만으로 AGX의
  4.8 req/s 수용 여부를 단정하지 않는다. 세 반복의 실제 처리·지연·GPU 증거가 모두
  통과한 경우에만 AGX의 검증 처리량 하한을 이 값으로 올린다. 보간한 값은 사용하지 않는다.
  각 부하 단계는 30초이며 회차별 장비 순서를 교대한다. 네트워크 시간은 서비스 비용에 포함한다.
- 개발 지연 기준 S = 양쪽 저부하 p95 TTFT 중 큰 값 × 2. p95는 nearest rank다.
- 지속 가능 처리율 C는 3회 모두 S를 만족하고 도착 구간 내 완료 비율 ≥98%, 후반
  outstanding 평균이 전반 평균보다 0.5건 넘게 증가하지 않은 최대 시험 rate다.
  그보다 높은 탈락 단계도 있어야 한다. 모두 통과했거나 모두 탈락하면 측정 범위 부족이다.
  이 정의는 30초 시험 범위의 공학적 기준이며 장시간 처리율 보증이 아니다.
- AGX cache-only 활성화→identity가 맞는 시험 추론 성공까지 10회 측정한다.
  실제 다운로드가 발생하면 cached activation 기준에서 탈락한다.
- 바쁜 상태의 처리시간은 각 노드에서 직렬 연속 호출 30건×3회로 별도 측정한다.
  회차별 p95 전체 응답시간의 최댓값을 사용하며, 유휴 뒤 지연을 포함한 저부하 표본은 S에만 쓴다.
- AGX가 Nano C의 120% 부하를 수용하지 못하거나 준비 중 Nano 처리를 포함한 예상 이득 15%가
  성립할 수 없으면 `AGX_NOT_QUALIFIED`. 정책 파일을 만들지 않는다.
- 완료 baseline digest와 정책 본문 digest를 고정한다. run은 baseline으로 정책을 다시
  계산해 동일성을 확인한다. 임계값 수정/이전 RTX 값 대입/실패 baseline 승격은 거부한다.

## 전환·복귀·해제 기준

| 동작 | 기준 |
|---|---|
| AGX 활성화 | 전체 유입량 ≥ Nano C×85% 또는 예상 지연 > S가 5초 지속하고 예상 이득 ≥15% |
| 전환 | 활성화와 실제 시험 추론 성공, 동일 모델/실제 AGX identity, 3초 이내 READY 관측, 전체 유입량 수용 가능 |
| 복귀 준비 | 전체 유입량 ≤ Nano C×60%가 30초 지속, 정상 전환 이후 60초 cooldown 경과 |
| 복귀 | Nano 시험 추론 성공과 최신 READY를 다시 확인한 뒤 신규 요청 전환 |
| 해제 | 실제 AGX 진행·대기 요청 0, 마지막 원격 완료부터 30초 유휴, Nano 정상 확인 |
| 원격 장애 | 정상 cooldown과 무관하게 신규 요청을 Nano로 제한 처리; 불확실한 요청은 재전송하지 않음 |

전체 유입량은 최근 10초의 **거절 요청까지 포함한 도착 수**로 계산한다. Nano 사용률이
전환 때문에 낮아졌다는 사실을 복귀 조건으로 쓰지 않는다. 오래된 관측은 dwell을 초기화하고
전환을 보류한다. activation 실패는 현재 회차에서 반복 시도하지 않는다. 복귀 probe 실패는
AGX 경로를 유지하고 모델을 해제하지 않는다.

v2 예측은 같은 대기 요청과 같은 미래 도착 스케줄에 대해 두 경로를 비교한다.
한 경로는 Nano만 처리하고, 다른 경로는 AGX 활성화 중 Nano가 계속 처리하다가 준비 시점부터
새로 접수한 요청을 AGX로 보낸다. 기존 Nano 대기열과 진행 요청은 Nano에서 마친다. 양쪽 모두 FCFS·노드별 동시 처리 1개다.
비교 구간은 `실측 activation 최대시간 + 기존 cooldown 60초`이며, 현재 관측 유입량이
그동안 유지된다는 개발용 가정이다. 구간 안에 도착한 모든 요청의 완료까지 계산한다.
준비 구간과 기존 대기열을 포함한 요청별 응답시간 합계가 15% 이상 줄어야 활성화한다.
관측값이 미래 부하를 보장하지 않으므로 실제 동작 성공과 대응 시험의 성능 개선을 별도로 보고한다.

queue limit은 activation 동안의 `Nano C×120%` 도착 수에 Nano가 S 동안 처리할 건수를
더한 유한 값이다. 한계를 넘으면 접수 거절을 기록하고 정상 왕복 시험은 불합격이다.
대기열 크기로 지연 기준을 바꾸지 않는다. 실제 전환 시 기록에 예측 구간·요청 수·준비 구간에 Nano로 접수된
요청 수·두 경로의 평균 응답시간·예측 이득을 남긴다.

v1의 저부하 전체 응답시간 기반 정적 대기열 식과 eMMC 기준선은 역사 자료로 남긴다.
v2 계약은 예측 모델, busy 표본 방법과 SD UUID를 포함한다. 이전 baseline을 새 정책으로
다시 포장하지 않으며 `live-calibration/v2`로 처음부터 측정한다.

## 합격 시험

정책 동결 후 저부하 30초(C×50%) → 고부하 120초(C×120%) → 복귀 120초(C×50%)를
10회 실행한다. 각 회차는 동일 스케줄의 Nano-only와 대응하며 실행 순서를 교대한다.
전체 시험은 기준선 약 25분 이상, 왕복 10쌍 약 90분 이상에 drain/activation 시간이 추가된다.
첫 후보 회차가 합격선을 벗어나면 verdict를 저장하고 중단한다. 실패한 수치에 맞춰 기준을 바꾸지 않는다.
실제 소요시간을 줄이기 위해 부하나 반복 수를 몰래 바꾸지 않는다.

- 정상 왕복 10회: 모든 예정 요청 집계, 접수 거절·결과 누락·오류·중복 확정 0.
- 실제 AGX 응답 → 실제 Nano 복귀 응답 → CACHED·model_loaded=false·model_vram_mib=0
  순서를 확인한다. Ready나 설정 변경만으로 성공하지 않는다.
- 정상 구간 p95 TTFT ≤ S. activation과 겹치는 요청의 최대 TTFT ≤ activation 최대시간＋S.
- 전체 응답시간/TTFT p95, 처리량, 최대 완료 공백, 오류·거절·확인 불가를 함께 보고한다.
  결과가 일부 빠진 비교는 `comparable=false`로 둔다. 동작 성공과 성능 개선은 별도다.
- 자동 회귀시험은 짧은 burst, 임계값 진동, stale/identity 오류, 활성화 실패, 원격 오류,
  복귀 probe 실패, busy 해제 차단, 늦은 READY 관측, 요청 전송 원장과 실제 streaming을 검증한다.
  이 자동시험을 실장비 장애주입 결과로 표시하지 않는다.

## 재현 명령

셸 명령은 rtk를 사용한다. 신규 시험 배포만 아래 경로로 조작한다. AGX의 기본 replica는 0이다.
시험 실행 중에는 apply/start.sh를 다시 실행하지 않는다. CLI의 원장 lock은 외부 kubectl apply까지 잠그지 않는다.
`nano-agx-k8s/start.sh`는 사전 점검 통과 후에만 배포·AGX 기동을 실행한다.
사전 점검은 Ready·Disk/Memory/PIDPressure, 모델 다운로드 임시 공간 3GiB와
AGX cold image 공간을 제외하고도 각각의 파일시스템에 20% 여유를 요구한다.
AGX 모델 3GiB는 SD 파일시스템에, cold image 예산은 eMMC root에만 차감한다.
기존 node exporter에서 정확한 SD mount/device/ext4와 쓰기 가능·오류 없음·여유를
읽으며, 미연결·관측 실패 시 root 공간으로 대체하지 않고 기동을 차단한다.
Git PV 경로·node affinity·PVC 연결·초기 컨테이너의 카드 식별 검사도 예산과 일치해야 한다. 새 이미지 공간은
실측 압축 layer 530,761,031바이트＋정규 파일 전개 상한 1,144,969,448바이트에
25% 여유와 256MiB 임시 공간을 더한 2,363,098,555바이트다. OCI archive를 호스트 디스크에
복사하지 않고 containerd로 직접 스트리밍하는 조건이다. 기존 전체 이미지에 이 예산을
적용하지 못하도록 manifest digest도 검사한다. 정확한 이미지의 runtime이 실제 AGX에서
Running/Ready이면 이미 사용 중인 이미지 공간은 중복 차감하지 않는다.
모델 3GiB 여유는 추가 다운로드를 위한 보수적인 **신규 기동 기준**이다. 실행 중인 서비스의
현재 DiskPressure 판정과 다르며, 기준이 부족하면 start.sh는 기동을 차단한다.

AGX 이미지는 `imagePullPolicy: Never`인 운영자 사전 적재 방식이다. 임의의 registry나
전체 이미지로 fallback하지 않는다. 빌드는 운영 PC에서 수행한다.

```bash
rtk proxy python3 qualification/llama-offloading/nano-agx-k8s/build-runtime.py /절대경로/runtime-artifacts
```

`runtime-provenance.json`의 image가 `continuity_policy.py`의 `AGX_RUNTIME_IMAGE`와 같아야 한다.
인가된 AGX 관리 셸에서 다음 containerd 명령의 stdin에 `runtime.oci.tar`를 직접 전달한다.
이미지 적재 전에 cold 사전 점검을 통과해야 한다. 2026-09-08에는 고정 AGX 노드의 일회성
읽기 전용 호스트 진단 Pod를 통해 `kubectl exec -i`로 전달했고, 적재 후 진단 Pod를 삭제했다.
이 관리 작업을 서비스 manifest나 UI의 임의 hostPath/command 입력으로 노출하지 않는다.

```bash
rtk proxy ctr -n k8s.io images import --platform linux/arm64 --digests \
  --base-name localhost/qualification/ollama-jetson --label io.cri-containerd.image=managed -
```

일반 서버 빌드 산출물은 `/home/jinuk/codex-work/artifacts/nano-agx-runtime-20260908/`에 보존했다.
실제 GPU/backend 증거와 원본→파생 이미지 관계는 아래 결과 디렉터리에 있다.

```bash
rtk proxy sh -c 'kubectl kustomize qualification/llama-offloading/nano-agx-k8s --load-restrictor LoadRestrictionsNone > /tmp/nano-agx-continuity.yaml'
rtk proxy kubectl apply --dry-run=client -f /tmp/nano-agx-continuity.yaml
rtk proxy kubectl apply -f /tmp/nano-agx-continuity.yaml
rtk proxy python3 qualification/llama-offloading/continuity_preflight.py
rtk proxy bash qualification/llama-offloading/nano-agx-k8s/start.sh
rtk proxy kubectl exec -n llama-continuity-test deploy/continuity-controller -- python /app/continuity_runner.py preflight
rtk proxy kubectl exec -n llama-continuity-test deploy/continuity-controller -- python /app/continuity_runner.py calibrate
rtk proxy kubectl exec -n llama-continuity-test deploy/continuity-controller -- python /app/continuity_runner.py freeze
rtk proxy kubectl exec -n llama-continuity-test deploy/continuity-controller -- python /app/continuity_runner.py run
rtk proxy kubectl exec -n llama-continuity-test deploy/continuity-controller -- python /app/continuity_runner.py verify
```

`calibrate`/`run`은 실제 inference와 고정된 worker 활성화·해제를 수행한다. 이미지 다운로드,
Service 통신, Nano/AGX runtime 및 기존 시연 유휴를 확인한 뒤 실행한다. 정책 미생성 상태는
자동으로 채우지 않는다. `--baseline`, `--policy`, `--data`로 새 증거 경로를 지정할 수 있지만
같은 controller의 `/data/operator.lock`은 공유하여 중복 실행을 차단한다. baseline/policy/회차
JSON은 덮어쓰지 않는다. 원시 요청은 SQLite에 전송 전과 완료 후 저장한다.

재시작 시 unfinished record가 있으면 새 시험을 차단한다. `recover`는 Nano 시험 추론과
AGX drain/모델 해제만 확인하고 원장을 `interrupted_recovered`로 남긴다. 요청을 재생하지
않으며 중단된 회차를 성공으로 계산하지 않는다. API/노드 장애 중에는 복구 완료를 주장하지 않는다.

코드 검증은 requirements-analysis.txt의 분석 의존성이 있는 venv에서
`python -m unittest discover -s qualification/llama-offloading/tests -q`로 수행한다.
실장비 결과·현재 배포 상태는 `results/2026-09-08-nano-agx-continuity/`에 따로 기록한다.

## 2026-09-08 1차 실행: 저장공간 부족으로 중단

- 별도 namespace에 controller·Nano 측정 API·실제 AGX runtime과 고정 Service를 배포했다.
  양쪽 Service DNS에서 실제 node identity·관리 runtime 응답을 확인했다.
- 최초 AGX Pod-network 주소는 중앙 client에서 timeout이었고 Pod 내부 API는 정상이다.
  고정 hostNetwork로 바꾼 뒤 Service DNS 경로가 정상 응답했다.
- 동일 pinned ARM64 Ollama 이미지의 pull은 처음 연결 reset으로 실패한 뒤 재시도 성공했다.
  실제 관리 runtime 버전은 0.33.2다. 관리 API 정상은 GPU 모델 추론 검증이 아니다.
- 기준선 준비 도중 AGX DiskPressure가 재발하고 시험 Pod가 퇴거됐다. baseline은
  `failed`, 측정 batch 0개·activation 표본 0개다. GPU 모델 자격·수치 동결·10회 왕복은
  **미완료**이며 policy.json이나 합격 성능값을 만들지 않았다.
- AGX replica를 0으로 내리고 종료된 시험 Pod와 이번에 만든 모델 PVC/PV를 정리했다.
  기존 Nano Ollama·센서 workload는 유지한다. controller의 실패 원장 PVC는 보존했다.
- 중단 후 AGX 여유 약 16GB는 cold runtime＋모델 다운로드＋20% 여유 기준을 충족하지
  않는다. 최종 조회에서 DiskPressure는 False로 해제됐다. 충분한 저장공간 확보 후 새 baseline
  파일로 재시도한다.
  호스트 임의 파일 삭제·disk-pressure toleration 추가·CPU 대체값 채우기는 수행하지 않았다.

1차 로컬 검증: 기존 및 신규 unittest **76개 통과**. 분석 의존성은
`requirements-analysis.txt`에 고정된 버전을 별도 venv에 설치해 사용했다.
Nano Service 스트리밍 실제 1건의 identity와 결과를 확인했으나 기준선·성능 자격 표본으로 쓰지 않는다.

1차 종료 시 AGX replica=0이며 빈 모델 PVC 정의만 Pending으로 다시 생성했다.
기존 실패 원장과 요청·상태 근거는 보존했다. controller의 세 Python 모듈 SHA-256이
로컬 파일과 일치함을 확인했다. 사전 점검 실패 시 start.sh가 exit 2로 끝나고 AGX가
기동되지 않는 것을 실제로 검증했다. 상세 최종 상태는
[검증 JSON](results/2026-09-08-nano-agx-continuity/verification.json)을 따른다.

## 2026-09-08 2차 실행: 저장공간 복구

- AGX는 추가 SSD 없이 eMMC root 57,806,061,568바이트를 사용했다.
- APT archive lock을 획득한 뒤 완료된 다운로드 캐시 `.deb` 385개, 1,985,751,772바이트만
  정리했다. 설치된 패키지·기존 시험 파일·호스트 containerd 설정은 보존했다.
- 위 파생 이미지로 압축 layer 용량을 약 2.78GB에서 0.53GB로 줄였다. cold 사전 점검
  통과 후 스트리밍 import·실제 AGX Pod 2/2 Ready·CUDA 모델 추론을 확인했다.
- 원본 실패 기록은 그대로 두고 `/data/attempt-02/`에 새 기준선을 시작했다.
- 관련 자동시험 **81개 통과**. 이미지 경로 필터와 실제 노드·정확한 이미지·Running/Ready
  조건이 맞을 때만 이미 할당된 저장공간을 인정하는 회귀시험을 포함한다.
- 근거: [저장공간 정리](results/2026-09-08-nano-agx-continuity/storage-recovery.json),
  [이미지 provenance](results/2026-09-08-nano-agx-continuity/runtime-provenance.json),
  [실제 Pod](results/2026-09-08-nano-agx-continuity/slim-runtime-live.json),
  [GPU 적재](results/2026-09-08-nano-agx-continuity/slim-gpu-proof.log).

## 저부하 표본 방법 보정

2차 중간 기록에서 연속 호출 저부하 p95는 두 노드 약 42ms였지만, 4초 간격 요청의
p95는 약 200ms 이상이었다. 연속 직렬 호출을 저부하로 쓰면 유휴 후 지연을 누락한다.
이 구현 문제를 확인해 2차 측정을 중단·복구하고 기준선으로 사용하지 않았다.
[중단 원장](results/2026-09-08-nano-agx-continuity/attempt-02-invalid-low-sampling.json)은
`interrupted_recovered`로 보존했다. 처리 중이던 요청을 다시 보내지 않았으며 AGX의
모델 해제를 확인했다. 정책 수치는 아직 동결하지 않았다.

수정한 4초 간격 표본 방식으로 `/data/attempt-03/`에서 처음부터 다시 측정한다.
기존 측정값의 label·타임스탬프를 고치거나 서로 다른 측정 계약을 합치지 않는다.

완료된 3차 기본 원본은 `attempt-03-baseline.json`으로 별도 보존한다. 추가 admission
측정은 원본 ID·digest를 `extended_from`에 남긴 새 기록으로 저장하며 원본을 덮어쓰지 않는다.
같은 모델·입출력·노드·runtime 계약에서만 확장하며, 향후 기본 calibrate도 이 검사를 수행한다.

## 최종 판정: 기준선 완료, 현재 예측식의 자격시험 불합격

실제 Nano와 AGX에서 저부하 6개·부하 36개 구간, AGX 추가 admission 3개 구간과
cache-only activation 10회를 완료했다. **자동 전환·복귀 10회는 실행하지 않았다.**
정책 동결 단계가 `AGX_NOT_QUALIFIED: measured whole-queue gain cannot reach 15%`로
종료해 policy.json을 생성하지 않았다.

| 측정 항목 | Nano | 실제 AGX Orin |
|---|---:|---:|
| 4초 간격 저부하 TTFT p95의 세 반복 최댓값 | 136.4ms | 270.8ms |
| 현재 예측식의 서비스시간(저부하 전체 응답 p95 최댓값) | 384.7ms | 454.9ms |
| 3회 통과한 공통 부하 단계 | 4 req/s | 4 req/s |
| 첫 불합격 부하 단계 | 8 req/s | 8 req/s |
| 정확한 120% 부하 추가 확인 | 기준 4 req/s | 4.8 req/s, 총 432/432건 성공 |

AGX의 4.8 req/s 부하에서는 반복별 p95 TTFT 33.6~36.5ms, 전체 응답 p95
147.4~154.4ms였다. 따라서 이 결과를 “AGX가 항상 Nano보다 느리다”로 해석하면 안 된다.
유휴 뒤 지연을 포함한 현재의 보수적인 고정 서비스시간 예측식이 자격시험을 통과하지
못했다는 뜻이다. 해당 식의 `0.85×Nano 서비스시간−AGX 서비스시간`은 −127.9ms여서
대기열을 늘려도 그 식에서는 15% 이득이 성립하지 않는다. 유휴 지연과 부하 중 처리시간을
구분하는 예측 모델의 타당성 검토가 남아 있다. 수치를 바꿔 이 실행을 합격으로 만들지 않았다.

TTFT 기준 S는 541.6ms다. 캐시에서 실제 추론 성공까지 10회 모두 다운로드 0ms였지만
활성화는 8.878~8.981초 걸렸다. 따라서 무중단 전환·복귀가 입증됐다고 보고할 수 없다.
이후 판단식을 바꾸면 새 정책 버전과 별도 왕복 검증을 적용해야 한다.

종료 시 AGX는 CACHED·model_loaded=false·model_vram_mib=0·진행/대기 요청 0,
Nano는 inference_ready=true다. AGX 관리 Pod와 공유 GPU 슬롯 1개는 유지한다.
기존 Nano 데모·센서 Pod의 UID·컨테이너 ID·재시작 횟수는 같으며 전체 7개 노드는 Ready다.
실패·중단·최종 원장을 모두 보존했고 미완료 원장은 없다. 일회성 호스트 정리 Pod는 삭제했다.

최종 APT 정리는 완료된 `.deb` 1,985,751,772바이트와 재생성 가능한 binary index
118,905,390바이트다. 기존 서비스·설치 패키지·시험 파일을 유지했다. 이미지와 모델이
적재된 뒤 여유 공간은 약 14.87GB이며, 정확한 runtime이 Running인 상태의 최종 사전 점검도 통과했다.

- [측정·판정 요약](results/2026-09-08-nano-agx-continuity/calibration-summary.json)
- [기본 기준선 원본](results/2026-09-08-nano-agx-continuity/attempt-03-baseline.json)
- [원본 연결을 보존한 admission 확장](results/2026-09-08-nano-agx-continuity/attempt-03-baseline-with-admission.json)
- [코드·원장·기존 서비스 최종 검증](results/2026-09-08-nano-agx-continuity/verification-retry.json)
- [최종 저장공간 사전 점검](results/2026-09-08-nano-agx-continuity/preflight-retry-final.json)


## 2026-09-08 SD카드 포맷 및 모델 저장소 전환

사용자의 명시적 포맷 승인 후 실제 AGX의 비어 있던 128GB SD 파티션
`/dev/mmcblk1p1`만 exFAT에서 ext4로 포맷했다. eMMC root와 부팅 파티션은 유지했다.
포맷 직전 장비명·파티션 크기 127,982,895,104바이트·기존 exFAT UUID·미연결 상태를
다시 확인했다. 포맷은 일회성 호스트 관리 작업이며 `start.sh`나 서비스에 포함하지 않는다.

- 새 UUID: `c6889d5e-37bb-4b07-8e0b-757d3de8c877`, label: `agx-model-cache`.
- 호스트 경로: `/srv/agx-model-cache`; 모델 디렉터리: `/srv/agx-model-cache/ollama`.
- `/etc/fstab`에 UUID로 등록했다. `nofail,x-systemd.device-timeout=10s`를 사용하고
  원본은 `/var/backups/agx-sd-20260908/fstab.before`에 보존했다.
  실제 적용 항목은 [마운트 기록](results/2026-09-08-nano-agx-continuity/sd-mount-setup.log)에 있다.
- [sd-storage.yaml](nano-agx-k8s/sd-storage.yaml)은 AGX로 제한된 static local PV,
  `Retain` 회수 정책과 전용 PVC를 정의한다. PVC의 100Gi 요청은 디렉터리 사용량의
  강제 quota를 뜻하지 않는다. 실제 파일시스템 여유를 별도로 점검한다.
- 카드가 연결되지 않은 root mountpoint에는 `ollama` 디렉터리가 없다.
  자동 디렉터리 생성이나 eMMC fallback을 하지 않는다. 초기 컨테이너는 카드 안의
  `.storage-uuid`를 검사한 뒤에만 runtime을 시작한다.
- 모델 6개 파일(합계 1,321,099,189바이트)의 원본/복사본 SHA-256이 모두 일치했다.
  이전 eMMC 모델 PVC는 복구용으로 남겼으므로 현재 원본 약 1.32GB는 계속 eMMC를 사용한다.
  이미지 저장소/containerd 경로는 변경하지 않았다.

마운트를 정상 해제한 상태에서 모델 경로 부재와 startup gate의 exit 2를 확인했다.
이후 fstab에서 생성한 mount unit으로 다시 연결해 UUID와 저장된 marker를 확인했다.
실제 재부팅이나 실행 중 카드 분리 시험은 하지 않았다. 카드 재연결 시 같은 UUID와
mount 상태를 먼저 확인하며, 다른 카드로 교체하려면 UUID·PV·초기 검사 계약을 함께 갱신한다.
[local PV의 노드 결합 특성](https://kubernetes.io/docs/concepts/storage/volumes/#local)에 따라
이 저장소를 다른 노드에서도 자동으로 사용할 수 있다고 가정하지 않는다.

AGX 시험 Pod만 재생성해 2/2 Ready를 확인했다. 실제 runtime의 `/models` mount는
SD 장치 `179:97`의 ext4 `/ollama`였다. CUDA에서 17/17 레이어를 적재했고,
고정 Service를 통한 AGX 추론 2건과 기존 Nano 추론 1건의 노드·모델·요청 ID가 일치했다.
**SD 연결 직후 활성화는 24.579초, 직후 반복은 24.463초**였고 다운로드는 두 번 모두 0ms였다.
기존 eMMC 기준선의 8.878~8.981초보다 길게 관측됐다. 이 두 건은 저장소 전환 smoke test이며
통제된 저장장치 비교나 새로운 정책 기준선이 아니다. 원인을 SD만으로 확정하거나
기존 활성화 상한을 새 저장소에도 그대로 적용하지 않는다.

현재 SD 여유는 약 122.76GB다. 종료 시 AGX는 CACHED·모델 VRAM 0이며 Nano는 정상 추론한다.
기존 Nano·센서·controller Pod의 UID/컨테이너 ID/재시작 횟수는 동일했고 7개 노드는 Ready였다.
관련 자동시험 84개를 통과했다. 일회성 호스트 관리 Pod는 삭제했다.
**자동 전환·복귀 10회와 정책 자격은 여전히 미완료**다. SD 전환 이후 성능 기준선은
새 증거 경로에 다시 측정해야 하며 이전 eMMC 측정값을 덮어쓰지 않는다.

- [포맷 기록](results/2026-09-08-nano-agx-continuity/sd-format.log)
- [모델 복사 해시](results/2026-09-08-nano-agx-continuity/sd-copy-verification.json)
- [미연결 차단·재연결 검증](results/2026-09-08-nano-agx-continuity/sd-remount-verification.json)
- [실제 runtime 저장 장치](results/2026-09-08-nano-agx-continuity/sd-runtime-mount.json)
- [첫 활성화](results/2026-09-08-nano-agx-continuity/sd-runtime-smoke.json) ·
  [반복 활성화](results/2026-09-08-nano-agx-continuity/sd-runtime-smoke-repeat.json) ·
  [GPU 적재 로그](results/2026-09-08-nano-agx-continuity/sd-gpu-proof.log)
- [최종 검증](results/2026-09-08-nano-agx-continuity/sd-verification.json) ·
  [최종 공간 점검](results/2026-09-08-nano-agx-continuity/sd-preflight-final.json)


## 2026-09-08 연속성 v2 검증 재개

SD 전환 후 사용자가 기존 오프로딩·복귀 작업 재개를 지시했다. 유휴 지연과 busy 처리시간을
분리하고, AGX 준비 중에도 Nano가 계속 처리하는 실제 실행 구조를 예측식에 반영했다.
15% 이득, 5초 지속, 85% 진입, 60% 이하 30초 복귀, 60초 cooldown, 30초 유휴 해제,
고정 Service와 cache-only 대기는 유지한다. 새 결과가 나오기 전 이를 합격으로 표시하지 않는다.

요청 dispatcher는 고정 50ms sleep 대신 완료 알림과 다음 도착 시각에 깨어나도록 바꿨다.
기존에는 직렬 요청 완료 뒤 다음 50ms tick까지 쉬어 실제 runtime과 다른 인위적 처리 한계를
추가했다. 요청 ID와 전송 의도는 여전히 전송 전에 영속 기록한다. 대응 control의 증거가
불합격이면 전체 10쌍 보고서도 합격하지 않도록 판정을 보강했다.


v2 왕복 실행 전 추가 점검에서 접수 시점의 노드 지정을 고정하도록 수정했다.
전환 전에 접수된 Nano 대기 요청까지 AGX로 옮기지 않는다. 준비 이후의 새 요청은 AGX가
처리하고 기존 Nano 요청은 병렬로 drain한다. 복귀도 같은 원칙이며 AGX의 진행 요청뿐
아니라 클라이언트 대기 요청도 0이어야 모델을 해제한다. 정상 시험은 접수 시점의 경로와
실제 실행 경로까지 검사한다. 원격 장애 때에만 아직 전송하지 않은 원격 요청을 Nano로
재지정하며, 이미 전송한 불확실한 요청은 재실행하지 않는다. 이 동작은 frozen policy의
`routing_semantics=pin-at-admission-drain-existing/v2`로 명시한다.

기준선은 GPU/서비스 측정 입력이 같은 상태에서 완료했다. 접수·drain과 보고서 보강은
기준선 수집 함수를 변경하지 않았고, 아직 어떤 v2 왕복 정책도 배포·시험하지 않은 시점에
적용했다. 측정 당시 코드와 왕복 실행 코드 해시는 별도 보존한다. control 결과에 오류나
누락이 있어 비교가 불가능하면 해당 verdict를 남기고 후속 반복도 중단한다.


### v2 첫 왕복: 동작 성공, 지연 불합격 및 기록 경로 수정

`v2-sd-01`의 첫 control·candidate는 각각 876건 모두 성공했고 후보는 실제 AGX 응답,
Nano 복귀, SD CACHED·모델 VRAM 0까지 순서대로 확인했다. 다만 후보 정상 구간 p95 TTFT가
6,640.0ms로 S 548.4ms를 넘어 실패했고, 예정된 나머지 반복은 자동 중단했다.
[첫 실행 원본·verdict](results/2026-09-08-nano-agx-v2/attempt-01/)을 보존한다.
이것은 10회 왕복 합격이나 무중단 보장의 근거가 아니다.

실행 후반에는 매 접수·전송·첫 토큰·완료마다 약 1.6~2.15MB 누적 JSON 전체를
SQLite에 다시 저장했다. 실제 기록 기반 로컬 진단에서 전체 저장 중앙값 39.44ms,
변경 항목 저장 중앙값 4.11ms를 확인했다. 측정된 runtime 처리량에 이러한 추가 대기를
계속 더하는 문제가 있어 `entries` 테이블의 요청/이벤트/표본별 작은 트랜잭션으로 수정했다.
SQLite WAL·synchronous=FULL은 유지한다. dispatch 행과 이벤트는 같은 트랜잭션으로
전송 전에 commit하고, 재시작 시 delta를 합쳐 접수/전송 상태를 복구한다. 실행 종료 시
전체 결과와 delta 정리는 원자적으로 확정한다. `records.body`만으로는 진행 중인 최신
요청 목록을 알 수 없으며 `Journal.latest()`/`unfinished()`로 재구성해야 한다.

93개 자동시험에 전송 전 실제 영속 의도 확인과 재시작 후 대기/전송 요청 복구 검증이
포함된다. [진단 근거](results/2026-09-08-nano-agx-v2/incremental-journal-diagnostic.json)는
로컬 기록 비용 비교이며 Jetson 성능 향상값으로 사용하지 않는다. 모델·저장소·부하·정책
수치를 변경하지 않았으므로 완료 기준선과 동결 정책은 유지하고, 새 `v2-sd-02`에서 control과
candidate를 모두 처음부터 실행한다. 첫 실패의 성공 구간을 골라 새 10쌍에 섞지 않는다.

### v2 최종 판정: 동일 정책으로 10쌍 합격

2026-09-08 22:47 KST에 `v2-sd-02`의 20회 실행이 exit 0으로 종료됐다.
같은 baseline·정책으로 `verify`를 다시 실행해 `passed=true`를 확인했다.
반복마다 30초 2 req/s → 120초 4.8 req/s → 120초 2 req/s의 876건을 보냈고,
짝수 반복은 Nano 단독부터, 홀수 반복은 왕복부터 실행했다. 총 부하 시간은 약 90분이다.

| 항목 | 실제 결과 | 판정 경계 |
| --- | --- | --- |
| 자동 전환·복귀·해제 | 10/10회 합격 | 실제 AGX 응답 → Nano 응답 → CACHED·모델 VRAM 0 |
| Nano 단독 비교 | 10/10회 합격 | 같은 요청 스케줄, 모든 요청 완료·identity 검증 |
| 요청 완료 | 왕복 8,760/8,760건; 비교 포함 17,520/17,520건 | 거절·오류·누락·중복 전송 0 |
| 정상 구간 p95 TTFT | 회차별 103.03~379.47ms | S 548.41ms 이하 |
| 활성화와 겹친 요청의 최대 TTFT | 2,407.42ms | 별도 예산 22,846.53ms 이하 |
| AGX 준비→실제 probe 완료 | 22,131.99~22,546.88ms | 10회 모두 모델 다운로드 0ms |
| 대응 p95 전체 응답시간 감소 | 62.11~88.11%, 중앙값 81.11% | 같은 반복의 Nano 단독과 비교한 실측값 |
| 왕복 응답 완료 사이 최대 간격 | 1,890.04ms | 별도 관측값; 0ms 지연이나 완전 무중단 보장은 아님 |

S는 첫 토큰까지의 시간이고, 성능 감소율은 마지막 결과까지의 전체 응답시간 p95다.
예측식의 평균 응답 비용 이득과 실측 p95 감소율을 같은 지표로 사용하지 않는다.
실행 중 활성화 최댓값 22.547초는 기준선 10회 최댓값 22.298초보다 약 0.249초 길었다.
기준선 최대치를 절대적 상한으로 일반화하지 않는다. 합격 기준인 활성화 중 요청 지연 예산은
동결 값 그대로 유지했고 모두 통과했다. SD 성능·입력률 변동과 더 긴 작업은 별도 검증 대상이다.

최종 확인 시 Nano는 `inference_ready=true`, AGX는 `CACHED`, `model_loaded=false`,
모델 VRAM·active·queue 모두 0이었다. SD 여유는 122,755,854,336바이트(약 122.76GB),
AGX eMMC 여유는 약 14.86GB이며 저장소 preflight도 통과했다. 7개 노드는 Ready이고
Disk/Memory/PID pressure가 없었다. 기존 Llama와 `edgex-edge` Pod의 UID·컨테이너 ID·
재시작 횟수·Ready 상태가 시작 기록과 같았다. 미완료 원장은 없으며,
실제 controller 코드 해시는 93개 자동시험을 통과한 코드와 일치했다.

이번에 검증한 것은 **양쪽 노드가 살아 있는 상태의 고정 Llama 3.2 1B·8토큰 요청 연속성**이다.
Nano 전체 전원/네트워크 장애, 긴 생성·다른 서비스, 외부 서비스 공용 gateway, UI 운영 연결,
KV-cache 이전, 실제 SD 재부팅/실행 중 분리까지 검증한 것은 아니다. 다음 플랫폼 단계는
이 측정·접수/전송 계약을 외부 서비스가 사용할 공용 진입점에 연결하고 같은 기준을 다시 검증하는 일이다.

- [원본 20회·개별 verdict·전체 보고서·요약](results/2026-09-08-nano-agx-v2/attempt-02/README.md)
- [최종 실행·기존 서비스·코드 검증](results/2026-09-08-nano-agx-v2/final-verification.json)
- [종료 worker 상태](results/2026-09-08-nano-agx-v2/final-worker-state.json)
- [최종 저장소 점검](results/2026-09-08-nano-agx-v2/final-storage-preflight.json)
