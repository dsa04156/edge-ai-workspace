from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from .models import ProcessResourceObservation


def read_process_rss_bytes() -> int | None:
    """Read the current process RSS without requiring host or cgroup access."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


class ProcessResourceTracker:
    """Interval CPU and current RSS for the service's main process.

    This is deliberately labelled as process scope. It is a fail-closed fallback
    when the central cluster cannot observe the KubeEdge Pod through cAdvisor.
    """

    def __init__(
        self,
        *,
        wall_clock: Callable[[], float] = time.monotonic,
        cpu_clock: Callable[[], float] = time.process_time,
        rss_reader: Callable[[], int | None] = read_process_rss_bytes,
        minimum_interval_seconds: float = 1.0,
    ) -> None:
        if minimum_interval_seconds <= 0:
            raise ValueError("minimum interval must be positive")
        self._wall_clock = wall_clock
        self._cpu_clock = cpu_clock
        self._rss_reader = rss_reader
        self._minimum_interval_seconds = float(minimum_interval_seconds)
        self._previous_wall: float | None = None
        self._previous_cpu: float | None = None
        self._last_cpu_cores: float | None = None
        self._last_interval: float | None = None
        self._lock = Lock()

    def snapshot(self) -> ProcessResourceObservation:
        with self._lock:
            wall = self._wall_clock()
            cpu = self._cpu_clock()
            rss_bytes = self._rss_reader()
            interval = None
            cpu_cores = self._last_cpu_cores
            if self._previous_wall is not None and self._previous_cpu is not None:
                interval = wall - self._previous_wall
                if interval >= self._minimum_interval_seconds:
                    cpu_cores = max(0.0, (cpu - self._previous_cpu) / interval)
                    self._last_cpu_cores = cpu_cores
                    self._last_interval = interval
                    self._previous_wall = wall
                    self._previous_cpu = cpu
            else:
                self._previous_wall = wall
                self._previous_cpu = cpu

        memory_mib = rss_bytes / 1024 / 1024 if rss_bytes is not None else None
        valid = cpu_cores is not None and memory_mib is not None
        return ProcessResourceObservation(
            observed_at=datetime.now(timezone.utc),
            cpu_cores=round(cpu_cores, 6) if cpu_cores is not None else None,
            memory_rss_mib=round(memory_mib, 3) if memory_mib is not None else None,
            sample_interval_seconds=self._last_interval,
            metrics_valid=valid,
        )
