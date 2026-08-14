from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Protocol

from .alignment import TemporalAligner
from .config import Settings
from .contracts import Measurement, PumpMotorSignals, PumpMotorTelemetry
from .joiner import FrameJoiner
from .local_data import (
    ACCELERATION_SOURCES,
    TEMPERATURE_SOURCE,
    AxisSource,
    LocalDataClient,
    LocalDataSource,
    ScalarSource,
)
from .model_adapter import ModelDecision, PumpModelAdapter, build_model_adapter
from .models import (
    AccelerationFrame,
    AlertTransition,
    AxisSample,
    AxisValues,
    ComponentScores,
    FeatureModelObservation,
    FeatureModelSnapshot,
    InferenceRoutingStatus,
    LatestObservation,
    ModelObservation,
    RuntimeCounters,
    ScoreWeights,
    ServiceStatus,
    SourceIdentity,
    TemperatureFeatureObservation,
    VibrationFeatureObservation,
)
from .performance import PerformanceTracker
from .resource_observation import ProcessResourceTracker
from .remote_inference import (
    RemoteInferenceClient,
    RemoteInferenceRouter,
    RoutedInference,
)
from .storage import ResultStore


class LocalDataReader(Protocol):
    async def fetch(
        self,
        source: LocalDataSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]: ...

    async def close(self) -> None: ...


class InferenceRouter(Protocol):
    async def infer(
        self,
        frame: AccelerationFrame,
        temperature: AxisSample,
        *,
        local: Callable[[], ModelDecision | None],
        now: datetime | None = None,
    ) -> RoutedInference | None: ...

    def status(
        self,
        *,
        now: datetime | None = None,
    ) -> InferenceRoutingStatus: ...

    async def close(self) -> None: ...


class AnomalyRuntime:
    def __init__(
        self,
        settings: Settings,
        client: LocalDataReader,
        sources: tuple[AxisSource, ...] = ACCELERATION_SOURCES,
        context_source: ScalarSource = TEMPERATURE_SOURCE,
        model_adapter: PumpModelAdapter | None = None,
        inference_router: InferenceRouter | None = None,
        result_store: ResultStore | None = None,
        resource_tracker: ProcessResourceTracker | None = None,
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
        self.model_adapter = model_adapter or build_model_adapter(settings)
        self.inference_router = inference_router or RemoteInferenceRouter(
            mode="disabled",
            approval_id=None,
            client=None,
            failure_threshold=settings.remote_inference_failure_threshold,
            rollback_cooldown_seconds=(
                settings.remote_inference_rollback_cooldown_seconds
            ),
        )
        self._cursors: dict[str, int | None] = {
            source.key: None for source in self._all_sources
        }
        self.result_store = result_store or ResultStore(
            ":memory:",
            settings.recent_result_limit,
        )
        self._results: deque[LatestObservation] = deque(
            self.result_store.results(settings.recent_result_limit),
            maxlen=settings.recent_result_limit,
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
        self._store_closed = False
        self._router_closed = False
        self.performance = PerformanceTracker()
        self.resource_tracker = resource_tracker or ProcessResourceTracker()

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
        if not self._store_closed:
            self.result_store.close()
            self._store_closed = True
        if not self._router_closed:
            await self.inference_router.close()
            self._router_closed = True

    @property
    def worker_started(self) -> bool:
        return self._task is not None and not self._task.done()

    async def poll_once(self, now_ns: int | None = None) -> None:
        poll_started = time.perf_counter()
        frames_before = self._frames_processed
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
            model_input = self._model_input(row.acceleration, row.temperature)
            validated_frame = AccelerationFrame(
                origin=row.acceleration.origin,
                x=model_input.signals.acceleration_x.value,
                y=model_input.signals.acceleration_y.value,
                z=model_input.signals.acceleration_z.value,
            )
            local_decision = self.model_adapter.infer(
                validated_frame,
                row.temperature.origin,
            )
            routed = await self.inference_router.infer(
                validated_frame,
                row.temperature,
                local=lambda: local_decision,
                now=datetime.fromtimestamp(current / 1_000_000_000, timezone.utc),
            )
            if routed is None:
                continue
            decision = routed.decision
            if decision is None:
                continue
            observation = LatestObservation(
                origin=row.acceleration.origin,
                observed_at=datetime.fromtimestamp(
                    row.acceleration.origin / 1_000_000_000,
                    timezone.utc,
                ),
                values=AxisValues(
                    x=model_input.signals.acceleration_x.value,
                    y=model_input.signals.acceleration_y.value,
                    z=model_input.signals.acceleration_z.value,
                ),
                magnitude=round(
                    math.sqrt(
                        model_input.signals.acceleration_x.value**2
                        + model_input.signals.acceleration_y.value**2
                        + model_input.signals.acceleration_z.value**2
                    ),
                    6,
                ),
                score=decision.score,
                anomaly=decision.status == "anomaly",
                model_version=self.model_adapter.version,
                component_scores=ComponentScores(
                    vibration=decision.vibration_score,
                    temperature=decision.temperature_score,
                ),
                weights=self._weights(),
                vibration_features=VibrationFeatureObservation(
                    rms=decision.vibration_features.rms,
                    peak=decision.vibration_features.peak,
                    kurtosis=decision.vibration_features.kurtosis,
                    sample_count=decision.vibration_features.sample_count,
                ),
                temperature_features=TemperatureFeatureObservation(
                    origin=decision.temperature_features.origin,
                    raw=decision.temperature_features.raw,
                    mean=decision.temperature_features.mean,
                    stddev=decision.temperature_features.stddev,
                    delta=decision.temperature_features.delta,
                    sample_count=decision.temperature_features.sample_count,
                    alignment_lag_ms=round(
                        abs(
                            row.acceleration.origin
                            - decision.temperature_features.origin
                        )
                        / 1_000_000,
                        3,
                    ),
                ),
                input_contract=model_input.schema_version,
                inference_target=routed.target,
                augmentation_approval_id=(
                    self.inference_router.status(
                        now=datetime.fromtimestamp(
                            current / 1_000_000_000,
                            timezone.utc,
                        )
                    ).approval_id
                    if routed.target == "server1"
                    else None
                ),
            )
            self.result_store.record_result(
                observation,
                asset_id=self.settings.service_asset_id,
            )
            self._results.append(observation)
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
        self.performance.observe(
            processing_latency_ms=(time.perf_counter() - poll_started) * 1_000,
            processed_frames=self._frames_processed - frames_before,
            backlog=len(self.joiner.pending_origins) + len(self.aligner.pending_origins),
            observed_at=current / 1_000_000_000,
        )

    def status(self, now_ns: int | None = None) -> ServiceStatus:
        current = time.time_ns() if now_ns is None else now_ns
        latest = self._results[-1] if self._results else None
        vibration_snapshot, temperature_snapshot = self.model_adapter.snapshots()
        drop_count = self.aligner.counters.unaligned_frames_dropped
        sample_count = min(
            vibration_snapshot.sample_count,
            temperature_snapshot.sample_count,
        )
        model_state = (
            "ready" if sample_count >= self.settings.warmup_samples else "warming_up"
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
                else "anomaly"
                if latest.anomaly
                else "normal"
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
                algorithm=self.model_adapter.algorithm,
                version=self.model_adapter.version,
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
            performance=self.performance.snapshot(
                observed_at=current / 1_000_000_000,
            ),
            process_resources=self.resource_tracker.snapshot(),
            inference_routing=self.inference_router.status(
                now=datetime.fromtimestamp(current / 1_000_000_000, timezone.utc),
            ),
            last_error=self._last_error,
        )

    def results(
        self,
        limit: int,
        *,
        anomaly: bool | None = None,
        from_origin: int | None = None,
        to_origin: int | None = None,
    ) -> list[LatestObservation]:
        return self.result_store.results(
            limit,
            anomaly=anomaly,
            from_origin=from_origin,
            to_origin=to_origin,
        )

    def alerts(
        self,
        limit: int,
        *,
        status: str | None = None,
    ) -> list[AlertTransition]:
        return self.result_store.alerts(limit, status=status)

    def storage_status(self):
        return self.result_store.status()

    def _process_temperatures(self, samples: list[AxisSample]) -> None:
        for sample in samples:
            self.model_adapter.ingest_temperature(sample)
            self._context_samples_processed += 1
        self.model_adapter.trim_temperature_state(self.settings.max_pending_frames)

    def _weights(self) -> ScoreWeights:
        return ScoreWeights(
            vibration=self.settings.vibration_weight,
            temperature=self.settings.temperature_weight,
        )

    def _model_input(
        self,
        acceleration: AccelerationFrame,
        temperature: AxisSample,
    ) -> PumpMotorTelemetry:
        observed_at = datetime.fromtimestamp(
            acceleration.origin / 1_000_000_000,
            timezone.utc,
        )
        return PumpMotorTelemetry(
            event_id=(
                f"live-{self.settings.service_node_id}-"
                f"{self.settings.service_device_id}-{acceleration.origin}"
            ),
            source_type="sensor",
            device_id=self.settings.service_device_id,
            asset_id=self.settings.service_asset_id,
            node_id=self.settings.service_node_id,
            observed_at=observed_at,
            signals=PumpMotorSignals(
                acceleration_x=Measurement(value=float(acceleration.x)),
                acceleration_y=Measurement(value=float(acceleration.y)),
                acceleration_z=Measurement(value=float(acceleration.z)),
                temperature=Measurement(value=float(temperature.value)),
            ),
            attributes={
                "accelerationOrigin": str(acceleration.origin),
                "temperatureOrigin": str(temperature.origin),
            },
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


def build_runtime(
    settings: Settings,
    model_adapter: PumpModelAdapter | None = None,
) -> AnomalyRuntime:
    remote_client = (
        RemoteInferenceClient(
            base_url=settings.remote_inference_url or "",
            timeout_seconds=settings.remote_inference_timeout_seconds,
            max_attempts=settings.remote_inference_max_attempts,
        )
        if settings.remote_inference_mode == "approved"
        else None
    )
    return AnomalyRuntime(
        settings=settings,
        client=LocalDataClient(
            settings.local_data_base_url,
            settings.http_timeout_seconds,
        ),
        model_adapter=model_adapter or build_model_adapter(settings),
        inference_router=RemoteInferenceRouter(
            mode=settings.remote_inference_mode,
            approval_id=settings.remote_inference_approval_id,
            client=remote_client,
            failure_threshold=settings.remote_inference_failure_threshold,
            rollback_cooldown_seconds=(
                settings.remote_inference_rollback_cooldown_seconds
            ),
        ),
        result_store=ResultStore(
            settings.result_db_path,
            settings.result_retention_rows,
        ),
    )
