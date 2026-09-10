# Llama 3.2 1B Orin Nano GPU 포화점 자격시험

## 판정 요약

실제 `etri-dev0001-jetorn` Orin Nano에서 Ollama JetPack 6 CUDA runner로
`llama3.2:1b` 전체 모델을 실행했다. AGX Orin과 DGX Spark는 이 run에 포함하지 않았으므로
두 장비의 성능이나 오프로딩 손익은 결론 내리지 않는다.

- 처리량 knee: 관측 최대 처리량의 95%에 처음 도달한 동시성
- SLO capacity: 오류 0이고 p95 TTFT가 1,500ms 이하인 가장 높은 동시성
- first overload: p95 TTFT 1,500ms 초과 또는 오류가 처음 발생한 동시성
- 반복 단위: block 3회. 같은 노드의 요청 여러 개를 독립 장비 반복으로 해석하지 않는다.

| node   |   baseline_p95_ttft_ms |   baseline_median_tokens_per_second |   tokens_per_second_low |   max_observed_throughput_rps |   throughput_knee_concurrency |   slo_capacity_concurrency |   first_slo_overload_concurrency |   ttft_high_ms |
|:-------|-----------------------:|------------------------------------:|------------------------:|------------------------------:|------------------------------:|---------------------------:|---------------------------------:|---------------:|
| nano   |                 36.167 |                              49.352 |                  39.482 |                          5.07 |                             1 |                          8 |                               16 |           1500 |

## 원격 오프로딩 손익

이 run은 Orin Nano GPU 단독 포화점만 측정했다. 실제 AGX Orin·DGX Spark의 동일 조건
성능과 activation 시간이 없으므로 원격 break-even과 대상 선택 기준은 계산하지 않는다.

## Orin Nano GPU worker에 적용할 초기 부하 기준

- 조기 압력: `queue_length >= 8`이 2초 동안 지속
- 서비스 한계: rolling/worker EWMA TTFT가 `1500ms` 이상
- 생성 성능 저하 보조 신호: tokens/s가 단독 실행 중앙값의 80%인 `39.482` 이하
- 부하 해제: queue 0 및 active request 0이 4초 지속, 경로 변경 후 5초 cooldown

queue는 임계값에 순간적으로 닿은 것만으로 즉시 오프로딩하지 않는다. 위 부하 latch를 통과한 뒤에도 대상의 `activation + RTT + queue wait + inference`를 포함한 예상 완료시간이 Nano 예상 완료시간보다 15% 이상 짧고 gain이 양수일 때만 새 요청을 보낸다. 대상이 READY가 되기 전에는 보내지 않는다.

## 조건별 원자료 집계

| node   |   concurrency |   requests |   errors |   p95_ttft_ms |   p95_client_latency_ms |   mean_throughput_rps |   p95_observed_queue_length |
|:-------|--------------:|-----------:|---------:|--------------:|------------------------:|----------------------:|----------------------------:|
| nano   |             1 |        180 |        0 |        36.167 |                 208.029 |                 4.959 |                           0 |
| nano   |             2 |        186 |        0 |       234.884 |                 402.219 |                 5.053 |                           1 |
| nano   |             4 |        193 |        0 |       624.334 |                 790.15  |                 5.07  |                           3 |
| nano   |             8 |        204 |        0 |      1405.29  |                1573.28  |                 5.055 |                           7 |
| nano   |            16 |        229 |        1 |      2960.65  |                3135.38  |                 5.058 |                          15 |
| nano   |            32 |        284 |        8 |      6110.33  |                6290.7   |                 5.066 |                          31 |

## 해석 경계

- 요청은 실제 Orin Nano GPU worker API에 직접 전달했다.
- AGX Orin과 DGX Spark 실장비가 없어 원격 activation·break-even은 계산하지 않았다.
- GPU 사용 여부는 Ollama `inference compute`의 CUDA 8.7·JetPack 6 탐지와 `ollama ps`의
  `100% GPU`로 별도 검증했다.
- 모델, prompt, max tokens, worker concurrency는 동일하게 고정했다.
- block 안의 node×concurrency 조건 순서는 seed `20260904`로 무작위화해 시간·열·공유 클러스터 부하의 순서 편향을 줄였다.

## 그림

- `figures/p95-ttft.png`: 동시성별 p95 TTFT와 1,500ms SLO
- `figures/throughput.png`: 동시성별 완료 처리량
- `figures/p95-latency.png`: 동시성별 client p95 latency
- `figures/p95-queue.png`: 동시성별 관측 queue p95

동시성이 2배씩 증가하므로 그림 x축은 명시적인 log2 scale을 사용한다. 그림은 색상 외 marker와 line style도 함께 사용하며, 동일 표의 CSV가 접근 가능한 원자료 대안이다.
