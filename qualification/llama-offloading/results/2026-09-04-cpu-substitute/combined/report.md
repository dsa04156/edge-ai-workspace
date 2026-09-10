# Llama 3.2 1B 오프로딩 비교 결과

> 혼합 장비 CPU-only 자격시험 결과다. Nano는 실제 Orin Nano의 CPU-only 행이고, AGX·Spark는 amd64 서버 CPU 대체 행이다. 실제 세 장비의 GPU 성능 결론이 아니다. 총 4015개 요청 중 성공 4015개, 실패 0개다. GPU memory·전력은 직접 귀속 계측이 없어 N/A로 유지했다.

## 성능 비교

| method           |   requests |   mean_latency_ms |   p95_latency_ms |   mean_ttft_ms |   p95_ttft_ms |   mean_tokens_per_second |   throughput_requests_per_second |   slo_violation_union_seconds |
|:-----------------|-----------:|------------------:|-----------------:|---------------:|--------------:|-------------------------:|---------------------------------:|------------------------------:|
| Always-On        |       1460 |          1737.849 |         6597.548 |       1319.614 |      4783.548 |                   40.534 |                            3.853 |                       119.207 |
| Cold On-Demand   |        896 |          3075.483 |         9335.651 |       2372.467 |      7355.714 |                   24.336 |                            2.236 |                       164.763 |
| Cached On-Demand |       1396 |          1818.153 |         6570.638 |       1343.659 |      4770.175 |                   39.405 |                            3.670 |                       124.553 |

## Activation 비교

| method           | node   |   activation_time_ms |   worker_start_ms |   model_remote_download_ms |   model_load_ms |   first_offloaded_request_latency_ms |
|:-----------------|:-------|---------------------:|------------------:|---------------------------:|----------------:|-------------------------------------:|
| Cold On-Demand   | AGX    |            40646.331 |             1.254 |                  39507.390 |        1132.840 |                            41019.212 |
| Cold On-Demand   | SPARK  |            38465.279 |             0.169 |                  37285.098 |        1174.719 |                            38842.388 |
| Cached On-Demand | AGX    |             1187.222 |             1.092 |                      0.000 |        1181.609 |                             1535.747 |
| Cached On-Demand | SPARK  |             1187.079 |             0.380 |                      0.000 |        1182.687 |                             1609.976 |

## 자원 사용 비교

| method           | node   |   idle_gpu_memory_mib |   idle_inference_runner_rss_mib |   local_checkpoint_bytes |   average_gpu_utilization_percent |   average_ram_utilization_percent |   idle_power_watts | gpu_attribution_note           |
|:-----------------|:-------|----------------------:|--------------------------------:|-------------------------:|----------------------------------:|----------------------------------:|-------------------:|:-------------------------------|
| Always-On        | NANO   |                   nan |                        1657.801 |           1321098329.000 |                               nan |                            42.141 |                nan | direct measurement unavailable |
| Always-On        | AGX    |                   nan |                        1372.930 |           1321098329.000 |                               nan |                            19.285 |                nan | direct measurement unavailable |
| Always-On        | SPARK  |                   nan |                        1372.758 |           1321098329.000 |                               nan |                            29.458 |                nan | direct measurement unavailable |
| Cold On-Demand   | NANO   |                   nan |                        1659.754 |           1321098329.000 |                               nan |                            42.194 |                nan | direct measurement unavailable |
| Cold On-Demand   | AGX    |                   nan |                           0.000 |                    0.000 |                               nan |                            18.200 |                nan | direct measurement unavailable |
| Cold On-Demand   | SPARK  |                   nan |                           0.000 |                    0.000 |                               nan |                            25.073 |                nan | direct measurement unavailable |
| Cached On-Demand | NANO   |                   nan |                        1654.123 |           1321098329.000 |                               nan |                            41.914 |                nan | direct measurement unavailable |
| Cached On-Demand | AGX    |                   nan |                           0.000 |           1321098329.000 |                               nan |                            18.277 |                nan | direct measurement unavailable |
| Cached On-Demand | SPARK  |                   nan |                           0.000 |           1321098329.000 |                               nan |                            24.955 |                nan | direct measurement unavailable |

## Break-even

| method           | selected_node   |   requested_concurrency |   count |       mean |     median |
|:-----------------|:----------------|------------------------:|--------:|-----------:|-----------:|
| always_on        | agx             |                       4 |      26 |   1060.225 |    921.672 |
| always_on        | spark           |                       4 |      39 |    975.226 |    928.668 |
| always_on        | spark           |                       8 |      80 |   1697.531 |   1599.766 |
| always_on        | spark           |                      16 |      87 |   3436.624 |   3013.448 |
| always_on        | spark           |                      32 |     104 |   5464.733 |   3979.190 |
| cached_on_demand | agx             |                       1 |       1 |   -983.464 |   -983.464 |
| cached_on_demand | agx             |                       8 |      62 |   1754.843 |   1628.691 |
| cached_on_demand | agx             |                      16 |      25 |   4347.332 |   4296.310 |
| cached_on_demand | spark           |                       1 |       1 |  -1012.472 |  -1012.472 |
| cached_on_demand | spark           |                      16 |      71 |   3483.927 |   3034.170 |
| cached_on_demand | spark           |                      32 |     104 |   5431.742 |   3999.617 |
| cold_on_demand   | agx             |                       1 |       1 | -40448.845 | -40448.845 |
| cold_on_demand   | spark           |                       1 |       1 | -38288.712 | -38288.712 |

### 단순 누적 break-even 임계값

| method           | node   |   nano_service_ms |   remote_inference_plus_rtt_ms |   saved_ms_per_request |   activation_ms |   break_even_requests |   break_even_nano_time_seconds |
|:-----------------|:-------|------------------:|-------------------------------:|-----------------------:|----------------:|----------------------:|-------------------------------:|
| Cold On-Demand   | AGX    |           455.856 |                        258.370 |                197.486 |       40646.331 |                   206 |                         93.906 |
| Cold On-Demand   | SPARK  |           455.856 |                        279.289 |                176.567 |       38465.279 |                   218 |                         99.377 |
| Cached On-Demand | AGX    |           455.856 |                        252.098 |                203.758 |        1187.222 |                     6 |                          2.735 |
| Cached On-Demand | SPARK  |           455.856 |                        281.249 |                174.607 |        1187.079 |                     7 |                          3.191 |

## 질문별 분석

1. 직접 귀속 가능한 GPU memory 값은 없다. runner RSS 대체 계측에서 Always-On 원격 합계는 2745.7 MiB, Cached는 0.0 MiB로 2745.7 MiB 차이다.
2-3. AGX: Cold 첫 offload 41019.2 ms, Cached 1535.7 ms; activation은 40646.3→1187.2 ms로 97.1% 감소했다.
2-3. SPARK: Cold 첫 offload 38842.4 ms, Cached 1610.0 ms; activation은 38465.3→1187.1 ms로 96.9% 감소했다.
4. concurrency 32의 Always-On: Nano-only 대비 p95 latency 53.0% 개선, throughput 102.3% 증가했다.
4. concurrency 32의 Cached On-Demand: Nano-only 대비 p95 latency 53.1% 개선, throughput 102.6% 증가했다.
4. concurrency 32의 Cold On-Demand: Nano-only 대비 p95 latency -0.2% 개선, throughput -1.8% 증가했다.
5. Cached는 원격 runner RSS 2745.7 MiB를 유휴 시 반환했고, 전체 p95 latency는 Always-On 대비 -0.4% 차이였다.
6. 이 혼합 장비 CPU-only 시험에서 activation 대비 첫 요청 latency가 더 낮은 역할은 AGX였다. 실제 AGX Orin/DGX Spark GPU 결론으로 일반화할 수 없다.
7. activation을 포함한 gain이 0 이하인 짧은 burst는 원격을 켜지 않는 편이 낫다. Cold 방식은 체크포인트 전송 시간이 길어 이 구간이 특히 크다.
8. 단일 요청 service-time 차이를 누적하는 단순 break-even 추정은 Cold On-Demand/AGX 약 206 requests 또는 Nano 순차시간 93.9s, Cold On-Demand/SPARK 약 218 requests 또는 Nano 순차시간 99.4s, Cached On-Demand/AGX 약 6 requests 또는 Nano 순차시간 2.7s, Cached On-Demand/SPARK 약 7 requests 또는 Nano 순차시간 3.2s다. queueing과 병렬성은 제외한 자격시험용 근사치다.


GPU memory와 power는 직접 귀속 가능한 계측값이 없으면 NaN으로 유지했다. inference runner RSS는 GPU memory의 대체값이지 같은 측정값이 아니다.
