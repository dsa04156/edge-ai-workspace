from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
    inference_target: Literal["edge-local", "server1"] = "edge-local"
    augmentation_approval_id: str | None = None
    request_id: str | None = None
    execution_mode: Literal["local", "remote", "fallback"] = "local"
    source_node: str | None = None
    remote_node: str | None = None
    local_latency_ms: float | None = Field(default=None, ge=0)
    network_latency_ms: float | None = Field(default=None, ge=0)
    remote_processing_ms: float | None = Field(default=None, ge=0)
    total_latency_ms: float | None = Field(default=None, ge=0)
    fallback: bool = False
    reason_code: str | None = None


class UpstreamInferenceRouting(UpstreamModel):
    configured_mode: Literal["disabled", "approved"] = "disabled"
    state: Literal["disabled", "remote", "rolled-back"] = "disabled"
    effective_target: Literal["edge-local", "server1"] = "edge-local"
    approval_id: str | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    rollback_remaining_seconds: int = Field(default=0, ge=0)
    last_error: str | None = None
    inference_mode: Literal["LOCAL", "REMOTE", "LOCAL_FALLBACK"] = "LOCAL"
    source_node: str | None = None
    remote_node: str | None = None
    remote_ready: bool | None = None
    target_model_version: str | None = None
    local_latency_ms: float | None = Field(default=None, ge=0)
    network_latency_ms: float | None = Field(default=None, ge=0)
    remote_processing_ms: float | None = Field(default=None, ge=0)
    total_latency_ms: float | None = Field(default=None, ge=0)
    remote_attempts: int = Field(default=0, ge=0)
    remote_successes: int = Field(default=0, ge=0)
    offload_success_rate: float | None = Field(default=None, ge=0, le=1)
    fallback_count: int = Field(default=0, ge=0)
    last_reason_code: str | None = None
    observed_at: datetime | None = None


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
    shadow_frames_processed: int = Field(default=0, ge=0)
    duplicates_ignored: int = Field(ge=0)
    incomplete_frames_dropped: int = Field(ge=0)
    input_errors: int = Field(ge=0)
    context_samples_processed: int = Field(default=0, ge=0)
    unaligned_frames_dropped: int = Field(default=0, ge=0)


class UpstreamServicePerformance(UpstreamModel):
    observed_at: datetime
    window_seconds: float = Field(gt=0)
    processing_latency_p95_ms: float = Field(ge=0)
    backlog: int = Field(ge=0)
    throughput_per_second: float = Field(ge=0)
    sample_count: int = Field(ge=0)
    metrics_valid: bool


class UpstreamProcessResources(UpstreamModel):
    observed_at: datetime
    source: Literal["process-self"]
    scope: Literal["main-process"]
    cpu_cores: float | None = Field(default=None, ge=0)
    memory_rss_mib: float | None = Field(default=None, ge=0)
    sample_interval_seconds: float | None = Field(default=None, gt=0)
    metrics_valid: bool


class UpstreamExecutionOwnership(UpstreamModel):
    configured_mode: Literal["ACTIVE", "STANDBY", "SHADOW"]
    effective_mode: Literal["ACTIVE", "STANDBY", "SHADOW"]
    enabled: bool
    lease_namespace: str | None = None
    lease_name: str | None = None
    holder_identity: str | None = None
    owner_identity: str | None = None
    lease_valid: bool
    renew_time: datetime | None = None
    lease_duration_seconds: int | None = Field(default=None, ge=1)
    resource_version: str | None = None
    reason_code: str | None = None
    observed_at: datetime


class UpstreamStorageStatus(UpstreamModel):
    api_version: Literal["v1"]
    backend: Literal["sqlite"] = "sqlite"
    durable: bool
    result_count: int = Field(ge=0)
    alert_event_count: int = Field(ge=0)
    open_alert_count: int = Field(ge=0)
    retention_rows: int = Field(ge=1)


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
    performance: UpstreamServicePerformance | None = None
    process_resources: UpstreamProcessResources | None = None
    execution_ownership: UpstreamExecutionOwnership | None = None
    storage: UpstreamStorageStatus | None = None
    inference_routing: UpstreamInferenceRouting = Field(
        default_factory=UpstreamInferenceRouting
    )
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
    inference_target: Literal["edge-local", "server1"] = "edge-local"
    augmentation_approval_id: str | None = None
    request_id: str | None = None
    execution_mode: Literal["local", "remote", "fallback"] = "local"
    source_node: str | None = None
    remote_node: str | None = None
    local_latency_ms: float | None = None
    network_latency_ms: float | None = None
    remote_processing_ms: float | None = None
    total_latency_ms: float | None = None
    fallback: bool = False
    reason_code: str | None = None


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
    shadow_frames_processed: int = 0
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0
    input_errors: int = 0
    context_samples_processed: int = 0
    unaligned_frames_dropped: int = 0


class ServiceDemoPerformance(BaseModel):
    observed_at: datetime
    window_seconds: float
    processing_latency_p95_ms: float
    backlog: int
    throughput_per_second: float
    sample_count: int
    metrics_valid: bool


class ServiceDemoProcessResources(BaseModel):
    observed_at: datetime
    source: Literal["process-self"] = "process-self"
    scope: Literal["main-process"] = "main-process"
    cpu_cores: float | None = None
    memory_rss_mib: float | None = None
    sample_interval_seconds: float | None = None
    metrics_valid: bool


class ServiceDemoExecutionOwnership(BaseModel):
    configured_mode: Literal["ACTIVE", "STANDBY", "SHADOW"]
    effective_mode: Literal["ACTIVE", "STANDBY", "SHADOW"]
    enabled: bool
    lease_namespace: str | None = None
    lease_name: str | None = None
    holder_identity: str | None = None
    owner_identity: str | None = None
    lease_valid: bool
    renew_time: datetime | None = None
    lease_duration_seconds: int | None = None
    resource_version: str | None = None
    reason_code: str | None = None
    observed_at: datetime


class ServiceDemoStorageStatus(BaseModel):
    backend: Literal["sqlite"] = "sqlite"
    durable: bool
    result_count: int = Field(ge=0)
    alert_event_count: int = Field(ge=0)
    open_alert_count: int = Field(ge=0)
    retention_rows: int = Field(ge=1)


class ServiceAugmentationGate(BaseModel):
    id: str
    label: str
    passed: bool
    reason: str


class ServiceAugmentationMetrics(BaseModel):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    processing_latency_p95_ms: float | None = None
    backlog: int | None = None
    throughput_per_second: float | None = None


class ServiceAugmentationDwell(BaseModel):
    resource_pressure_seconds: int = 0
    resource_pressure_required_seconds: int = 300
    service_pressure_seconds: int = 0
    service_pressure_required_seconds: int = 180


class ServiceAugmentationObservation(BaseModel):
    source: Literal["container-cadvisor", "process-self", "unavailable"]
    scope: Literal["container", "main-process", "unknown"]


class ServiceAugmentationCandidate(BaseModel):
    target: str = "server1 GPU"
    ready: bool = False
    qualified: bool = False
    qualification_reason: str = "not_evaluated"


class ServiceAugmentationState(BaseModel):
    generated_at: datetime
    service: Literal["sensor-anomaly-demo"] = "sensor-anomaly-demo"
    state: Literal["NORMAL", "OBSERVING", "RECOMMENDED", "BLOCKED"]
    recommendation: Literal["none", "scale-up"] = "none"
    apply_state: Literal["observed-only", "blocked"] = "observed-only"
    reason_codes: list[str] = Field(default_factory=list)
    gates: list[ServiceAugmentationGate] = Field(default_factory=list)
    metrics: ServiceAugmentationMetrics
    dwell: ServiceAugmentationDwell = Field(default_factory=ServiceAugmentationDwell)
    observation: ServiceAugmentationObservation
    candidate: ServiceAugmentationCandidate
    anomaly_signal_used: Literal[False] = False


class ServiceDemoInferenceRouting(BaseModel):
    configured_mode: Literal["disabled", "approved"] = "disabled"
    state: Literal["disabled", "remote", "rolled-back"] = "disabled"
    effective_target: Literal["edge-local", "server1"] = "edge-local"
    approval_id: str | None = None
    consecutive_failures: int = 0
    rollback_remaining_seconds: int = 0
    last_error: str | None = None
    inference_mode: Literal["LOCAL", "REMOTE", "LOCAL_FALLBACK"] = "LOCAL"
    source_node: str | None = None
    remote_node: str | None = None
    remote_ready: bool | None = None
    target_model_version: str | None = None
    local_latency_ms: float | None = None
    network_latency_ms: float | None = None
    remote_processing_ms: float | None = None
    total_latency_ms: float | None = None
    remote_attempts: int = 0
    remote_successes: int = 0
    offload_success_rate: float | None = None
    fallback_count: int = 0
    last_reason_code: str | None = None
    observed_at: datetime | None = None


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
    performance: ServiceDemoPerformance | None = None
    process_resources: ServiceDemoProcessResources | None = None
    execution_ownership: ServiceDemoExecutionOwnership | None = None
    storage: ServiceDemoStorageStatus | None = None
    augmentation: ServiceAugmentationState | None = None
    inference_routing: ServiceDemoInferenceRouting = Field(
        default_factory=ServiceDemoInferenceRouting
    )
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


class DeployedServiceInputBinding(BaseModel):
    stage_id: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    resource_name: str = Field(min_length=1)


class DeployedServiceDesignContract(BaseModel):
    contract_id: Literal["sensor-anomaly-demo-v1"]
    source_mode: Literal["local_recent"] = "local_recent"
    pipeline_algorithm: str = Field(min_length=1)
    vibration_algorithm: str = Field(min_length=1)
    temperature_algorithm: str = Field(min_length=1)
    vibration_window_samples: int = Field(ge=2)
    temperature_window_samples: int = Field(ge=2)
    warmup_samples: int = Field(ge=1)
    threshold: float = Field(gt=0)
    vibration_weight: float = Field(ge=0)
    temperature_weight: float = Field(ge=0)
    inputs: list[DeployedServiceInputBinding] = Field(default_factory=list)


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
    inference_target: Literal["edge-local", "server1"] = "edge-local"
    observation_error: str | None = None
    design_contract: DeployedServiceDesignContract | None = None
    catalog_version: str | None = None
    definition_source: str | None = None
    descriptor: dict[str, Any] | None = None


class DeployedServiceState(BaseModel):
    generated_at: datetime
    services: list[DeployedServiceItem] = Field(default_factory=list)
