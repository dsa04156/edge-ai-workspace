from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Protocol

from .alignment import TemporalAligner
from .config import Settings
from .feature_detector import (
    FeatureDetectorConfig,
    OnlineFeatureDetector,
    ScoreLatch,
)
from .features import SlidingFeatureExtractor
from .joiner import FrameJoiner
from .local_data import (
    ACCELERATION_SOURCES,
    TEMPERATURE_SOURCE,
    AxisSource,
    LocalDataClient,
    LocalDataSource,
    ScalarSource,
)
from .models import (
    AxisSample,
    AxisValues,
    ComponentScores,
    FeatureInferenceResult,
    FeatureModelSnapshot,
    FeatureModelObservation,
    LatestObservation,
    ModelObservation,
    RuntimeCounters,
    ScoreWeights,
    ServiceStatus,
    SourceIdentity,
    TemperatureFeatureObservation,
    TemperatureFeatures,
    VibrationFeatureObservation,
)


PIPELINE_ALGORITHM = "weighted-multi-sensor-feature-score-v1"
VIBRATION_ALGORITHM = "online-vibration-feature-gaussian-v1"
TEMPERATURE_ALGORITHM = "online-temperature-feature-gaussian-v1"


class LocalDataReader(Protocol):
    async def fetch(
        self,
        source: LocalDataSource,
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
        context_source: ScalarSource = TEMPERATURE_SOURCE,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sources = sources
        self.context_source = context_source
        self._all_sources: tuple[LocalDataSource, ...] = (*sources, context_source)
        self.joiner = FrameJoiner(
            pending_ttl_ns=int(settings.pending_ttl_seconds * 1_000_000_000),
            max_pending=settings.max_pending_frames,
        )
        self.aligner = TemporalAligner(
            max_skew_ns=int(settings.context_max_skew_seconds * 1_000_000_000),
            pending_ttl_ns=int(settings.pending_ttl_seconds * 1_000_000_000),
            max_pending=settings.max_pending_frames,
        )
        self.extractor = SlidingFeatureExtractor(
            vibration_window_samples=settings.vibration_window_samples,
            temperature_window_samples=settings.temperature_window_samples,
        )
        shared_detector = {
            "warmup_samples": settings.warmup_samples,
            "threshold": settings.anomaly_threshold,
            "stddev_floor": settings.stddev_floor,
            "anomaly_streak": settings.anomaly_streak,
            "clear_streak": settings.clear_streak,
            "ewma_alpha": settings.ewma_alpha,
        }
        self.vibration_detector = OnlineFeatureDetector(
            FeatureDetectorConfig(
                algorithm=VIBRATION_ALGORITHM,
                feature_names=("rms", "peak", "kurtosis"),
                stddev_floor_overrides={"kurtosis": 0.1},
                **shared_detector,
            )
        )
        self.temperature_detector = OnlineFeatureDetector(
            FeatureDetectorConfig(
                algorithm=TEMPERATURE_ALGORITHM,
                feature_names=("mean", "stddev", "delta"),
                stddev_floor_overrides={"stddev": 0.1, "delta": 0.1},
                **shared_detector,
            )
        )
        self.score_latch = ScoreLatch(
            threshold=settings.anomaly_threshold,
            anomaly_streak=settings.anomaly_streak,
            clear_streak=settings.clear_streak,
        )
        self._cursors: dict[str, int | None] = {
            source.key: None for source in self._all_sources
        }
        self._temperature_results: dict[
            int, tuple[TemperatureFeatures, FeatureInferenceResult]
        ] = {}
        self._results: deque[LatestObservation] = deque(
            maxlen=settings.recent_result_limit
        )
        self._frames_processed = 0
        self._context_samples_processed = 0
        self._input_errors = 0
        self._consecutive_failed_polls = 0
        self._last_error: str | None = None
        self._last_unaligned_drops = 0
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
                    if self._cursors[source.key] is None
                    else self._cursors[source.key] + 1,
                    current,
                )
                for source in self._all_sources
            ),
            return_exceptions=True,
        )

        first_error: str | None = None
        successful_rows: dict[str, list[AxisSample]] = {}
        for source, rows in zip(self._all_sources, rows_by_source, strict=True):
            if isinstance(rows, Exception):
                self._input_errors += 1
                successful_rows[source.key] = []
                if first_error is None:
                    first_error = f"{rows.__class__.__name__}: {rows}"
                continue
            successful_rows[source.key] = rows
            if rows:
                self._cursors[source.key] = max(row.origin for row in rows)

        temperatures = successful_rows[self.context_source.key]
        self._process_temperatures(temperatures)

        acceleration_frames = []
        for source in self.sources:
            acceleration_frames.extend(
                self.joiner.ingest(
                    source.axis,
                    successful_rows[source.key],
                    current,
                )
            )

        aligned = self.aligner.ingest(
            acceleration_frames,
            temperatures,
            current,
        )
        for row in aligned:
            temperature_state = self._temperature_results.get(
                row.temperature.origin
            )
            if temperature_state is None:
                continue
            temperature_features, temperature_result = temperature_state
            vibration_features = self.extractor.add_vibration(row.acceleration)
            vibration_result = self.vibration_detector.process(
                row.acceleration.origin,
                vibration_features.values(),
            )
            ready = (
                vibration_result.status != "warming_up"
                and temperature_result.status != "warming_up"
            )
            score = (
                self._fused_score(
                    vibration_result.score,
                    temperature_result.score,
                )
                if ready
                else 0.0
            )
            detection_status = self.score_latch.process(score, ready)
            self._results.append(
                LatestObservation(
                    origin=row.acceleration.origin,
                    observed_at=datetime.fromtimestamp(
                        current / 1_000_000_000,
                        timezone.utc,
                    ),
                    values=AxisValues(
                        x=row.acceleration.x,
                        y=row.acceleration.y,
                        z=row.acceleration.z,
                    ),
                    magnitude=round(
                        math.sqrt(
                            row.acceleration.x**2
                            + row.acceleration.y**2
                            + row.acceleration.z**2
                        ),
                        6,
                    ),
                    score=round(score, 6),
                    anomaly=detection_status == "anomaly",
                    component_scores=ComponentScores(
                        vibration=vibration_result.score,
                        temperature=temperature_result.score,
                    ),
                    weights=self._weights(),
                    vibration_features=VibrationFeatureObservation(
                        rms=vibration_features.rms,
                        peak=vibration_features.peak,
                        kurtosis=vibration_features.kurtosis,
                        sample_count=vibration_features.sample_count,
                    ),
                    temperature_features=TemperatureFeatureObservation(
                        origin=temperature_features.origin,
                        raw=temperature_features.raw,
                        mean=temperature_features.mean,
                        stddev=temperature_features.stddev,
                        delta=temperature_features.delta,
                        sample_count=temperature_features.sample_count,
                        alignment_lag_ms=round(
                            abs(
                                row.acceleration.origin
                                - temperature_features.origin
                            )
                            / 1_000_000,
                            3,
                        ),
                    ),
                )
            )
            self._frames_processed += 1

        drop_count = self.aligner.counters.unaligned_frames_dropped
        dropped_this_poll = drop_count - self._last_unaligned_drops
        self._last_unaligned_drops = drop_count
        if first_error is None:
            self._consecutive_failed_polls = 0
            self._last_error = (
                f"{dropped_this_poll} acceleration frame(s) lacked temperature context"
                if dropped_this_poll > 0
                else None
            )
        else:
            self._consecutive_failed_polls += 1
            self._last_error = first_error

    def status(self, now_ns: int | None = None) -> ServiceStatus:
        current = time.time_ns() if now_ns is None else now_ns
        latest = self._results[-1] if self._results else None
        vibration_snapshot = self.vibration_detector.snapshot()
        temperature_snapshot = self.temperature_detector.snapshot()
        drop_count = self.aligner.counters.unaligned_frames_dropped
        sample_count = min(
            vibration_snapshot.sample_count,
            temperature_snapshot.sample_count,
        )
        model_state = (
            "ready"
            if sample_count >= self.settings.warmup_samples
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
            source=SourceIdentity(
                devices=[source.device_name for source in self._all_sources]
            ),
            latest=latest,
            model=ModelObservation(
                algorithm=PIPELINE_ALGORITHM,
                sample_count=sample_count,
                warmup_samples=self.settings.warmup_samples,
                threshold=self.settings.anomaly_threshold,
                baseline_mean=0.0,
                baseline_stddev=0.0,
                stddev_floor=self.settings.stddev_floor,
                components={
                    "vibration": self._model_observation(vibration_snapshot),
                    "temperature": self._model_observation(temperature_snapshot),
                },
                weights=self._weights(),
            ),
            counters=RuntimeCounters(
                frames_processed=self._frames_processed,
                duplicates_ignored=self.joiner.counters.duplicates_ignored,
                incomplete_frames_dropped=(
                    self.joiner.counters.incomplete_frames_dropped
                ),
                input_errors=self._input_errors,
                context_samples_processed=self._context_samples_processed,
                unaligned_frames_dropped=drop_count,
            ),
            last_error=self._last_error,
        )

    def results(self, limit: int) -> list[LatestObservation]:
        if limit < 1 or limit > 1_000:
            raise ValueError("limit must be from 1 through 1000")
        return list(self._results)[-limit:]

    def _process_temperatures(self, samples: list[AxisSample]) -> None:
        for sample in samples:
            features = self.extractor.add_temperature(sample)
            result = self.temperature_detector.process(
                sample.origin,
                features.values(),
            )
            self._temperature_results[sample.origin] = (features, result)
            self._context_samples_processed += 1
        excess = len(self._temperature_results) - self.settings.max_pending_frames
        if excess > 0:
            for origin in sorted(self._temperature_results)[:excess]:
                self._temperature_results.pop(origin, None)

    def _fused_score(self, vibration: float, temperature: float) -> float:
        total_weight = (
            self.settings.vibration_weight + self.settings.temperature_weight
        )
        return (
            self.settings.vibration_weight * vibration
            + self.settings.temperature_weight * temperature
        ) / total_weight

    def _weights(self) -> ScoreWeights:
        return ScoreWeights(
            vibration=self.settings.vibration_weight,
            temperature=self.settings.temperature_weight,
        )

    @staticmethod
    def _model_observation(
        snapshot: FeatureModelSnapshot,
    ) -> FeatureModelObservation:
        return FeatureModelObservation(
            algorithm=snapshot.algorithm,
            sample_count=snapshot.sample_count,
            warmup_samples=snapshot.warmup_samples,
            threshold=snapshot.threshold,
            feature_means=snapshot.feature_means,
            feature_stddevs=snapshot.feature_stddevs,
            stddev_floors=snapshot.stddev_floors,
        )

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
