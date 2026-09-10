# Llama 3.2 1B 노드별 포화점 자격시험

## 판정 요약

Nano는 실제 Orin Nano 노드에서 CPU-only로 실행했다. `AGX/Spark`는 실제 대상 장비가
아니라 amd64 서버에 부여한 역할이며 CPU로 실행했다. 따라서 Nano 행은 Orin Nano
CPU-only 기준선, AGX·Spark 행은 x86 CPU 대체값이며 실제 세 장비의 GPU 용량이 아니다.

- 처리량 knee: 관측 최대 처리량의 95%에 처음 도달한 동시성
- SLO capacity: 오류 0이고 p95 TTFT가 1,500ms 이하인 가장 높은 동시성
- first overload: p95 TTFT 1,500ms 초과 또는 오류가 처음 발생한 동시성
- 반복 단위: block 3회. 같은 노드의 요청 여러 개를 독립 장비 반복으로 해석하지 않는다.

| node   |   baseline_p95_ttft_ms |   baseline_median_tokens_per_second |   tokens_per_second_low |   max_observed_throughput_rps |   throughput_knee_concurrency |   slo_capacity_concurrency |   first_slo_overload_concurrency |   ttft_high_ms |
|:-------|-----------------------:|------------------------------------:|------------------------:|------------------------------:|------------------------------:|---------------------------:|---------------------------------:|---------------:|
| nano   |                199.409 |                              25.661 |                  20.529 |                         2.525 |                             1 |                          2 |                                4 |           1500 |
| agx    |                 29.97  |                              44.96  |                  35.968 |                         4.783 |                             1 |                          4 |                                8 |           1500 |
| spark  |                 33.453 |                              45.98  |                  36.784 |                         4.828 |                             1 |                          8 |                               16 |           1500 |

## Activation을 포함한 오프로딩 손익 기준

아래 `minimum_nano_requests_ahead...`는 새 요청이 도착할 때 Orin Nano CPU-only worker에서 이미
실행·대기 중인 요청 수를 뜻한다. 같은 prompt 길이와 이 혼합 CPU-only run의 중앙
서비스시간을 순차 처리로 근사했다. 실제 라우터는 이 고정 숫자만 사용하지 않고 매
요청의 최신 EWMA, queue, RTT와 activation estimate로 다시 계산한다.

| method           | target_node   |   activation_ms |   nano_median_service_ms |   target_median_service_ms |   saved_ms_per_subsequent_request |   sequential_break_even_requests |   minimum_nano_requests_ahead_for_15pct_first_request_gain | reachable_before_tested_connection_failure_ceiling   |
|:-----------------|:--------------|----------------:|-------------------------:|---------------------------:|----------------------------------:|---------------------------------:|-----------------------------------------------------------:|:-----------------------------------------------------|
| always_on        | agx           |            0    |                  388.082 |                    208.096 |                           179.986 |                                1 |                                                          0 | True                                                 |
| always_on        | spark         |            0    |                  388.082 |                    211.063 |                           177.019 |                                1 |                                                          0 | True                                                 |
| cached_on_demand | agx           |         1187.22 |                  388.082 |                    208.096 |                           179.986 |                                7 |                                                          4 | True                                                 |
| cached_on_demand | spark         |         1187.08 |                  388.082 |                    211.063 |                           177.019 |                                7 |                                                          4 | True                                                 |
| cold_on_demand   | agx           |        40646.3  |                  388.082 |                    208.096 |                           179.986 |                              226 |                                                        123 | False                                                |
| cold_on_demand   | spark         |        38465.3  |                  388.082 |                    211.063 |                           177.019 |                              218 |                                                        117 | False                                                |

## Orin Nano CPU-only worker에 적용할 초기 부하 기준

- 조기 압력: `queue_length >= 1`이 2초 동안 지속
- 서비스 한계: rolling/worker EWMA TTFT가 `1500ms` 이상
- 생성 성능 저하 보조 신호: tokens/s가 단독 실행 중앙값의 80%인 `20.529` 이하
- 부하 해제: queue 0 및 active request 0이 4초 지속, 경로 변경 후 5초 cooldown

queue는 순간적으로 1이 된 것만으로 즉시 오프로딩하지 않는다. 위 부하 latch를 통과한 뒤에도 대상의 `activation + RTT + queue wait + inference`를 포함한 예상 완료시간이 Nano 예상 완료시간보다 15% 이상 짧고 gain이 양수일 때만 새 요청을 보낸다. 대상이 READY가 되기 전에는 보내지 않는다.

## 조건별 원자료 집계

| node   |   concurrency |   requests |   errors |   p95_ttft_ms |   p95_client_latency_ms |   mean_throughput_rps |   p95_observed_queue_length |
|:-------|--------------:|-----------:|---------:|--------------:|------------------------:|----------------------:|----------------------------:|
| agx    |             1 |        173 |        0 |        29.97  |                 221.871 |                 4.766 |                           0 |
| agx    |             2 |        176 |        0 |       251.907 |                 447.057 |                 4.769 |                           1 |
| agx    |             4 |        180 |        0 |       690.012 |                 880.799 |                 4.741 |                           3 |
| agx    |             8 |        195 |        0 |      1527.75  |                1712.71  |                 4.783 |                           7 |
| agx    |            16 |        217 |        0 |      3232.09  |                3440.92  |                 4.767 |                          15 |
| agx    |            32 |        267 |        4 |      6948.68  |                7184.11  |                 4.702 |                          31 |
| nano   |             1 |         89 |        0 |       199.409 |                 572.028 |                 2.422 |                           0 |
| nano   |             2 |         94 |        0 |       640.704 |                 981.956 |                 2.525 |                           1 |
| nano   |             4 |        100 |        0 |      1503.51  |                1915.77  |                 2.511 |                           3 |
| nano   |             8 |        112 |        0 |      3238.82  |                3593.26  |                 2.477 |                           7 |
| nano   |            16 |        127 |        0 |      8299.82  |                8748.1   |                 2.292 |                          15 |
| nano   |            32 |        207 |       30 |     14580.6   |               14918     |                 2.375 |                          31 |
| spark  |             1 |        172 |        0 |        33.453 |                 215.385 |                 4.747 |                           0 |
| spark  |             2 |        177 |        0 |       238.271 |                 420.089 |                 4.824 |                           1 |
| spark  |             4 |        184 |        0 |       652.773 |                 834.169 |                 4.828 |                           3 |
| spark  |             8 |        195 |        0 |      1490.9   |                1672.22  |                 4.821 |                           7 |
| spark  |            16 |        220 |        0 |      3152.81  |                3335.76  |                 4.827 |                          15 |
| spark  |            32 |        281 |       13 |      6455.33  |                6860.26  |                 4.828 |                          31 |

## 해석 경계

- 요청은 워커 API에 직접 전달해 프록시의 세 노드 snapshot lock 시간을 모델 포화로 오인하지 않았다.
- 모델, prompt, max tokens, worker concurrency는 동일하게 고정했다.
- block 안의 node×concurrency 조건 순서는 seed `20260904`로 무작위화해 시간·열·공유 클러스터 부하의 순서 편향을 줄였다.
- CPU/온도/queue 표본은 보존하지만 서버 GPU 값은 기존 workload와 공유되어 Llama에 귀속하지 않는다.
- Orin Nano GPU와 실제 AGX Orin·DGX Spark 도입 시 같은 GPU runner로 다시 측정한
  값으로 이 기준을 교체해야 한다.

## 그림

- `figures/p95-ttft.png`: 동시성별 p95 TTFT와 1,500ms SLO
- `figures/throughput.png`: 동시성별 완료 처리량
- `figures/p95-latency.png`: 동시성별 client p95 latency
- `figures/p95-queue.png`: 동시성별 관측 queue p95

동시성이 2배씩 증가하므로 그림 x축은 명시적인 log2 scale을 사용한다. 그림은 색상 외 marker와 line style도 함께 사용하며, 동일 표의 CSV가 접근 가능한 원자료 대안이다.
