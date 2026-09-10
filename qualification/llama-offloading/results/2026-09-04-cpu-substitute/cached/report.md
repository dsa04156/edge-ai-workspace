# Llama 3.2 1B 오프로딩 비교 결과

## 성능 비교

| method           |   requests |   mean_latency_ms |   p95_latency_ms |   mean_ttft_ms |   p95_ttft_ms |   mean_tokens_per_second |   throughput_requests_per_second |   slo_violation_union_seconds |
|:-----------------|-----------:|------------------:|-----------------:|---------------:|--------------:|-------------------------:|---------------------------------:|------------------------------:|
| Always-On        |          0 |           nan     |          nan     |        nan     |       nan     |                  nan     |                          nan     |                         0.000 |
| Cold On-Demand   |          0 |           nan     |          nan     |        nan     |       nan     |                  nan     |                          nan     |                         0.000 |
| Cached On-Demand |       1396 |          1818.153 |         6570.638 |       1343.659 |      4770.175 |                   39.405 |                            3.670 |                       124.553 |

## Activation 비교

| method           | node   |   activation_time_ms |   worker_start_ms |   model_remote_download_ms |   model_load_ms |   first_offloaded_request_latency_ms |
|:-----------------|:-------|---------------------:|------------------:|---------------------------:|----------------:|-------------------------------------:|
| Cold On-Demand   | AGX    |              nan     |           nan     |                    nan     |         nan     |                              nan     |
| Cold On-Demand   | SPARK  |              nan     |           nan     |                    nan     |         nan     |                              nan     |
| Cached On-Demand | AGX    |             1187.222 |             1.092 |                      0.000 |        1181.609 |                             1535.747 |
| Cached On-Demand | SPARK  |             1187.079 |             0.380 |                      0.000 |        1182.687 |                             1609.976 |

## 자원 사용 비교

| method           | node   |   idle_gpu_memory_mib |   idle_inference_runner_rss_mib |   average_gpu_utilization_percent |   average_ram_utilization_percent |   idle_power_watts | gpu_attribution_note           |
|:-----------------|:-------|----------------------:|--------------------------------:|----------------------------------:|----------------------------------:|-------------------:|:-------------------------------|
| Always-On        | NANO   |                   nan |                         nan     |                               nan |                           nan     |                nan | direct measurement unavailable |
| Always-On        | AGX    |                   nan |                         nan     |                               nan |                           nan     |                nan | direct measurement unavailable |
| Always-On        | SPARK  |                   nan |                         nan     |                               nan |                           nan     |                nan | direct measurement unavailable |
| Cold On-Demand   | NANO   |                   nan |                         nan     |                               nan |                           nan     |                nan | direct measurement unavailable |
| Cold On-Demand   | AGX    |                   nan |                         nan     |                               nan |                           nan     |                nan | direct measurement unavailable |
| Cold On-Demand   | SPARK  |                   nan |                         nan     |                               nan |                           nan     |                nan | direct measurement unavailable |
| Cached On-Demand | NANO   |                   nan |                        1654.123 |                               nan |                            41.914 |                nan | direct measurement unavailable |
| Cached On-Demand | AGX    |                   nan |                           0.000 |                               nan |                            18.277 |                nan | direct measurement unavailable |
| Cached On-Demand | SPARK  |                   nan |                           0.000 |                               nan |                            24.955 |                nan | direct measurement unavailable |

## Break-even

| method           | selected_node   |   requested_concurrency |   count |   mean |   median |
|:-----------------|:----------------|------------------------:|--------:|-------:|---------:|
| cached_on_demand | agx             |                       1 |       0 |    nan |      nan |
| cached_on_demand | agx             |                       8 |       0 |    nan |      nan |
| cached_on_demand | agx             |                      16 |       0 |    nan |      nan |
| cached_on_demand | spark           |                       1 |       0 |    nan |      nan |
| cached_on_demand | spark           |                      16 |       0 |    nan |      nan |
| cached_on_demand | spark           |                      32 |       0 |    nan |      nan |

GPU memory와 power는 직접 귀속 가능한 계측값이 없으면 NaN으로 유지했다. inference runner RSS는 GPU memory의 대체값이지 같은 측정값이 아니다.
