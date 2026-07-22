from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Protocol

from .config import Settings
from .detector import DetectorConfig, OnlineGaussianDetector
from .joiner import FrameJoiner
from .local_data import ACCELERATION_SOURCES, AxisSource, LocalDataClient
from .models import (
    AxisSample,
    AxisValues,
    LatestObservation,
    ModelObservation,
    RuntimeCounters,
    ServiceStatus,
    SourceIdentity,
)


class LocalDataReader(Protocol):
    async def fetch(
        self,
        source: AxisSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]: ...

    async def close(self) -> None: ...


class AnomalyRuntime:
    def __init__(
        self,
        settings: Settings,
        client: LocalDataReader,
        sources: tuple[AxisSource, ...] = ACCELERATION_SOURCES,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sources = sources
        self.joiner = FrameJoiner(
            pending_ttl_ns=int(settings.pending_ttl_seconds * 1_000_000_000),
            max_pending=settings.max_pending_frames,
        )
        self.detector = OnlineGaussianDetector(
            DetectorConfig(
                warmup_samples=settings.warmup_samples,
                threshold=settings.anomaly_threshold,
                stddev_floor=settings.stddev_floor,
                anomaly_streak=settings.anomaly_streak,
                clear_streak=settings.clear_streak,
                ewma_alpha=settings.ewma_alpha,
            )
        )
        self._cursors: dict[str, int | None] = {
            source.axis: None for source in sources
        }
        self._results: deque[LatestObservation] = deque(
            maxlen=settings.recent_result_limit
        )
        self._frames_processed = 0
        self._input_errors = 0
        self._consecutive_failed_polls = 0
        self._last_error: str | None = None
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._client_closed = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            await task
            self._task = None
        if not self._client_closed:
            await self.client.close()
            self._client_closed = True

    @property
    def worker_started(self) -> bool:
        return self._task is not None and not self._task.done()

    async def poll_once(self, now_ns: int | None = None) -> None:
        current = time.time_ns() if now_ns is None else now_ns
        rows_by_source = await asyncio.gather(
            *(
                self.client.fetch(
                    source,
                    None
                    if self._cursors[source.axis] is None
                    else self._cursors[source.axis] + 1,
                    current,
                )
                for source in self.sources
            ),
            return_exceptions=True,
        )

        first_error: str | None = None
        for source, rows in zip(self.sources, rows_by_source, strict=True):
            if isinstance(rows, Exception):
                self._input_errors += 1
                if first_error is None:
                    first_error = f"{rows.__class__.__name__}: {rows}"
                continue
            if rows:
                self._cursors[source.axis] = max(row.origin for row in rows)
            for frame in self.joiner.ingest(source.axis, rows, current):
                result = self.detector.process(frame)
                self._results.append(
                    LatestObservation(
                        origin=result.origin,
                        observed_at=datetime.fromtimestamp(
                            current / 1_000_000_000,
                            timezone.utc,
                        ),
                        values=AxisValues(x=result.x, y=result.y, z=result.z),
                        magnitude=result.magnitude,
                        score=result.score,
                        anomaly=result.anomaly,
                    )
                )
                self._frames_processed += 1

        if first_error is None:
            self._consecutive_failed_polls = 0
            self._last_error = None
        else:
            self._consecutive_failed_polls += 1
            self._last_error = first_error

    def status(self, now_ns: int | None = None) -> ServiceStatus:
        current = time.time_ns() if now_ns is None else now_ns
        latest = self._results[-1] if self._results else None
        snapshot = self.detector.snapshot()
        model_state = (
            "ready"
            if snapshot.sample_count >= snapshot.warmup_samples
            else "warming_up"
        )
        if self._consecutive_failed_polls >= 3:
            runtime_status = "degraded"
            input_state = "error"
        elif latest is None:
            runtime_status = "starting"
            input_state = "waiting"
        elif current - latest.origin > int(
            self.settings.input_stale_seconds * 1_000_000_000
        ):
            runtime_status = "degraded"
            input_state = "stale"
        else:
            input_state = "fresh"
            runtime_status = (
                "warming_up"
                if model_state == "warming_up"
                else "anomaly" if latest.anomaly else "normal"
            )

        return ServiceStatus(
            status=runtime_status,
            input_state=input_state,
            model_state=model_state,
            source=SourceIdentity(devices=[source.device_name for source in self.sources]),
            latest=latest,
            model=ModelObservation(
                algorithm=snapshot.algorithm,
                sample_count=snapshot.sample_count,
                warmup_samples=snapshot.warmup_samples,
                threshold=snapshot.threshold,
                baseline_mean=snapshot.baseline_mean,
                baseline_stddev=snapshot.baseline_stddev,
                stddev_floor=snapshot.stddev_floor,
            ),
            counters=RuntimeCounters(
                frames_processed=self._frames_processed,
                duplicates_ignored=self.joiner.counters.duplicates_ignored,
                incomplete_frames_dropped=(
                    self.joiner.counters.incomplete_frames_dropped
                ),
                input_errors=self._input_errors,
            ),
            last_error=self._last_error,
        )

    def results(self, limit: int) -> list[LatestObservation]:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be from 1 through 1000")
        return list(self._results)[-limit:]

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.poll_interval_seconds,
                )
            except TimeoutError:
                continue


def build_runtime(settings: Settings) -> AnomalyRuntime:
    return AnomalyRuntime(
        settings=settings,
        client=LocalDataClient(
            settings.local_data_base_url,
            settings.http_timeout_seconds,
        ),
    )
