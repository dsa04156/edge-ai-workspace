from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceDemoStatus = Literal[
    "starting",
    "warming_up",
    "normal",
    "anomaly",
    "degraded",
]


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class UpstreamModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class UpstreamAxisValues(UpstreamModel):
    x: int | float
    y: int | float
    z: int | float


class UpstreamSource(UpstreamModel):
    physical_source: str
    device_service: str
    devices: list[str]


class UpstreamComponentScores(UpstreamModel):
    vibration: float = Field(ge=0)
    temperature: float = Field(ge=0)


class UpstreamScoreWeights(UpstreamModel):
    vibration: float = Field(ge=0)
    temperature: float = Field(ge=0)


class UpstreamVibrationFeatures(UpstreamModel):
    rms: float
    peak: float
    kurtosis: float
    sample_count: int = Field(ge=1)


class UpstreamTemperatureFeatures(UpstreamModel):
    origin: int = Field(gt=0)
    raw: int | float
    mean: float
    stddev: float = Field(ge=0)
    delta: float
    sample_count: int = Field(ge=1)
    alignment_lag_ms: float = Field(ge=0)


class UpstreamLatest(UpstreamModel):
    origin: int = Field(gt=0)
    observed_at: datetime
    values: UpstreamAxisValues
    magnitude: float
    score: float = Field(ge=0)
    anomaly: bool
    model_version: str = "baseline-1.0.0"
    input_contract: str = "okdong.pump-motor.telemetry/v1"
    component_scores: UpstreamComponentScores | None = None
    weights: UpstreamScoreWeights | None = None
    vibration_features: UpstreamVibrationFeatures | None = None
    temperature_features: UpstreamTemperatureFeatures | None = None


class UpstreamFeatureModel(UpstreamModel):
    algorithm: str = Field(min_length=1)
    sample_count: int = Field(ge=0)
    warmup_samples: int = Field(ge=1)
    threshold: float = Field(gt=0)
    feature_means: dict[str, float] = Field(default_factory=dict)
    feature_stddevs: dict[str, float] = Field(default_factory=dict)
    stddev_floors: dict[str, float] = Field(default_factory=dict)


class UpstreamDetectorModel(UpstreamModel):
    algorithm: str = Field(min_length=1)
    version: str = "baseline-1.0.0"
    sample_count: int = Field(ge=0)
    warmup_samples: int = Field(ge=1)
    threshold: float = Field(gt=0)
    baseline_mean: float
    baseline_stddev: float = Field(ge=0)
    stddev_floor: float = Field(gt=0)
    components: dict[str, UpstreamFeatureModel] = Field(default_factory=dict)
    weights: UpstreamScoreWeights | None = None


class UpstreamCounters(UpstreamModel):
    frames_processed: int = Field(ge=0)
    duplicates_ignored: int = Field(ge=0)
    incomplete_frames_dropped: int = Field(ge=0)
    input_errors: int = Field(ge=0)
    context_samples_processed: int = Field(default=0, ge=0)
    unaligned_frames_dropped: int = Field(default=0, ge=0)


class UpstreamServiceStatus(UpstreamModel):
    api_version: Literal["v1"]
    service: Literal["sensor-anomaly-demo"]
    mode: Literal["live"]
    status: ServiceDemoStatus
    input_state: Literal["waiting", "fresh", "stale", "error"]
    model_state: Literal["warming_up", "ready"]
    source: UpstreamSource
    latest: UpstreamLatest | None = None
    model: UpstreamDetectorModel
    counters: UpstreamCounters
    last_error: str | None = None


class UpstreamResultEnvelope(UpstreamModel):
    api_version: Literal["v1"]
    count: int = Field(ge=0)
    results: list[UpstreamLatest]


class UpstreamAlertTransition(UpstreamModel):
    alert_id: str
    transition: Literal["opened", "cleared"]
    status: Literal["open", "closed"]
    origin: int = Field(gt=0)
    observed_at: datetime
    asset_id: str
    score: float = Field(ge=0)
    model_version: str
    message: str


class UpstreamAlertEnvelope(UpstreamModel):
    api_version: Literal["v1"]
    count: int = Field(ge=0)
    alerts: list[UpstreamAlertTransition]


class ServiceDemoBinding(BaseModel):
    physical_source: str = "arduino-001"
    device_service: str = "device-serial-jetson"
    devices: list[str] = Field(default_factory=list)
    consumer: str = "sensor-anomaly-demo"
    node: str = "etri-dev0001-jetorn"


class ServiceDemoAxisValues(BaseModel):
    x: int | float
    y: int | float
    z: int | float


class ServiceDemoLatest(BaseModel):
    origin: int
    observed_at: datetime
    values: ServiceDemoAxisValues
    magnitude: float
    score: float
    anomaly: bool
    model_version: str = "baseline-1.0.0"
    input_contract: str = "okdong.pump-motor.telemetry/v1"
    component_scores: ServiceDemoComponentScores | None = None
    weights: ServiceDemoScoreWeights | None = None
    vibration_features: ServiceDemoVibrationFeatures | None = None
    temperature_features: ServiceDemoTemperatureFeatures | None = None


class ServiceDemoComponentScores(BaseModel):
    vibration: float
    temperature: float


class ServiceDemoScoreWeights(BaseModel):
    vibration: float
    temperature: float


class ServiceDemoVibrationFeatures(BaseModel):
    rms: float
    peak: float
    kurtosis: float
    sample_count: int


class ServiceDemoTemperatureFeatures(BaseModel):
    origin: int
    raw: int | float
    mean: float
    stddev: float
    delta: float
    sample_count: int
    alignment_lag_ms: float


class ServiceDemoFeatureModel(BaseModel):
    algorithm: str
    sample_count: int
    warmup_samples: int
    threshold: float
    feature_means: dict[str, float] = Field(default_factory=dict)
    feature_stddevs: dict[str, float] = Field(default_factory=dict)
    stddev_floors: dict[str, float] = Field(default_factory=dict)


class ServiceDemoModel(BaseModel):
    algorithm: str
    version: str = "baseline-1.0.0"
    sample_count: int
    warmup_samples: int
    threshold: float
    baseline_mean: float
    baseline_stddev: float
    stddev_floor: float
    components: dict[str, ServiceDemoFeatureModel] = Field(default_factory=dict)
    weights: ServiceDemoScoreWeights | None = None


class ServiceDemoCounters(BaseModel):
    frames_processed: int = 0
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0
    input_errors: int = 0
    context_samples_processed: int = 0
    unaligned_frames_dropped: int = 0


class ServiceDemoState(BaseModel):
    generated_at: datetime
    mode: Literal["live", "unavailable"]
    status: ServiceDemoStatus
    input_state: str
    model_state: str
    binding: ServiceDemoBinding
    latest: ServiceDemoLatest | None = None
    model: ServiceDemoModel | None = None
    counters: ServiceDemoCounters = Field(default_factory=ServiceDemoCounters)
    last_error: str | None = None
    observation_error: str | None = None


class ServiceDemoResultState(BaseModel):
    generated_at: datetime
    mode: Literal["live", "unavailable"]
    count: int = Field(ge=0)
    results: list[ServiceDemoLatest] = Field(default_factory=list)
    observation_error: str | None = None


class ServiceDemoAlertTransition(BaseModel):
    alert_id: str
    transition: Literal["opened", "cleared"]
    status: Literal["open", "closed"]
    origin: int
    observed_at: datetime
    asset_id: str
    score: float
    model_version: str
    message: str


class ServiceDemoAlertState(BaseModel):
    generated_at: datetime
    mode: Literal["live", "unavailable"]
    count: int = Field(ge=0)
    alerts: list[ServiceDemoAlertTransition] = Field(default_factory=list)
    observation_error: str | None = None


class DeployedServiceItem(BaseModel):
    service_id: str
    display_name: str
    description: str
    category: Literal["ai_inference"] = "ai_inference"
    lifecycle: Literal["deployed"] = "deployed"
    execution_mode: Literal["fixed"] = "fixed"
    mode: Literal["live", "unavailable"]
    status: ServiceDemoStatus
    input_state: str
    model_state: str
    node: str
    physical_source: str
    device_service: str
    input_devices: list[str] = Field(default_factory=list)
    model_version: str | None = None
    latest_observed_at: datetime | None = None
    observation_error: str | None = None


class DeployedServiceState(BaseModel):
    generated_at: datetime
    services: list[DeployedServiceItem] = Field(default_factory=list)
