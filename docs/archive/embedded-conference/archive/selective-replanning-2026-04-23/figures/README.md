# Selective Replanning Log Figures

Source logs: `docs/archive/embedded-conference/archive/selective-replanning-2026-04-23/*/*.json`

Regenerate:

```bash
python3 docs/archive/embedded-conference/experiments/plot_selective_replanning_logs.py
```

## Figures

### 1. E2E p95 latency

![E2E p95 latency](01_e2e_p95_latency.png)

### 2. Throughput

![Throughput](02_throughput.png)

### 3. Migration decision quality

![Migration decision quality](03_migration_quality.png)

### 4. Adaptive net gain

![Adaptive net gain](04_adaptive_net_gain.png)

### 5. Heavy burst stage composition

![Heavy burst stage composition](05_heavy_burst_stage_composition.png)

### 6. Poster static baseline and migration summary

![Poster static baseline and migration summary](06_poster_static_latency_migration_summary.png)

### 7. Poster two-panel latency and migration quality

![Poster two-panel latency and migration quality](07_poster_two_panel_latency_migration_quality.png)

### 8. Poster two-panel E2E latency and throughput

![Poster two-panel E2E latency and throughput](08_poster_two_panel_e2e_throughput.png)
