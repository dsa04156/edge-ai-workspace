from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PressureLevel = Literal["low", "medium", "high"]
HealthLevel = Literal["available", "healthy", "degraded", "unavailable"]
UrgencyLevel = Literal["low", "medium", "high"]
RiskLevel = Literal["low", "medium", "high"]
PlacementStability = Literal["stable", "moving", "unstable"]
ActionType = Literal["keep", "migrate", "offload_to_cloud", "reject"]


class WorkflowEvent(BaseModel):
    event_type: str
    timestamp: datetime
    workflow_id: str
    workflow_type: str | None = None
    stage_id: str
    stage_type: str | None = None
    assigned_node: str | None = None
    status: str | None = None
    exec_time_ms: int | None = None
    queue_wait_ms: int | None = None
    transfer_time_ms: int | None = None
    from_node: str | None = None
    to_node: str | None = None
    reason: str | None = None
    action_type: ActionType | None = None
    score_breakdown: dict[str, float | int | bool | str | None] = Field(default_factory=dict)


class StageObservation(BaseModel):
    workflow_id: str
    stage_id: str
    stage_type: str | None = None
    assigned_node: str | None = None
    started_at: datetime
    completed_at: datetime
    observed_latency_ms: int
    queue_wait_ms: int | None = None
    transfer_time_ms: int | None = None
    warmup_ms: int | None = None
    action_type: ActionType | None = None
    from_node: str | None = None
    to_node: str | None = None


class MigrationObservation(BaseModel):
    workflow_id: str
    stage_id: str
    stage_type: str | None = None
    from_node: str
    to_node: str
    decided_at: datetime
    started_at: datetime
    migration_time_ms: int


class StageCostStats(BaseModel):
    stage_type: str
    node: str
    sample_count: int = 0
    exec_median_ms: float = 0.0
    exec_ema_ms: float = 0.0
    queue_median_ms: float = 0.0
    warmup_median_ms: float = 0.0
    recent_migration_count_last_hour: int = 0
    placement_stability: PlacementStability = "stable"


class MigrationCostStats(BaseModel):
    stage_type: str
    from_node: str
    to_node: str
    sample_count: int = 0
    migration_median_ms: float = 0.0
    migration_ema_ms: float = 0.0


class NodeRawMetrics(BaseModel):
    instance: str
    hostname: str
    node_type: str | None = None
    up: float = 0.0
    cpu_utilization: float = 0.0
    cpu_logical_cores: float | None = None
    memory_usage_ratio: float = 0.0
    load_average: float = 0.0
    network_rx_rate: float = 0.0
    network_tx_rate: float = 0.0
    gpu_utilization: float | None = None
    gpu_memory_used_mib: float | None = None
    gpu_memory_total_mib: float | None = None
    gpu_memory_usage_ratio: float | None = None
    gpu_temperature_celsius: float | None = None
    gpu_power_watts: float | None = None
    collected_at: datetime


class NodeState(BaseModel):
    hostname: str
    instance: str
    node_type: str | None = None
    collected_at: datetime
    raw_metrics: dict[str, float]
    compute_pressure: PressureLevel
    memory_pressure: PressureLevel
    network_pressure: PressureLevel
    node_health: HealthLevel


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class SchedulingModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class SchedulingResourceAmounts(SchedulingModel):
    cpu_cores: float = Field(ge=0)
    memory_bytes: int = Field(ge=0)
    accelerator_units: dict[str, float] = Field(default_factory=dict)


class NodeResourceUtilization(SchedulingModel):
    cpu_ratio: float | None = Field(default=None, ge=0)
    memory_ratio: float | None = Field(default=None, ge=0)
    gpu_ratio: float | None = Field(default=None, ge=0)
    gpu_memory_ratio: float | None = Field(default=None, ge=0)
    load_average: float | None = Field(default=None, ge=0)
    network_rx_bytes_per_second: float | None = Field(default=None, ge=0)
    network_tx_bytes_per_second: float | None = Field(default=None, ge=0)
    observed_at: datetime | None = None


class NodeSchedulingResource(SchedulingModel):
    node: str
    cpu_available: float = Field(ge=0)
    memory_available_gb: float = Field(
        ge=0,
        serialization_alias="memoryAvailableGB",
        validation_alias="memoryAvailableGB",
    )
    accelerator: str | None = None
    health: HealthLevel
    schedulable: bool
    reason_codes: list[str] = Field(default_factory=list)
    architecture: str | None = None
    node_type: str | None = None
    allocatable: SchedulingResourceAmounts
    requested: SchedulingResourceAmounts
    available: SchedulingResourceAmounts
    utilization: NodeResourceUtilization | None = None
    capacity_source: str = "kubernetes-allocatable"
    reservation_source: str = "kubernetes-pod-requests"
    utilization_source: str = "prometheus"


class PlacementSelectionRequest(SchedulingModel):
    namespace: str = Field(min_length=1, max_length=253)
    service: str = Field(min_length=1, max_length=253)
    architecture: str = Field(min_length=1, max_length=64)
    accelerator: str | None = Field(default=None, min_length=1, max_length=128)
    accelerator_units: dict[str, float] = Field(default_factory=dict)
    refresh_profile: bool = False

    @field_validator("accelerator_units")
    @classmethod
    def validate_accelerator_units(
        cls, values: dict[str, float]
    ) -> dict[str, float]:
        if any(not name or amount < 0 for name, amount in values.items()):
            raise ValueError("acceleratorUnits must use non-empty names and non-negative values")
        return values


class PlacementRequirements(SchedulingModel):
    cpu_cores: float = Field(ge=0)
    memory_bytes: int = Field(ge=0)
    memory_gb: float = Field(ge=0)
    architecture: str
    accelerator: str | None = None
    accelerator_units: dict[str, float] = Field(default_factory=dict)
    source: str = "service-resource-profile"


class PlacementServiceProfileRef(SchedulingModel):
    namespace: str
    service: str
    generated_at: datetime | None = None
    pod_count: int = Field(ge=0)
    request_coverage_ratio: float = Field(ge=0, le=1)


class PlacementScoreBreakdown(SchedulingModel):
    cpu_headroom_ratio: float = Field(ge=0, le=1)
    memory_headroom_ratio: float = Field(ge=0, le=1)
    cpu_idle_ratio: float = Field(ge=0, le=1)
    memory_idle_ratio: float = Field(ge=0, le=1)
    cpu_headroom_points: float = Field(ge=0)
    memory_headroom_points: float = Field(ge=0)
    cpu_idle_points: float = Field(ge=0)
    memory_idle_points: float = Field(ge=0)
    total: float = Field(ge=0, le=100)


class PlacementCandidate(SchedulingModel):
    node: str
    eligible: bool
    score: float | None = Field(default=None, ge=0, le=100)
    reason_codes: list[str] = Field(default_factory=list)
    health: HealthLevel
    architecture: str | None = None
    accelerator: str | None = None
    available_before: SchedulingResourceAmounts
    available_after: SchedulingResourceAmounts | None = None
    utilization: NodeResourceUtilization | None = None
    score_breakdown: PlacementScoreBreakdown | None = None


class PlacementSelectionResult(SchedulingModel):
    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    status: Literal["selected", "no_fit", "blocked"]
    service_profile: PlacementServiceProfileRef
    requirements: PlacementRequirements | None = None
    selected_node: str | None = None
    selected_score: float | None = Field(default=None, ge=0, le=100)
    reason_codes: list[str] = Field(default_factory=list)
    candidates: list[PlacementCandidate] = Field(default_factory=list)


DeploymentExecutionStatus = Literal["ready", "failed", "rejected"]


class DeploymentCreateRequest(SchedulingModel):
    deployment_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    image: str = Field(min_length=1, max_length=512)
    placement: PlacementSelectionRequest
    container_port: int | None = Field(default=None, ge=1, le=65535)
    readiness_path: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("image")
    @classmethod
    def validate_immutable_image(cls, value: str) -> str:
        if re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", value) is None:
            raise ValueError("image must use an immutable sha256 digest")
        return value

    @field_validator("readiness_path")
    @classmethod
    def validate_readiness_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("readiness_path must start with '/'")
        return value

    @model_validator(mode="after")
    def validate_probe_contract(self) -> "DeploymentCreateRequest":
        if self.readiness_path is not None and self.container_port is None:
            raise ValueError("container_port is required with readiness_path")
        return self


class DeploymentPodObservation(SchedulingModel):
    name: str
    phase: str | None = None
    node: str | None = None
    ready: bool = False
    reason_code: str | None = None
    reason: str | None = None
    message: str | None = None


class DeploymentCreateResult(SchedulingModel):
    operation_id: str
    namespace: str
    deployment_name: str
    image: str
    status: DeploymentExecutionStatus
    created: bool = False
    selected_node: str | None = None
    pod_ready: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    message: str
    placement: PlacementSelectionResult
    pods: list[DeploymentPodObservation] = Field(default_factory=list)
    observed_at: datetime


class EdgeXDevice(BaseModel):
    name: str
    description: str | None = None
    profile_name: str
    device_service_name: str
    protocol_names: list[str] = Field(default_factory=list)
    admin_state: str
    operating_state: str
    tags: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    node_name: str | None = None


class DeviceResourceContract(BaseModel):
    name: str
    description: str | None = None
    value_type: str
    read_write: str = "R"
    units: str | None = None


class DeviceProfileContract(BaseModel):
    name: str
    description: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    labels: list[str] = Field(default_factory=list)
    resources: list[DeviceResourceContract] = Field(default_factory=list)


class TelemetryPoint(BaseModel):
    device_name: str
    source_name: str
    resource_name: str
    value_type: str
    value: str | float | int | bool | dict[str, Any] | list[Any] | None
    timestamp: datetime
    origin: int
    event_id: str | None = None
    units: str | None = None


class DeviceState(BaseModel):
    name: str
    source: Literal["edgex"] = "edgex"
    profile_name: str
    device_service_name: str
    protocol_names: list[str] = Field(default_factory=list)
    admin_state: str
    operating_state: str
    connection_state: Literal["connected", "disconnected", "unknown"] = "unknown"
    device_service_available: bool = False
    latest_event_timestamp: datetime | None = None
    latest_readings: list[TelemetryPoint] = Field(default_factory=list)
    telemetry_freshness: Literal["fresh", "stale", "no_events"] = "no_events"
    overall_status: HealthLevel = "degraded"
    reason: str = ""
    node_name: str | None = None
    physical_device_id: str | None = None
    hardware_binding_id: str | None = None
    controller_candidate_id: str | None = None


class WorkflowState(BaseModel):
    workflow_id: str
    workflow_type: str | None = None
    last_event_type: str
    last_stage_id: str
    last_stage_type: str | None = None
    assigned_node: str | None = None
    last_status: str | None = None
    latest_timestamp: datetime
    event_count: int = 0
    migration_count_last_hour: int = 0
    workflow_urgency: UrgencyLevel
    sla_risk: RiskLevel
    placement_stability: PlacementStability
    recent_event: dict[str, Any] = Field(default_factory=dict)


class SummaryState(BaseModel):
    generated_at: datetime
    hotspot_nodes: list[dict[str, Any]]
    sla_risk_workflows: list[dict[str, Any]]
    recent_migration_count: int
    unstable_workflows: list[dict[str, Any]]


class OperatorAssistantState(BaseModel):
    generated_at: datetime
    assistant_name: str = "kagenti-operator-assistant-poc"
    mode: Literal["read_only"] = "read_only"
    summary_ko: str
    focus_devices: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    source_endpoints: list[str] = Field(default_factory=list)


class OperatorChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)


class OperatorChatResponse(BaseModel):
    assistant_name: str = "kagenti-qwen-operator-chat"
    mode: Literal["read_only"] = "read_only"
    model: str
    answer: str
    source_endpoints: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    upstream_status: str = "ok"


class CostModelState(BaseModel):
    node_states: list[NodeState]
    stage_cost_stats: list[StageCostStats] = Field(default_factory=list)
    migration_cost_stats: list[MigrationCostStats] = Field(default_factory=list)


class DashboardState(BaseModel):
    generated_at: datetime
    nodes: list[NodeState]
    devices: list[DeviceState]
    workflows: list[WorkflowState]
    summary: SummaryState
    kpis: dict[str, Any]
    resource_profiles: dict[str, Any] = Field(default_factory=dict)
    device_observation_error: str | None = None
