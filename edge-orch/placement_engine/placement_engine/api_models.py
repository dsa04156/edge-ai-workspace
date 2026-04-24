from __future__ import annotations

from pydantic import BaseModel, Field

from .models import (
    MigrationCostStats,
    NodeProfile,
    NodeState,
    PlacementDecision,
    StageCostStats,
    StageMetadata,
)


class PlacementDecisionRequest(BaseModel):
    workflow_id: str
    stage_id: str
    stage_metadata: StageMetadata
    node_profiles: list[NodeProfile]
    node_states: list[NodeState] | None = None
    stage_cost_stats: list[StageCostStats] | None = None
    migration_cost_stats: list[MigrationCostStats] | None = None
    current_placement: str | None = None
    workflow_type: str | None = None


class ReplanWorkflowStage(BaseModel):
    stage_id: str
    stage_metadata: StageMetadata


class ReplanWorkflowRequest(BaseModel):
    workflow_id: str
    stages: list[ReplanWorkflowStage]
    node_profiles: list[NodeProfile]
    node_states: list[NodeState] | None = None
    stage_cost_stats: list[StageCostStats] | None = None
    migration_cost_stats: list[MigrationCostStats] | None = None
    current_placement: dict[str, str] = Field(default_factory=dict)
    workflow_type: str | None = None


class AggregatorSummary(BaseModel):
    node_states: list[NodeState]
    source: str


class CostModelSnapshot(BaseModel):
    node_states: list[NodeState]
    stage_cost_stats: list[StageCostStats] = Field(default_factory=list)
    migration_cost_stats: list[MigrationCostStats] = Field(default_factory=list)
    source: str


class PlacementDecisionResponse(BaseModel):
    decision: PlacementDecision


class ReplanWorkflowResponse(BaseModel):
    decisions: list[PlacementDecision]
