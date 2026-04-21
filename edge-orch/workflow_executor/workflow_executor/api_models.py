from __future__ import annotations

from pydantic import BaseModel

from .models import (
    ExecuteStageRequest,
    ExecuteWorkflowRequest,
    StageExecutionResult,
    WorkflowRunState,
    WorkflowExecutionResult,
)


class ExecuteStageResponse(BaseModel):
    result: StageExecutionResult


class ExecuteWorkflowResponse(BaseModel):
    result: WorkflowExecutionResult


class WorkflowStateResponse(BaseModel):
    workflow: WorkflowRunState


class WorkflowStateListResponse(BaseModel):
    workflows: list[WorkflowRunState]


__all__ = [
    "ExecuteStageRequest",
    "ExecuteStageResponse",
    "ExecuteWorkflowRequest",
    "ExecuteWorkflowResponse",
    "WorkflowStateListResponse",
    "WorkflowStateResponse",
]
