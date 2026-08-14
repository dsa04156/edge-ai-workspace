from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from threading import Lock

from .config import Settings
from .model_adapter import PumpModelAdapter, build_model_adapter
from .models import (
    AccelerationFrame,
    AxisSample,
    ComponentScores,
    InferenceRequest,
    InferenceResponse,
    TemperatureFeatureObservation,
    VibrationFeatureObservation,
)


class InferenceRequestConflict(ValueError):
    pass


class InferenceInputError(ValueError):
    pass


class InferenceEngine:
    """Serialized, idempotent inference endpoint for the server1 worker.

    The online baseline is stateful, so requests are deliberately processed under
    one lock. Replayed request IDs return the original response without advancing
    model state a second time.
    """

    def __init__(
        self,
        settings: Settings,
        model_adapter: PumpModelAdapter | None = None,
        cache_size: int = 1_000,
    ) -> None:
        self.settings = settings
        self.model_adapter = model_adapter or build_model_adapter(settings)
        self.cache_size = cache_size
        self._cache: OrderedDict[str, tuple[str, InferenceResponse]] = OrderedDict()
        self._lock = Lock()

    @property
    def ready(self) -> bool:
        vibration, temperature = self.model_adapter.snapshots()
        return (
            self.model_adapter.runtime_ready
            and min(vibration.sample_count, temperature.sample_count)
            >= self.settings.warmup_samples
        )

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        fingerprint = _fingerprint(request)
        with self._lock:
            cached = self._cache.get(request.request_id)
            if cached is not None:
                cached_fingerprint, response = cached
                if cached_fingerprint != fingerprint:
                    raise InferenceRequestConflict(
                        "requestId was reused with another payload"
                    )
                self._cache.move_to_end(request.request_id)
                return response

            lag_ns = abs(request.frame.origin - request.temperature.origin)
            maximum_lag_ns = int(self.settings.context_max_skew_seconds * 1_000_000_000)
            if lag_ns > maximum_lag_ns:
                raise InferenceInputError(
                    "frame and temperature origins exceed the alignment contract"
                )

            self.model_adapter.ingest_temperature(
                AxisSample(
                    origin=request.temperature.origin,
                    value_type="Float64",
                    value=request.temperature.value,
                )
            )
            decision = self.model_adapter.infer(
                AccelerationFrame(
                    origin=request.frame.origin,
                    x=request.frame.x,
                    y=request.frame.y,
                    z=request.frame.z,
                ),
                request.temperature.origin,
            )
            if decision is None:
                raise InferenceInputError("temperature context was not available")

            response = InferenceResponse(
                request_id=request.request_id,
                input_contract=request.input_contract,
                origin=request.frame.origin,
                status=decision.status,
                anomaly=decision.status == "anomaly",
                score=decision.score,
                component_scores=ComponentScores(
                    vibration=decision.vibration_score,
                    temperature=decision.temperature_score,
                ),
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
                    alignment_lag_ms=round(lag_ns / 1_000_000, 3),
                ),
                model_state="ready" if self.ready else "warming_up",
                model_version=self.model_adapter.version,
            )
            self._cache[request.request_id] = (fingerprint, response)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            return response


def _fingerprint(request: InferenceRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
