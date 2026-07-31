from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
