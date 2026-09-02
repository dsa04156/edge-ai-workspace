from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import Settings
from .cuda_runtime import CudaRuntime, CupyCudaRuntime
from .feature_detector import (
    FeatureDetectorConfig,
    OnlineFeatureDetector,
    ScoreLatch,
)
from .features import SlidingFeatureExtractor
from .models import (
    AccelerationFrame,
    AxisSample,
    DetectionStatus,
    FeatureInferenceResult,
    FeatureModelSnapshot,
    TemperatureFeatures,
    VibrationFeatures,
)

PIPELINE_ALGORITHM = "weighted-multi-sensor-feature-score-v1"
VIBRATION_ALGORITHM = "online-vibration-feature-gaussian-v1"
TEMPERATURE_ALGORITHM = "online-temperature-feature-gaussian-v1"


@dataclass(frozen=True)
class ModelDecision:
    status: DetectionStatus
    score: float
    vibration_score: float
    temperature_score: float
    vibration_features: VibrationFeatures
    temperature_features: TemperatureFeatures


class PumpModelAdapter(Protocol):
    algorithm: str
    version: str
    backend: str
    accelerator: str
    accelerator_device: str
    runtime_ready: bool

    def ingest_temperature(self, sample: AxisSample) -> None: ...

    def infer(
        self,
        frame: AccelerationFrame,
        temperature_origin: int,
    ) -> ModelDecision | None: ...

    def trim_temperature_state(self, maximum: int) -> None: ...

    def snapshots(self) -> tuple[FeatureModelSnapshot, FeatureModelSnapshot]: ...


class OnlineBaselinePumpModel:
    """Replaceable baseline model behind the stable service contract.

    Only this backend is currently implemented. A future ONNX model must
    implement ``PumpModelAdapter`` and receive an explicit model version; an
    unsupported backend is never silently treated as the baseline.
    """

    algorithm = PIPELINE_ALGORITHM
    backend = "online-baseline"
    accelerator = "cpu"
    accelerator_device = "host-cpu"
    runtime_ready = True

    def __init__(
        self,
        settings: Settings,
        cuda_runtime: CudaRuntime | None = None,
    ) -> None:
        self.version = settings.model_version
        self.vibration_weight = settings.vibration_weight
        self.temperature_weight = settings.temperature_weight
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
            ),
            score_vector=(cuda_runtime.score_vector if cuda_runtime else None),
        )
        self.temperature_detector = OnlineFeatureDetector(
            FeatureDetectorConfig(
                algorithm=TEMPERATURE_ALGORITHM,
                feature_names=("mean", "stddev", "delta"),
                stddev_floor_overrides={"stddev": 0.1, "delta": 0.1},
                **shared_detector,
            ),
            score_vector=(cuda_runtime.score_vector if cuda_runtime else None),
        )
        self._cuda_runtime = cuda_runtime
        self.score_latch = ScoreLatch(
            threshold=settings.anomaly_threshold,
            anomaly_streak=settings.anomaly_streak,
            clear_streak=settings.clear_streak,
        )
        self._temperature_results: dict[
            int, tuple[TemperatureFeatures, FeatureInferenceResult]
        ] = {}

    def ingest_temperature(self, sample: AxisSample) -> None:
        features = self.extractor.add_temperature(sample)
        result = self.temperature_detector.process(
            sample.origin,
            features.values(),
        )
        self._temperature_results[sample.origin] = (features, result)

    def infer(
        self,
        frame: AccelerationFrame,
        temperature_origin: int,
    ) -> ModelDecision | None:
        temperature_state = self._temperature_results.get(temperature_origin)
        if temperature_state is None:
            return None
        temperature_features, temperature_result = temperature_state
        vibration_features = self.extractor.add_vibration(frame)
        vibration_result = self.vibration_detector.process(
            frame.origin,
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
        status = self.score_latch.process(score, ready)
        return ModelDecision(
            status=status,
            score=round(score, 6),
            vibration_score=vibration_result.score,
            temperature_score=temperature_result.score,
            vibration_features=vibration_features,
            temperature_features=temperature_features,
        )

    def trim_temperature_state(self, maximum: int) -> None:
        excess = len(self._temperature_results) - maximum
        if excess > 0:
            for origin in sorted(self._temperature_results)[:excess]:
                self._temperature_results.pop(origin, None)

    def snapshots(self) -> tuple[FeatureModelSnapshot, FeatureModelSnapshot]:
        return (
            self.vibration_detector.snapshot(),
            self.temperature_detector.snapshot(),
        )

    def _fused_score(self, vibration: float, temperature: float) -> float:
        if self._cuda_runtime is not None:
            return self._cuda_runtime.weighted_average(
                [vibration, temperature],
                [self.vibration_weight, self.temperature_weight],
            )
        total_weight = self.vibration_weight + self.temperature_weight
        return (
            self.vibration_weight * vibration + self.temperature_weight * temperature
        ) / total_weight


class CudaOnlineBaselinePumpModel(OnlineBaselinePumpModel):
    """The same explainable baseline with detector scoring executed on CUDA."""

    backend = "cuda-online-baseline"
    accelerator = "cuda"

    def __init__(
        self,
        settings: Settings,
        cuda_runtime: CudaRuntime | None = None,
    ) -> None:
        runtime = cuda_runtime or CupyCudaRuntime()
        if not runtime.ready:
            raise RuntimeError("CUDA runtime is not ready")
        self.accelerator_device = runtime.device_name
        self.runtime_ready = runtime.ready
        super().__init__(settings, cuda_runtime=runtime)


def build_model_adapter(settings: Settings) -> PumpModelAdapter:
    if settings.model_backend == "online-baseline":
        return OnlineBaselinePumpModel(settings)
    if settings.model_backend == "cuda-online-baseline":
        return CudaOnlineBaselinePumpModel(settings)
    raise ValueError(f"unsupported model backend: {settings.model_backend}")
