from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal["keep", "migrate", "offload_to_cloud", "reject"]


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
    compute_pressure: str
    memory_pressure: str
    network_pressure: str
    node_health: str


class StageMetadata(BaseModel):
    stage_type: str
    requires_accelerator: bool
    compute_intensity: str
    memory_intensity: str
    latency_sensitivity: str
    input_size_kb: int
    output_size_kb: int


class PlacementDecision(BaseModel):
    workflow_id: str
    stage_id: str
    target_node: str | None
    decision_reason: str
    action_type: ActionType
    score_breakdown: dict[str, float] = Field(default_factory=dict)
