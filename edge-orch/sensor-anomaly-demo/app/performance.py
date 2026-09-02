from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import ServicePerformance


@dataclass(frozen=True)
class PerformanceSample:
    observed_at: float
    processing_latency_ms: float
    processed_frames: int
    backlog: int


class PerformanceTracker:
    """Bounded in-process service SLI window used by the read-only evaluator."""

    def __init__(
        self,
        *,
        window_seconds: float = 300,
        minimum_samples: int = 3,
        stale_seconds: float = 30,
    ) -> None:
        if window_seconds <= 0 or minimum_samples < 1 or stale_seconds <= 0:
            raise ValueError("performance tracker settings must be positive")
        self.window_seconds = float(window_seconds)
        self.minimum_samples = minimum_samples
        self.stale_seconds = float(stale_seconds)
        self._samples: deque[PerformanceSample] = deque()

    def observe(
        self,
        *,
        processing_latency_ms: float,
        processed_frames: int,
        backlog: int,
        observed_at: float | None = None,
    ) -> None:
        timestamp = time.time() if observed_at is None else float(observed_at)
        self._samples.append(
            PerformanceSample(
                observed_at=timestamp,
                processing_latency_ms=max(0.0, float(processing_latency_ms)),
                processed_frames=max(0, int(processed_frames)),
                backlog=max(0, int(backlog)),
            )
        )
        self._trim(timestamp)

    def snapshot(self, *, observed_at: float | None = None) -> ServicePerformance:
        timestamp = time.time() if observed_at is None else float(observed_at)
        self._trim(timestamp)
        samples = list(self._samples)
        latest = samples[-1] if samples else None
        latencies = sorted(sample.processing_latency_ms for sample in samples)
        p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
        p95 = latencies[p95_index] if latencies else 0.0
        elapsed = (
            max(samples[-1].observed_at - samples[0].observed_at, 1.0)
            if samples
            else 1.0
        )
        throughput = sum(sample.processed_frames for sample in samples) / elapsed
        is_fresh = latest is not None and timestamp - latest.observed_at <= self.stale_seconds
        return ServicePerformance(
            observed_at=datetime.fromtimestamp(timestamp, timezone.utc),
            window_seconds=self.window_seconds,
            processing_latency_p95_ms=round(p95, 3),
            backlog=latest.backlog if latest is not None else 0,
            throughput_per_second=round(throughput, 3),
            sample_count=len(samples),
            metrics_valid=len(samples) >= self.minimum_samples and is_fresh,
        )

    def _trim(self, observed_at: float) -> None:
        cutoff = observed_at - self.window_seconds
        while self._samples and self._samples[0].observed_at < cutoff:
            self._samples.popleft()
