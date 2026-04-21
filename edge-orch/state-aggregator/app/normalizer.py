from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import NodeRawMetrics, NodeState, SummaryState, WorkflowEvent, WorkflowState


def _pressure_from_value(value: float, medium: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def normalize_node_state(raw: NodeRawMetrics) -> NodeState:
    compute_signal = max(raw.cpu_utilization, raw.load_average / 4.0)
    network_total = raw.network_rx_rate + raw.network_tx_rate

    compute_pressure = _pressure_from_value(compute_signal, medium=0.60, high=0.85)
    memory_pressure = _pressure_from_value(raw.memory_usage_ratio, medium=0.70, high=0.90)
    network_pressure = _pressure_from_value(network_total, medium=20_000_000, high=80_000_000)

    if raw.up < 0.5:
        node_health = "unavailable"
    elif "high" in {compute_pressure, memory_pressure, network_pressure}:
        node_health = "degraded"
    else:
        node_health = "healthy"

    return NodeState(
        hostname=raw.hostname,
        instance=raw.instance,
        node_type=raw.node_type,
        collected_at=raw.collected_at,
        raw_metrics={
            "up": raw.up,
            "cpu_utilization": raw.cpu_utilization,
            "memory_usage_ratio": raw.memory_usage_ratio,
            "load_average": raw.load_average,
            "network_rx_rate": raw.network_rx_rate,
            "network_tx_rate": raw.network_tx_rate,
        },
        compute_pressure=compute_pressure,
        memory_pressure=memory_pressure,
        network_pressure=network_pressure,
        node_health=node_health,
    )


def normalize_workflow_state(
    event: WorkflowEvent,
    previous: WorkflowState | None,
    now: datetime | None = None,
) -> WorkflowState:
    reference_now = now or datetime.now(timezone.utc)
    previous_event_count = previous.event_count if previous else 0
    migration_count = previous.migration_count_last_hour if previous else 0

    if event.event_type == "migration_event":
        migration_count += 1
    if previous and previous.latest_timestamp < reference_now - timedelta(hours=1):
        migration_count = 1 if event.event_type == "migration_event" else 0

    total_latency_ms = sum(
        value or 0
        for value in [event.exec_time_ms, event.queue_wait_ms, event.transfer_time_ms]
    )

    failed = event.event_type == "failure_event" or (event.status or "").lower() in {
        "failed",
        "error",
    }
    urgent = event.event_type in {"failure_event", "migration_event"}

    if failed or total_latency_ms >= 30_000:
        sla_risk = "high"
    elif total_latency_ms >= 10_000 or (event.queue_wait_ms or 0) >= 5_000:
        sla_risk = "medium"
    else:
        sla_risk = "low"

    if failed or urgent:
        workflow_urgency = "high"
    elif sla_risk == "medium":
        workflow_urgency = "medium"
    else:
        workflow_urgency = "low"

    if migration_count >= 3:
        placement_stability = "unstable"
    elif migration_count >= 1:
        placement_stability = "moving"
    else:
        placement_stability = "stable"

    return WorkflowState(
        workflow_id=event.workflow_id,
        workflow_type=event.workflow_type or (previous.workflow_type if previous else None),
        last_event_type=event.event_type,
        last_stage_id=event.stage_id,
        last_stage_type=event.stage_type,
        assigned_node=event.to_node or event.assigned_node,
        last_status=event.status,
        latest_timestamp=event.timestamp,
        event_count=previous_event_count + 1,
        migration_count_last_hour=migration_count,
        workflow_urgency=workflow_urgency,
        sla_risk=sla_risk,
        placement_stability=placement_stability,
        recent_event=event.model_dump(mode="json"),
    )


def build_summary(
    node_states: list[NodeState],
    workflow_states: list[WorkflowState],
) -> SummaryState:
    hotspot_nodes = [
        {
            "hostname": node.hostname,
            "node_type": node.node_type,
            "node_health": node.node_health,
            "compute_pressure": node.compute_pressure,
            "memory_pressure": node.memory_pressure,
            "network_pressure": node.network_pressure,
        }
        for node in node_states
        if node.node_health != "healthy"
        or "high" in {
            node.compute_pressure,
            node.memory_pressure,
            node.network_pressure,
        }
    ]

    risk_workflows = [
        {
            "workflow_id": workflow.workflow_id,
            "assigned_node": workflow.assigned_node,
            "sla_risk": workflow.sla_risk,
            "workflow_urgency": workflow.workflow_urgency,
        }
        for workflow in workflow_states
        if workflow.sla_risk == "high"
    ]

    unstable_workflows = [
        {
            "workflow_id": workflow.workflow_id,
            "placement_stability": workflow.placement_stability,
            "migration_count_last_hour": workflow.migration_count_last_hour,
        }
        for workflow in workflow_states
        if workflow.placement_stability != "stable"
    ]

    return SummaryState(
        generated_at=datetime.now(timezone.utc),
        hotspot_nodes=hotspot_nodes,
        sla_risk_workflows=risk_workflows,
        recent_migration_count=sum(
            workflow.migration_count_last_hour for workflow in workflow_states
        ),
        unstable_workflows=unstable_workflows,
    )
