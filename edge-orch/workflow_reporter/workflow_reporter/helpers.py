from __future__ import annotations

from .client import WorkflowReporter
from .models import WorkflowEvent


def _report(event: WorkflowEvent, reporter: WorkflowReporter | None = None) -> dict:
    active_reporter = reporter or WorkflowReporter()
    return active_reporter.send_event(event)


def report_stage_start(
    workflow_id: str,
    workflow_type: str,
    stage_id: str,
    stage_type: str,
    assigned_node: str,
    queue_wait_ms: int | None = None,
    reporter: WorkflowReporter | None = None,
) -> dict:
    return _report(
        WorkflowEvent(
            event_type="stage_start",
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage_id,
            stage_type=stage_type,
            assigned_node=assigned_node,
            queue_wait_ms=queue_wait_ms,
            status="running",
        ),
        reporter,
    )


def report_stage_end(
    workflow_id: str,
    workflow_type: str,
    stage_id: str,
    stage_type: str,
    assigned_node: str,
    exec_time_ms: int,
    status: str = "completed",
    reporter: WorkflowReporter | None = None,
) -> dict:
    return _report(
        WorkflowEvent(
            event_type="stage_end",
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage_id,
            stage_type=stage_type,
            assigned_node=assigned_node,
            exec_time_ms=exec_time_ms,
            status=status,
        ),
        reporter,
    )


def report_migration(
    workflow_id: str,
    workflow_type: str,
    stage_id: str,
    stage_type: str,
    from_node: str,
    to_node: str,
    transfer_time_ms: int | None = None,
    reason: str | None = None,
    reporter: WorkflowReporter | None = None,
) -> dict:
    return _report(
        WorkflowEvent(
            event_type="migration_event",
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage_id,
            stage_type=stage_type,
            assigned_node=to_node,
            from_node=from_node,
            to_node=to_node,
            transfer_time_ms=transfer_time_ms,
            reason=reason,
            status="migrating",
        ),
        reporter,
    )


def report_failure(
    workflow_id: str,
    workflow_type: str,
    stage_id: str,
    stage_type: str,
    assigned_node: str,
    reason: str,
    status: str = "failed",
    reporter: WorkflowReporter | None = None,
) -> dict:
    return _report(
        WorkflowEvent(
            event_type="failure_event",
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage_id,
            stage_type=stage_type,
            assigned_node=assigned_node,
            reason=reason,
            status=status,
        ),
        reporter,
    )


def report_workflow_end(
    workflow_id: str,
    workflow_type: str,
    stage_id: str,
    stage_type: str,
    assigned_node: str,
    status: str = "completed",
    reporter: WorkflowReporter | None = None,
) -> dict:
    return _report(
        WorkflowEvent(
            event_type="workflow_end",
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage_id,
            stage_type=stage_type,
            assigned_node=assigned_node,
            status=status,
        ),
        reporter,
    )
