# Llama 오프로딩 부하 판단 기준 — 실제 Orin Nano GPU 시험

> **최신 안내 (2026-09-10): 실제 AGX Orin과 DGX Spark의 GPU 실측은 완료했다.**
> [장비별 GPU 성능측정](Llama-장비별-GPU-성능측정.md)에서 실제 Spark의
> 8토큰 상한 조건 640/640건 성공을 확인할 수 있다. Spark의 512/128토큰 공통 비교는 미측정이다.
> 아래는 **9월 4일 초기 시험의 이력**이다. 당시 RTX 대체 결과를 실제 AGX·Spark 값으로
> 바꾸어 읽거나 당시 임계값을 다른 요청 길이의 확정 기준으로 사용하지 않는다.

> **2026-09-04 당시 측정 범위:** `etri-dev0001-jetorn`의 실제 Jetson Orin Nano에서
> Ollama JetPack 6 CUDA runner로 `llama3.2:1b`를 실행했다. 로그에서 Orin compute
> capability 8.7을 확인했고 `ollama ps`는 모델을 `100% GPU`로 표시했다.
> 이 초기 시험에는 실제 Jetson AGX Orin과 NVIDIA DGX Spark가 포함되지 않았다. 대신 RTX 5060 Ti와 RTX 5080
> x86 서버에서 같은 모델의 GPU 대체시험을 수행했으며, 두 결과를 실제 AGX·Spark
> 성능값으로 해석하지 않는다.

| 역할 | 실제 장비 | 이번 결과에 포함 | 실행 backend |
|---|---|---|---|
| Nano | `etri-dev0001-jetorn`, Jetson Orin Nano | 예 | JetPack 6 CUDA, `100% GPU` |
| AGX | 당시 시험에는 미포함 | 후속 실제 AGX 실측은 상단 링크 | RTX 5060 Ti x86 대체 서버에서 `100% GPU` 별도 측정 |
| Spark | 당시 시험에는 미포함 | 후속 실제 Spark 실측은 상단 링크 | RTX 5080 x86 대체 서버에서 `100% GPU` 별도 측정 |

## ELI5: 언제 “부하가 걸렸다”고 하나

급식실에 배식 창구가 하나 있다고 생각하면 된다.

- 한 명씩 오면 바로 밥을 받는다. 아직 여유가 있다.
- 앞사람이 끝나기 전에 새 사람이 계속 오면 줄이 생긴다.
- 사람이 더 와도 1초에 배식하는 수가 늘지 않고 기다리는 시간만 길어지면 포화다.
- 첫 숟가락을 받기까지 1.5초보다 오래 걸리면 이번 시험의 서비스 한계를 넘은 것이다.

Orin Nano GPU worker도 generation을 한 번에 하나씩 처리하도록 고정했다. 그래서 GPU
사용률 하나로 판단하지 않고 다음 세 신호를 함께 본다.

1. **줄이 안전 범위를 넘었는가?** `queue_length >= 8`
2. **첫 토큰이 늦는가?** p95 또는 worker EWMA TTFT가 1,500ms 이상
3. **생성 속도가 떨어지는가?** `tokens/s <= 39.5`

위 신호 중 하나가 한 번 튄 것만으로는 원격 장비를 켜지 않는다. **2초 동안 지속될 때**
오프로딩 검토를 시작한다. 이것은 전환 명령이 아니라 “다른 창구를 열어야 할지 계산하자”는
신호다.

## 실제 Orin Nano GPU에서 관측한 구간

동일 모델과 prompt, 최대 생성 토큰 8개, worker concurrency 1 조건에서 client concurrency를
1·2·4·8·16·32로 늘렸다. 각 조건은 무작위 순서로 3회 반복했다.

| 동시 요청 | p95 TTFT | p95 전체 지연 | 처리량 | 실패 | 판단 |
|---:|---:|---:|---:|---:|---|
| 1 | 36.2ms | 208.0ms | 4.959 req/s | 0/180 | 여유 |
| 2 | 234.9ms | 402.2ms | 5.053 req/s | 0/186 | 안전 범위 |
| 4 | 624.3ms | 790.1ms | 5.070 req/s | 0/193 | 안전 범위 |
| 8 | 1,405.3ms | 1,573.3ms | 5.055 req/s | 0/204 | SLO 안쪽 마지막 구간 |
| 16 | 2,960.6ms | 3,135.4ms | 5.058 req/s | 1/229 | 첫 과부하 |
| 32 | 6,110.3ms | 6,290.7ms | 5.066 req/s | 8/284 | 과부하·연결 실패 증가 |

따라서 이번 짧은 prompt 자격시험에서는 다음처럼 정한다.

- **동시 요청 8까지:** p95 TTFT 1,500ms SLO와 오류 0을 함께 지킨 범위
- **동시 요청 16부터:** p95 TTFT가 SLO를 넘고 오류가 처음 생긴 과부하 구간
- **처리량 약 5.07 req/s:** 동시 요청을 더 늘려도 거의 증가하지 않은 관측 상한
- **단독 생성 속도 49.352 tokens/s:** 이 값의 80%인 39.482 tokens/s를 저하 신호로 사용

동시 요청 8은 p95 TTFT가 1,405.3ms라 SLO에 가깝다. 그래서 `queue_length >= 8`을
즉시 오프로딩 조건이 아니라 2초 지속되는 조기 검토 신호로 둔다. 더 긴 prompt, 더 많은
출력 토큰, 높은 온도에서는 한계가 달라질 수 있으므로 운영 확정값이 아니라 현재
자격시험의 초기값이다.

## 그러면 언제 오프로딩하나

두 문을 모두 통과해야 한다.

### 1문: Nano 부하가 계속되는가

```text
(queue_length >= 8
 OR worker EWMA TTFT >= 1,500ms
 OR tokens/s <= 39.5)
가 2초 지속
```

### 2문: 원격 실행이 실제로 더 빠른가

```text
Offloading Gain
= Nano에서 계속 기다릴 예상시간
 - (원격 activation + RTT + 원격 queue wait + 원격 inference)
```

`Gain > 0`이면서 원격 예상 완료시간이 Nano보다 **최소 15% 짧아야** 신규 요청을 보낸다.
원격 node가 READY가 되기 전에는 보내지 않는다. 아래 x86 대체값으로 prototype 기준은
계산할 수 있지만, 실제 AGX/Spark의 최종 선택 임계값은 아직 확정할 수 없다.

### RTX 5060 Ti x86 대체 서버에서 확인한 참고값

실제 AGX가 없는 상태에서 오프로딩 코드와 GPU 경로를 검증하기 위해
`etri-ser0001-cg0msb`의 RTX 5060 Ti를 AGX **대체 역할**로만 측정했다.

| 항목 | 측정값 |
|---|---:|
| SLO capacity / first overload | 동시 요청 4 / 8 |
| 최대 처리량 | 5.306 req/s |
| Cold activation 평균 | 19.074초 |
| Cached activation 평균 | 2.329초 |
| Cached의 activation 단축 | 16.745초, 87.8% |
| ACTIVE / CACHED GPU memory | 1,764MiB / 228MiB |

이번 짧은 8-token 요청에서 대체 서버의 단독 p95 전체 지연은 220.5ms로 Nano 208.0ms보다
6.0% 느렸고, 최대 처리량은 4.7%만 높았다. 따라서 “서버 GPU이므로 무조건 요청 하나가
빨라진다”는 결론은 틀리다. Cached activation까지 포함하면 Nano 앞에 약 12건 이상
대기해야 첫 offload 요청의 근사 gain이 양수가 되고, 15% 이득 기준은 약 14건이다.

두 worker가 이미 ACTIVE이고 backlog가 충분하다는 단순 합산에서는 10.376 req/s로
Nano-only보다 약 104.7% 높은 잠재 처리량이 나온다. 이것은 아직 동적 burst 라우팅 실측이
아니며 실제 AGX 성능값도 아니다. 원자료와 계산 경계는
`qualification/llama-offloading/results/2026-09-04-rtx5060ti-gpu/검증-보고서.md`에 있다.

### RTX 5080 x86 대체 서버에서 확인한 참고값

9월 4일 시험에서 실제 DGX Spark를 사용하지 않고 `etri-ser0002-cgnmsb`의 RTX 5080을 Spark **대체 역할**로
측정했다. 기존 센서 GPU 서비스는 승인받아 시험 동안만 중단했고, 시험 직후 원래 1/1 Ready,
CUDA RTX 5080, GPU 예약 1/1 상태로 복구했다.

| 항목 | 측정값 |
|---|---:|
| SLO capacity / first overload | 동시 요청 16 / 32 |
| 최대 처리량 | 50.006 req/s |
| Cold activation 평균 | 26.980초 |
| Cached activation 평균 | 1.847초 |
| Cached의 activation 단축 | 25.133초, 93.2% |
| ACTIVE / CACHED GPU memory | 1,673MiB / 16MiB |
| 부하 중 GPU 사용률 평균 / 최대 | 69.8% / 80.0% |

동시 요청 32의 p95 TTFT는 653.9ms였지만 첫 블록에서 오류 3건이 발생했으므로, 오류 0을
요구하는 안전 상한은 16으로 둔다. Cached activation을 포함한 첫 요청은 Nano 앞에 약 9건
이상 대기할 때 gain이 양수가 되고, 최소 15% 이득 기준은 약 11건이다. Cold는 각각 약
136건과 160건이 필요하므로 짧은 burst에는 켜지 않는다.

요청 하나당 중앙 서비스시간 절감으로 activation 비용을 상쇄하는 지속 workload 기준은
Cached 약 11건, Cold 약 153건이다. Nano와 RTX 5080 worker가 이미 ACTIVE라는 단순 합산
상한은 약 55.075 req/s로 Nano-only보다 약 986.4% 높지만, 아직 동적 burst 라우팅을
동시에 실행해 얻은 결과는 아니다. 원자료와 계산 경계는
`qualification/llama-offloading/results/2026-09-04-rtx5080-gpu/검증-보고서.md`에 있다.

## 요청이 이동하는 범위

- 이미 답변을 생성 중인 요청은 다른 장비로 옮기지 않는다.
- overload 판정 뒤 들어온 **신규 요청**의 실행 위치만 바꾼다.
- Llama layer를 여러 장비에 나누지 않는다.
- 원격 worker가 READY가 되기 전에는 요청을 보내지 않는다.
- 부하가 사라져 queue 0과 active request 0이 4초 지속되면 복귀를 검토하고, 경로 변경 뒤
  5초 cooldown을 적용한다.

## 배포 상태

자격시험은 운영 EdgeX·대시보드와 분리한 `llama-offload-eval` namespace에 배포했다.
Nano worker는 실제 `etri-dev0001-jetorn`에 고정했다.
AGX/Spark Deployment는 실장비 연결용 placeholder만 남기고 replica 0으로 두어, 현재
신규 요청이 amd64 CPU 역할 대체 Pod로 잘못 전환되지 않게 했다.

```bash
rtk kubectl apply -k qualification/llama-offloading
rtk kubectl -n llama-offload-eval get pods -o wide
rtk curl -fsS http://192.168.0.3:18100/health
```

현재 클러스터의 Jetson edgecore에는 cluster-scoped `RuntimeClass`가 전달되지 않아 일반적인
`runtimeClassName: nvidia` 경로를 사용할 수 없었다. 격리된 Nano inference container에만
Jetson host driver library를 read-only로 mount하고 `JETSON_JETPACK=6`을 설정했다. 이
container는 해당 장치 접근을 위해 privileged로 실행하므로 운영 공통 패턴으로 승격하지
않는다. EdgeCore/containerd 기본값과 기존 EdgeX workload는 바꾸지 않았다.

Nano의 `/metrics`에서 GPU utilization과 GPU memory는 `null`이다. Jetson용 DCGM exporter가
현재 없기 때문이다. 따라서 이번 GPU 실행 증거는 CUDA 8.7 runner 탐지와 `ollama ps`의
`100% GPU`이며, idle GPU memory 절감량은 아직 측정 완료로 주장하지 않는다.

## 측정 근거와 제한

- 원자료: `qualification/llama-offloading/results/2026-09-04-orin-nano-gpu/saturation/`
- 요청 수: warm-up 1건 제외 1,276건, 성공 1,267건, 실패 9건
- 실패 위치: concurrency 16에서 1건, 32에서 8건의 connection reset
- 포화시험 전 Nano activation: 모델 다운로드 38.073초 + load/ready 26.141초 = 64.229초
- 배포 갱신 후 재검증 activation: 모델 다운로드 24.891초 + load/ready 27.355초 = 52.261초
- 모델 digest: `baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878`
- 분석기: `qualification/llama-offloading/analyze_saturation.py`
- RTX 5060 Ti x86 GPU 대체시험 원자료:
  `qualification/llama-offloading/results/2026-09-04-rtx5060ti-gpu/`
- RTX 5080 x86 GPU 대체시험 원자료:
  `qualification/llama-offloading/results/2026-09-04-rtx5080-gpu/`

두 값은 Nano Pod의 빈 writable layer에서 모델을 받은 Cold activation 실측이다.
AGX/Spark Cold 또는 Cached activation 시간으로 바꿔 쓰면 안 된다. 과거 CPU-only 혼합 역할
시험은 `results/2026-09-04-cpu-substitute/`에 이력으로 남기되 현재 GPU 기준과 섞지 않는다.

## 결론

> **한 줄 결론:** Llama 3.2 1B를 실제 Orin Nano GPU에서 실행한 이번 조건에서는 동시 요청
> 8까지 p95 TTFT 1.5초 SLO를 지켰고, 16부터 과부하가 시작됐다.

- 초기 Nano 부하 검토값은 `queue_length >= 8`, TTFT 1,500ms, 39.5 tokens/s, 지속시간
  2초다.
- GPU 실행은 CPU-only 기준보다 최대 처리량이 약 2.01배(2.525 → 5.070 req/s), 단독
  tokens/s가 약 1.92배(25.661 → 49.352) 높았다.
- CPU-only 때 안전 동시 요청 2·첫 과부하 4였던 경계가 GPU에서는 각각 8·16으로 이동했다.
- 이것은 Nano 단독 포화점 결론이다. **이 초기 시험으로 실제 AGX Orin과 DGX Spark의 성능을 판단하지 않는다. 후속 실측은 상단 링크를 따른다.**
- RTX 5060 Ti 대체시험에서는 Cached activation이 Cold보다 87.8% 짧았지만, 짧은 요청의
  단독 p95 latency는 Nano보다 개선되지 않았다. 충분한 backlog에서 병행 처리량을 늘리는
  용도로만 이득 가능성이 확인됐다.
- RTX 5080 대체시험에서는 오류 0 기준 동시 요청 16까지 안전했고 Cached activation은
  1.847초였다. Nano 선행 대기 9건에서 gain이 양수, 11건에서 15% 이득 기준을 넘었다.
- 현재 대체 장비 중 activation 대비 성능 향상은 RTX 5080 Spark 역할이 가장 컸다. 다만
  RTX 5060은 호스트 Ollama, RTX 5080은 Kubernetes 컨테이너 Ollama라 순수 GPU 비교가 아니다.
- 실제 AGX/Spark의 후속 실측과 별도로, 같은 GPU runtime·local SSD cache·모델·prompt·workload로
  세 방식의 idle 자원, activation과 최종 break-even을 다시 측정해야 한다.
