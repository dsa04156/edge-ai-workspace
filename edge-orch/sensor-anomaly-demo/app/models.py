from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AxisName = Literal["x", "y", "z"]
NumericValue = int | float
DetectionStatus = Literal["warming_up", "normal", "anomaly"]
RuntimeStatus = Literal["starting", "warming_up", "normal", "anomaly", "degraded"]
InputState = Literal["waiting", "fresh", "stale", "error"]
RuntimeModelState = Literal["warming_up", "ready"]
InputContractName = Literal["okdong.pump-motor.telemetry/v1"]


@dataclass(frozen=True)
class AxisSample:
    origin: int
    value_type: str
    value: NumericValue


@dataclass(frozen=True)
class AccelerationFrame:
    origin: int
    x: NumericValue
    y: NumericValue
    z: NumericValue


@dataclass
class JoinCounters:
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0


@dataclass(frozen=True)
class InferenceResult:
    origin: int
    x: int
    y: int
    z: int
    magnitude: float
    score: float
    anomaly: bool
    status: DetectionStatus


@dataclass(frozen=True)
class VibrationFeatures:
    origin: int
    rms: float
    peak: float
    kurtosis: float
    sample_count: int

    def values(self) -> dict[str, float]:
        return {
            "rms": self.rms,
            "peak": self.peak,
            "kurtosis": self.kurtosis,
        }


@dataclass(frozen=True)
class TemperatureFeatures:
    origin: int
    raw: NumericValue
    mean: float
    stddev: float
    delta: float
    sample_count: int

    def values(self) -> dict[str, float]:
        return {
            "mean": self.mean,
            "stddev": self.stddev,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class FeatureInferenceResult:
    origin: int
    score: float
    anomaly: bool
    status: DetectionStatus


@dataclass(frozen=True)
class FeatureModelSnapshot:
    algorithm: str
    sample_count: int
    warmup_samples: int
    threshold: float
    feature_means: dict[str, float]
    feature_stddevs: dict[str, float]
    stddev_floors: dict[str, float]


@dataclass(frozen=True)
class ModelSnapshot:
    algorithm: str
    sample_count: int
    warmup_samples: int
    threshold: float
    baseline_mean: float
    baseline_stddev: float
    stddev_floor: float


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class AxisValues(ApiModel):
    x: NumericValue
    y: NumericValue
    z: NumericValue


class SourceIdentity(ApiModel):
    physical_source: str = "arduino-001"
    device_service: str = "device-serial-jetson"
    devices: list[str] = Field(default_factory=list)


class LatestObservation(ApiModel):
    origin: int
    observed_at: datetime
    values: AxisValues
    magnitude: float
    score: float
    anomaly: bool
    model_version: str = "baseline-1.0.0"
    input_contract: str = "okdong.pump-motor.telemetry/v1"
    component_scores: ComponentScores | None = None
    weights: ScoreWeights | None = None
    vibration_features: VibrationFeatureObservation | None = None
    temperature_features: TemperatureFeatureObservation | None = None
    inference_target: Literal["edge-local", "server1"] = "edge-local"
    augmentation_approval_id: str | None = None


class ComponentScores(ApiModel):
    vibration: float = Field(ge=0)
    temperature: float = Field(ge=0)


class ScoreWeights(ApiModel):
    vibration: float = Field(ge=0)
    temperature: float = Field(ge=0)


class VibrationFeatureObservation(ApiModel):
    rms: float
    peak: float
    kurtosis: float
    sample_count: int = Field(ge=1)


class TemperatureFeatureObservation(ApiModel):
    origin: int = Field(gt=0)
    raw: NumericValue
    mean: float
    stddev: float = Field(ge=0)
    delta: float
    sample_count: int = Field(ge=1)
    alignment_lag_ms: float = Field(ge=0)


class FeatureModelObservation(ApiModel):
    algorithm: str
    sample_count: int = Field(ge=0)
    warmup_samples: int = Field(ge=1)
    threshold: float = Field(gt=0)
    feature_means: dict[str, float] = Field(default_factory=dict)
    feature_stddevs: dict[str, float] = Field(default_factory=dict)
    stddev_floors: dict[str, float] = Field(default_factory=dict)


class ModelObservation(ApiModel):
    algorithm: str
    version: str = "baseline-1.0.0"
    sample_count: int
    warmup_samples: int
    threshold: float
    baseline_mean: float
    baseline_stddev: float
    stddev_floor: float
    components: dict[str, FeatureModelObservation] = Field(default_factory=dict)
    weights: ScoreWeights | None = None


class RuntimeCounters(ApiModel):
    frames_processed: int = 0
    shadow_frames_processed: int = 0
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0
    input_errors: int = 0
    context_samples_processed: int = 0
    unaligned_frames_dropped: int = 0


class ServicePerformance(ApiModel):
    observed_at: datetime
    window_seconds: float = Field(gt=0)
    processing_latency_p95_ms: float = Field(ge=0)
    backlog: int = Field(ge=0)
    throughput_per_second: float = Field(ge=0)
    sample_count: int = Field(ge=0)
    metrics_valid: bool


class ProcessResourceObservation(ApiModel):
    observed_at: datetime
    source: Literal["process-self"] = "process-self"
    scope: Literal["main-process"] = "main-process"
    cpu_cores: float | None = Field(default=None, ge=0)
    memory_rss_mib: float | None = Field(default=None, ge=0)
    sample_interval_seconds: float | None = Field(default=None, gt=0)
    metrics_valid: bool


class InferenceInputFrame(ApiModel):
    origin: int = Field(gt=0)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    z: float = Field(allow_inf_nan=False)


class InferenceTemperature(ApiModel):
    origin: int = Field(gt=0)
    value: float = Field(allow_inf_nan=False)


class InferenceRequest(ApiModel):
    api_version: Literal["v1"] = "v1"
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    input_contract: InputContractName
    frame: InferenceInputFrame
    temperature: InferenceTemperature


class InferenceResponse(ApiModel):
    api_version: Literal["v1"] = "v1"
    request_id: str
    input_contract: InputContractName
    origin: int = Field(gt=0)
    status: DetectionStatus
    anomaly: bool
    score: float = Field(ge=0, allow_inf_nan=False)
    component_scores: ComponentScores
    vibration_features: VibrationFeatureObservation
    temperature_features: TemperatureFeatureObservation
    model_state: RuntimeModelState
    model_version: str
    server_processing_ms: float | None = Field(default=None, ge=0)


class InferenceRoutingStatus(ApiModel):
    configured_mode: Literal["disabled", "approved"] = "disabled"
    state: Literal["disabled", "remote", "rolled-back"] = "disabled"
    effective_target: Literal["edge-local", "server1"] = "edge-local"
    approval_id: str | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    rollback_remaining_seconds: int = Field(default=0, ge=0)
    last_error: str | None = None


class ExecutionOwnershipObservation(ApiModel):
    configured_mode: Literal["ACTIVE", "STANDBY", "SHADOW"] = "ACTIVE"
    effective_mode: Literal["ACTIVE", "STANDBY", "SHADOW"] = "ACTIVE"
    enabled: bool = False
    lease_namespace: str | None = None
    lease_name: str | None = None
    holder_identity: str | None = None
    owner_identity: str | None = None
    lease_valid: bool = True
    renew_time: datetime | None = None
    lease_duration_seconds: int | None = Field(default=None, ge=1)
    resource_version: str | None = None
    reason_code: str | None = None
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ServiceStatus(ApiModel):
    api_version: Literal["v1"] = "v1"
    service: Literal["sensor-anomaly-demo"] = "sensor-anomaly-demo"
    mode: Literal["live"] = "live"
    status: RuntimeStatus
    input_state: InputState
    model_state: RuntimeModelState
    source: SourceIdentity
    latest: LatestObservation | None = None
    model: ModelObservation
    counters: RuntimeCounters
    performance: ServicePerformance
    process_resources: ProcessResourceObservation
    inference_routing: InferenceRoutingStatus = Field(
        default_factory=InferenceRoutingStatus
    )
    execution_ownership: ExecutionOwnershipObservation = Field(
        default_factory=ExecutionOwnershipObservation
    )
    last_error: str | None = None


class ResultEnvelope(ApiModel):
    api_version: Literal["v1"] = "v1"
    count: int
    results: list[LatestObservation]


class AlertTransition(ApiModel):
    alert_id: str
    transition: Literal["opened", "cleared"]
    status: Literal["open", "closed"]
    origin: int = Field(gt=0)
    observed_at: datetime
    asset_id: str
    score: float = Field(ge=0)
    model_version: str
    message: str


class AlertEnvelope(ApiModel):
    api_version: Literal["v1"] = "v1"
    count: int
    alerts: list[AlertTransition]


class StorageStatus(ApiModel):
    api_version: Literal["v1"] = "v1"
    backend: Literal["sqlite"] = "sqlite"
    durable: bool
    result_count: int = Field(ge=0)
    alert_event_count: int = Field(ge=0)
    open_alert_count: int = Field(ge=0)
    retention_rows: int = Field(ge=1)
