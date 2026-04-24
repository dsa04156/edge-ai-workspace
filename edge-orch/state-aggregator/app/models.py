from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PressureLevel = Literal["low", "medium", "high"]
HealthLevel = Literal["healthy", "degraded", "unavailable"]
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


class CostModelState(BaseModel):
    node_states: list[NodeState]
    stage_cost_stats: list[StageCostStats] = Field(default_factory=list)
    migration_cost_stats: list[MigrationCostStats] = Field(default_factory=list)
