# Llama offloading comparison

| scenario | requests | mean_latency_ms | p95_latency_ms | mean_ttft_ms | p95_ttft_ms | mean_tokens_per_second | throughput_requests_per_second | offloading_transitions | offloaded_requests | nano_requests | agx_requests | spark_requests | latency_improvement_percent_vs_nano |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| nano_only | 31 | 2502.999 | 5382.827 | 2131.958 | 5061.897 | 23.901 | 2.224 | 0 | 0 | 31 | 0 | 0 | 0.000 |
| static_nano | 31 | 2311.979 | 5608.648 | 1958.832 | 5274.721 | 24.850 | 2.372 | 0 | 0 | 31 | 0 | 0 | 7.632 |
| static_agx | 31 | 965.706 | 2199.342 | 789.066 | 2027.265 | 45.732 | 4.861 | 0 | 31 | 0 | 31 | 0 | 61.418 |
| static_spark | 31 | 954.090 | 2259.442 | 774.625 | 2080.646 | 45.930 | 4.751 | 0 | 31 | 0 | 0 | 31 | 61.882 |
| dynamic | 62 | 1344.425 | 3188.581 | 1161.043 | 3016.134 | 45.034 | 5.216 | 2 | 60 | 2 | 53 | 7 | 46.287 |
