from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal["keep", "migrate", "offload_to_cloud", "reject"]
PressureLevel = Literal["low", "medium", "high"]
HealthLevel = Literal["healthy", "degraded", "unavailable"]
PlacementStability = Literal["stable", "moving", "unstable"]


class NodeProfile(BaseModel):
    hostname: str
    node_type: str
    arch: str
    compute_class: str
    memory_class: str
    accelerator_type: str | None = None
    preferred_workload: list[str] = Field(default_factory=list)
    risky_workload: list[str] = Field(default_factory=list)


class NodeState(BaseModel):
    hostname: str
    compute_pressure: PressureLevel
    memory_pressure: PressureLevel
    network_pressure: PressureLevel
    node_health: HealthLevel


class StageMetadata(BaseModel):
    stage_type: str
    requires_accelerator: bool
    compute_intensity: str
    memory_intensity: str
    latency_sensitivity: str
    input_size_kb: int
    output_size_kb: int


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


class PlacementDecision(BaseModel):
    workflow_id: str
    stage_id: str
    target_node: str | None
    decision_reason: str
    action_type: ActionType
    score_breakdown: dict[str, float | int | bool | str | None] = Field(default_factory=dict)
