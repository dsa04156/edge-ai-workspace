from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
