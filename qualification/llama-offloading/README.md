# Llama 3.2 1B 요청 단위 동적 오프로딩 자격시험

이 디렉터리는 Llama 3.2 1B 요청 라우팅, COLD/CACHED/ACTIVE 수명주기와 노드별 포화점을
검증하는 **격리된 자격시험 프로토타입**이다. 운영 대시보드 기능, 기존 AI 서비스 배포
경로, 실행 중 generation 이동 또는 layer 분할 기능이 아니다.

## ELI5 요약

작은 계산대가 한산하면 새 손님은 그곳으로 보낸다. 줄이 계속 길어지고 큰 계산대가 켜지는
시간까지 포함해도 최소 15% 빠를 때만 **새 손님**을 보낸다. 이미 계산 중인 손님은 옮기지
않는다. 줄이 사라지면 유휴 timeout 뒤 큰 계산대의 추론 runner를 끈다.

세 노드에 Pod가 보인다고 세 노드 모두 모델을 GPU에 올려 둔 것은 아니다. 작은 관리
프로세스는 상태 확인과 `/activate` 명령을 받기 위해 남아 있고 `ACTIVE`일 때만 Llama
runner가 모델을 메모리에 올린다.

## 실제 장비와 측정 경계

| 역할 | 실제 장비 | 현재 실행/측정 |
|---|---|---|
| Nano | `etri-dev0001-jetorn`, Jetson Orin Nano | JetPack 6 CUDA, `ollama ps`의 `100% GPU` 확인 |
| AGX | 실제 Jetson AGX Orin 없음 | `etri-ser0001-cg0msb` RTX 5060 Ti x86 GPU 대체시험 완료; 실제 AGX 값 아님 |
| Spark | 실제 NVIDIA DGX Spark 없음 | `etri-ser0002-cgnmsb` RTX 5080 x86 GPU 대체시험 완료; 실제 Spark 값 아님 |

Nano 로그에서 Orin compute capability 8.7과 `cuda_jetpack6` runner를 확인했다. 모델
digest는 `baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878`이다.
과거 amd64 서버를 AGX/Spark 역할로 둔 CPU-only 결과는
`results/2026-09-04-cpu-substitute/`에 실행 로직 이력으로만 보존한다.

Nano의 GPU utilization/memory는 현재 Jetson용 DCGM collector가 없어 `/metrics`에서
`null`로 남긴다. 이를 0으로 대체하거나 idle GPU memory 절감 증거로 사용하지 않는다.

## 구성

- `worker.py`: `/generate`, `/health`, `/metrics`, `/activate`, `/deactivate`
- `proxy.py`: 방식 설정, placement, READY 확인, 단일 전달, idle 반환과 JSONL 기록
- `placement.py`: Nano→AGX→Spark 승격과 복귀 정책
- `run_experiments.py`: idle/single/activation/increasing/burst/repeated workload 수집
- `analyze_experiments.py`: 세 방식 비교표, break-even과 그래프 생성
- `run_saturation.py`: 선택한 실제 노드의 고정 배치 반복 포화시험
- `analyze_saturation.py`: 처리량 knee, TTFT SLO capacity와 오프로딩 gate 산출
- `k8s/`: `llama-offload-eval` namespace 전용 manifest
- `results/`: 요청별 CSV, 집계표, 분석 설정과 그림

상태 의미는 다음과 같다.

| 상태 | local checkpoint | inference runner | 모델 메모리 | `/generate` |
|---|---:|---:|---:|---:|
| COLD | 없음 | 정지 | 미점유 | 거부 |
| CACHED | 있음 | 정지 | 미점유 | 거부 |
| ACTIVE | 있음 | 실행 | 점유 | READY일 때 허용 |

Ollama 관리 daemon과 control API는 세 상태 모두에서 상주한다. 여기서 worker를 끈다는 것은
토큰을 생성하고 모델 메모리를 점유하는 runner를 종료한다는 뜻이다.

## 2026-09-04 Orin Nano GPU 포화점

동일 모델·짧은 prompt·최대 생성 토큰 8개·worker concurrency 1 조건으로 client
concurrency 1·2·4·8·16·32를 무작위 순서로 3회 반복했다.

| 동시 요청 | p95 TTFT | p95 latency | 처리량 | 실패 |
|---:|---:|---:|---:|---:|
| 1 | 36.2ms | 208.0ms | 4.959 req/s | 0/180 |
| 2 | 234.9ms | 402.2ms | 5.053 req/s | 0/186 |
| 4 | 624.3ms | 790.1ms | 5.070 req/s | 0/193 |
| 8 | 1,405.3ms | 1,573.3ms | 5.055 req/s | 0/204 |
| 16 | 2,960.6ms | 3,135.4ms | 5.058 req/s | 1/229 |
| 32 | 6,110.3ms | 6,290.7ms | 5.066 req/s | 8/284 |

- SLO capacity: concurrency 8
- first overload: concurrency 16
- 관측 최대 처리량: 5.070 requests/s
- 단독 중앙 tokens/s: 49.352
- 초기 정책: queue high 8, TTFT high 1,500ms, tokens/s low 39.5, overload dwell 2초

초기 queue 기준 8은 오프로딩 명령이 아니라 검토 latch다. 이후에도 다음 gain이 양수이고
원격 예상 완료시간이 Nano보다 최소 15% 짧아야 신규 요청을 전환한다.

```text
Nano predicted completion
- (target activation + target RTT + target queue wait + target inference)
```

AGX/Spark 실장비 측정이 없으므로 현재 원격 gain과 최종 offloading threshold는 미확정이다.
상세 결과는 [Orin Nano GPU 포화점 보고서](results/2026-09-04-orin-nano-gpu/saturation/report.md)에 있다.

## 2026-09-04 RTX 5060 Ti x86 GPU 대체시험

`etri-ser0001-cg0msb`의 불필요한 `ai-scientist` GPU 예약을 제거한 뒤, 같은 모델 digest와
workload로 x86 RTX 5060 Ti 대체시험을 수행했다. 실제 Jetson AGX Orin 결과가 아니다.

- `ollama ps`: Llama 3.2 1B `100% GPU`
- SLO capacity: 동시 요청 4, first overload: 8
- 최대 처리량: 5.306 req/s
- Cold activation 평균: 19.074초
- Cached activation 평균: 2.329초, Cold 대비 87.8% 단축
- ACTIVE GPU memory: 1,764MiB, CACHED: 228MiB
- Cached 첫 요청 break-even: Nano 선행 대기 약 12건, 15% 이득 기준 약 14건

짧은 8-token 요청에서는 RTX 5060 Ti의 tokens/s가 Nano보다 높아도 전체 처리량은 4.7%만
높았다. 대상 하나로 교체하는 이득은 작고, 충분히 긴 backlog에서 두 worker를 병행해 합산
처리량을 늘리는 방식이 핵심이다. 상세 수치와 제한은
[RTX 5060 Ti GPU 대체 서버 검증 보고서](results/2026-09-04-rtx5060ti-gpu/검증-보고서.md)를 따른다.

## 2026-09-04 RTX 5080 x86 GPU 대체시험

`etri-ser0002-cgnmsb`의 센서 추론 서비스를 사용자 승인 아래 시험 동안만 중단하고, 같은
모델 digest와 workload로 RTX 5080 대체시험을 수행했다. 실제 NVIDIA DGX Spark 결과가 아니다.

- `ollama ps`: Llama 3.2 1B `100% GPU`
- SLO capacity: 동시 요청 16, first overload: 32의 오류 3건
- 최대 처리량: 50.006 req/s
- Cold activation 평균: 26.980초
- Cached activation 평균: 1.847초, Cold 대비 93.2% 단축
- ACTIVE GPU memory: 1,673MiB, CACHED: 16MiB
- Cached 첫 요청 break-even: Nano 선행 대기 약 9건, 15% 이득 기준 약 11건

RTX 5080 worker를 내린 뒤 센서 서비스는 원래 1/1 Ready, CUDA RTX 5080, GPU 예약 1/1로
복구했다. 현재 cache는 Pod writable layer라 scale-to-zero 뒤에는 유지되지 않는다. 상세 수치와
제한은 [RTX 5080 GPU 대체 서버 검증 보고서](results/2026-09-04-rtx5080-gpu/검증-보고서.md)를 따른다.

## 배포와 확인

```bash
rtk kubectl kustomize qualification/llama-offloading
rtk kubectl apply -k qualification/llama-offloading
rtk kubectl -n llama-offload-eval get pods -o wide

rtk curl -fsS http://192.168.0.3:18100/health
rtk curl -fsS http://192.168.0.3:18100/metrics
```

Nano endpoint는 `192.168.0.3:18100`, 프록시는 `192.168.0.56:18101`이다. AGX/Spark
Deployment는 실제 장비가 연결될 때 사용할 placeholder이며 현재 replica 0이다. 따라서
가짜 원격 역할 endpoint로 신규 요청을 보내지 않는다.

현재 Jetson edgecore는 cluster-scoped RuntimeClass를 받지 못해 격리된 Nano inference
container에만 host driver library를 read-only mount하고 `JETSON_JETPACK=6`을 설정했다.
장치 접근을 위해 privileged를 사용하므로 운영 공통 패턴으로 승격하지 않는다. 기존
EdgeCore/containerd 기본값과 EdgeX workload는 변경하지 않는다.

## 시험 재현

```bash
rtk qualification/llama-offloading/.venv/bin/python \
  -m unittest discover -s qualification/llama-offloading/tests -v

rtk qualification/llama-offloading/.venv/bin/python \
  qualification/llama-offloading/run_saturation.py \
  --tiers nano \
  --output-dir qualification/llama-offloading/results/<run-id>/saturation

rtk qualification/llama-offloading/.venv/bin/python \
  qualification/llama-offloading/analyze_saturation.py \
  qualification/llama-offloading/results/<run-id>/saturation \
  --execution-profile orin_nano_gpu
```

원자료는 `requests.csv`와 `resources.csv`, 변환 provenance는 `analysis-config.json`, 집계값은
`saturation-summary.csv`와 `derived-limits.csv`에 남는다. 결측 GPU·전력 값은 0으로
대체하지 않는다.

## 운영 경계

- root `edgex/k8s/kustomization.yaml`이나 Argo CD `edgex-telemetry`에 포함하지 않는다.
- EdgeX inventory/state/telemetry/command를 읽거나 변경하지 않는다.
- 현재 대시보드의 배포·migration·offloading 기능으로 연결하지 않는다.
- 모델 cache는 runtime container writable layer, 프록시 JSONL은 `emptyDir`라 Pod 교체 시
  사라진다. 내구성 있는 Cached 방식은 local SSD/PVC 계약을 별도 구현해야 한다.
- 실제 AGX Orin·DGX Spark가 준비되면 같은 GPU runtime·모델·prompt·workload로 세 방식의
  activation, idle GPU memory·전력, 열 throttling과 break-even을 다시 측정한다.
