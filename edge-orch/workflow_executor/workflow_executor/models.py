from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal["keep", "migrate", "offload_to_cloud", "reject"]
ExecutionStatus = Literal["completed", "failed"]
StageRunStatus = Literal["pending", "placed", "running", "completed", "failed"]
WorkflowRunStatus = Literal["pending", "running", "completed", "failed"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NodeProfile(BaseModel):
    hostname: str
    node_type: str
    arch: str
    compute_class: str
    memory_class: str
    accelerator_type: str | None = None
    preferred_workload: list[str] = Field(default_factory=list)
    risky_workload: list[str] = Field(default_factory=list)


class StageMetadata(BaseModel):
    stage_type: str
    requires_accelerator: bool
    compute_intensity: str
    memory_intensity: str
    latency_sensitivity: str
    input_size_kb: int
    output_size_kb: int


class StageExecutionSpec(BaseModel):
    stage_id: str
    stage_metadata: StageMetadata
    image: str
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    queue_wait_ms: int | None = None
    exec_time_ms: int | None = None
    transfer_time_ms: int | None = None
    timeout_seconds: int | None = None


class PlacementDecision(BaseModel):
    workflow_id: str
    stage_id: str
    target_node: str | None
    decision_reason: str
    action_type: ActionType
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class WorkflowEvent(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    workflow_id: str
    workflow_type: str
    stage_id: str
    stage_type: str
    assigned_node: str
    exec_time_ms: int | None = None
    queue_wait_ms: int | None = None
    transfer_time_ms: int | None = None
    from_node: str | None = None
    to_node: str | None = None
    reason: str | None = None
    status: str | None = None


class ExecuteStageRequest(BaseModel):
    workflow_id: str
    workflow_type: str
    stage: StageExecutionSpec
    node_profiles: list[NodeProfile]
    current_placement: str | None = None


class ExecuteWorkflowRequest(BaseModel):
    workflow_id: str
    workflow_type: str
    stages: list[StageExecutionSpec]
    node_profiles: list[NodeProfile]
    current_placement: dict[str, str] = Field(default_factory=dict)


class StageExecutionResult(BaseModel):
    workflow_id: str
    workflow_type: str
    stage_id: str
    target_node: str
    action_type: ActionType
    decision_reason: str
    job_name: str
    status: ExecutionStatus


class WorkflowExecutionResult(BaseModel):
    workflow_id: str
    workflow_type: str
    stages: list[StageExecutionResult]


class StageRunState(BaseModel):
    workflow_id: str
    workflow_type: str
    stage_id: str
    stage_type: str
    status: StageRunStatus
    assigned_node: str | None = None
    job_name: str | None = None
    action_type: ActionType | None = None
    decision_reason: str | None = None
    queue_wait_ms: int | None = None
    exec_time_ms: int | None = None
    transfer_time_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class WorkflowTransition(BaseModel):
    workflow_id: str
    stage_id: str | None = None
    status: str
    details: dict[str, str | int | float | None] = Field(default_factory=dict)
    created_at: datetime


class WorkflowRunState(BaseModel):
    workflow_id: str
    workflow_type: str
    status: WorkflowRunStatus
    current_stage_id: str | None = None
    created_at: datetime
    updated_at: datetime
    stages: list[StageRunState] = Field(default_factory=list)
    transitions: list[WorkflowTransition] = Field(default_factory=list)
