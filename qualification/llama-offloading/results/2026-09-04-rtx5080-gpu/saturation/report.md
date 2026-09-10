# Llama 3.2 1B x86 GPU 대체 서버 포화점 자격시험

## 판정 요약

실제 측정 장비는 `NVIDIA GeForce RTX 5080`를 장착한 x86 서버이며 논리적으로 SPARK 역할을
부여했다. Ollama에서 Llama 3.2 1B의 `100% GPU` 실행을 확인했지만, 실제 NVIDIA DGX Spark가 아니다.
따라서 이 결과는 오프로딩 코드와 GPU 실행 경로 검증용 대체값이며 목표 장비 성능값이 아니다.

- 처리량 knee: 관측 최대 처리량의 95%에 처음 도달한 동시성
- SLO capacity: 오류 0이고 p95 TTFT가 1,500ms 이하인 가장 높은 동시성
- first overload: p95 TTFT 1,500ms 초과 또는 오류가 처음 발생한 동시성
- 반복 단위: block 3회. 같은 노드의 요청 여러 개를 독립 장비 반복으로 해석하지 않는다.

| node   |   baseline_p95_ttft_ms |   baseline_median_tokens_per_second |   tokens_per_second_low |   max_observed_throughput_rps |   throughput_knee_concurrency |   slo_capacity_concurrency |   first_slo_overload_concurrency |   ttft_high_ms |
|:-------|-----------------------:|------------------------------------:|------------------------:|------------------------------:|------------------------------:|---------------------------:|---------------------------------:|---------------:|
| spark  |                   5.33 |                             540.358 |                 432.286 |                        50.006 |                             2 |                         16 |                               32 |           1500 |

## 원격 오프로딩 손익

이 run은 x86 GPU 대체 서버 한 대의 포화점만 측정했다. Nano와 동일 workload 결과는
비교할 수 있지만 실제 AGX Orin·DGX Spark의 activation·break-even은 계산하지 않는다.

## x86 GPU 대체 worker에서 관측한 초기 부하 기준

- 조기 압력: `queue_length >= 16`이 2초 동안 지속
- 서비스 한계: rolling/worker EWMA TTFT가 `1500ms` 이상
- 생성 성능 저하 보조 신호: tokens/s가 단독 실행 중앙값의 80%인 `432.286` 이하
- 부하 해제: queue 0 및 active request 0이 4초 지속, 경로 변경 후 5초 cooldown

queue는 임계값에 순간적으로 닿은 것만으로 즉시 오프로딩하지 않는다. 위 부하 latch를 통과한 뒤에도 대상의 `activation + RTT + queue wait + inference`를 포함한 예상 완료시간이 Nano 예상 완료시간보다 15% 이상 짧고 gain이 양수일 때만 새 요청을 보낸다. 대상이 READY가 되기 전에는 보내지 않는다.

## 조건별 원자료 집계

| node   |   concurrency |   requests |   errors |   p95_ttft_ms |   p95_client_latency_ms |   mean_throughput_rps |   p95_observed_queue_length |
|:-------|--------------:|-----------:|---------:|--------------:|------------------------:|----------------------:|----------------------------:|
| spark  |             1 |       1630 |        0 |         5.33  |                  23.782 |                45.245 |                           0 |
| spark  |             2 |       1805 |        0 |        24.405 |                  42.467 |                50.006 |                           1 |
| spark  |             4 |       1799 |        0 |        67.03  |                  85.322 |                49.704 |                           3 |
| spark  |             8 |       1806 |        0 |       152.332 |                 170.407 |                49.564 |                           7 |
| spark  |            16 |       1837 |        0 |       319.954 |                 338.575 |                49.721 |                          15 |
| spark  |            32 |       1889 |        3 |       653.882 |                 674.314 |                49.721 |                          31 |

## 해석 경계

- 요청은 `NVIDIA GeForce RTX 5080` worker API에 직접 전달했다.
- 실제 Jetson AGX Orin·DGX Spark의 성능 또는 전력 결과로 해석하지 않는다.
- 모델 digest, prompt, max tokens와 worker concurrency는 Orin Nano 시험과 동일하게 유지했다.
- 모델, prompt, max tokens, worker concurrency는 동일하게 고정했다.
- block 안의 node×concurrency 조건 순서는 seed `20260904`로 무작위화해 시간·열·공유 클러스터 부하의 순서 편향을 줄였다.

## 그림

- `figures/p95-ttft.png`: 동시성별 p95 TTFT와 1,500ms SLO
- `figures/throughput.png`: 동시성별 완료 처리량
- `figures/p95-latency.png`: 동시성별 client p95 latency
- `figures/p95-queue.png`: 동시성별 관측 queue p95

동시성이 2배씩 증가하므로 그림 x축은 명시적인 log2 scale을 사용한다. 그림은 색상 외 marker와 line style도 함께 사용하며, 동일 표의 CSV가 접근 가능한 원자료 대안이다.
