from __future__ import annotations

from .models import NodeState, SummaryState, WorkflowState


PRESSURE_VALUE = {"low": 0.0, "medium": 1.0, "high": 2.0}
HEALTH_VALUE = {"healthy": 0.0, "degraded": 1.0, "unavailable": 2.0}
RISK_VALUE = {"low": 0.0, "medium": 1.0, "high": 2.0}
STABILITY_VALUE = {"stable": 0.0, "moving": 1.0, "unstable": 2.0}


def _escape_label(value: str | None) -> str:
    text = value or ""
    return text.replace("\\", r"\\").replace('"', r"\"").replace("\n", r"\n")


def _labels(**labels: str | None) -> str:
    parts = [f'{key}="{_escape_label(value)}"' for key, value in labels.items()]
    return "{" + ",".join(parts) + "}"


def _metric_lines(
    name: str,
    metric_type: str,
    help_text: str,
    samples: list[tuple[dict[str, str | None], float]],
) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {metric_type}"]
    for label_values, value in samples:
        lines.append(f"{name}{_labels(**label_values)} {value}")
    return lines


def render_metrics(
    node_states: list[NodeState],
    workflow_states: list[WorkflowState],
    summary: SummaryState,
) -> str:
    lines: list[str] = []

    lines.extend(
        _metric_lines(
            "edge_orch_node_up",
            "gauge",
            "Latest node up metric collected by state aggregator.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                    },
                    node.raw_metrics["up"],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_cpu_utilization_ratio",
            "gauge",
            "Latest node CPU utilization ratio collected by state aggregator.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                    },
                    node.raw_metrics["cpu_utilization"],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_memory_usage_ratio",
            "gauge",
            "Latest node memory usage ratio collected by state aggregator.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                    },
                    node.raw_metrics["memory_usage_ratio"],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_load_average",
            "gauge",
            "Latest node load average collected by state aggregator.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                    },
                    node.raw_metrics["load_average"],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_network_rx_rate_bytes_per_second",
            "gauge",
            "Latest node network receive rate collected by state aggregator.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                    },
                    node.raw_metrics["network_rx_rate"],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_network_tx_rate_bytes_per_second",
            "gauge",
            "Latest node network transmit rate collected by state aggregator.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                    },
                    node.raw_metrics["network_tx_rate"],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_compute_pressure",
            "gauge",
            "Normalized compute pressure for each node.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                        "level": node.compute_pressure,
                    },
                    PRESSURE_VALUE[node.compute_pressure],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_memory_pressure",
            "gauge",
            "Normalized memory pressure for each node.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                        "level": node.memory_pressure,
                    },
                    PRESSURE_VALUE[node.memory_pressure],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_network_pressure",
            "gauge",
            "Normalized network pressure for each node.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                        "level": node.network_pressure,
                    },
                    PRESSURE_VALUE[node.network_pressure],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_node_health",
            "gauge",
            "Normalized health level for each node.",
            [
                (
                    {
                        "hostname": node.hostname,
                        "instance": node.instance,
                        "node_type": node.node_type,
                        "level": node.node_health,
                    },
                    HEALTH_VALUE[node.node_health],
                )
                for node in node_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_workflow_event_count",
            "gauge",
            "Latest workflow event count tracked by state aggregator.",
            [
                (
                    {
                        "workflow_id": workflow.workflow_id,
                        "workflow_type": workflow.workflow_type,
                        "assigned_node": workflow.assigned_node,
                    },
                    float(workflow.event_count),
                )
                for workflow in workflow_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_workflow_migration_count_last_hour",
            "gauge",
            "Workflow migration count observed in the last hour.",
            [
                (
                    {
                        "workflow_id": workflow.workflow_id,
                        "workflow_type": workflow.workflow_type,
                        "assigned_node": workflow.assigned_node,
                    },
                    float(workflow.migration_count_last_hour),
                )
                for workflow in workflow_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_workflow_sla_risk",
            "gauge",
            "Normalized SLA risk for each workflow.",
            [
                (
                    {
                        "workflow_id": workflow.workflow_id,
                        "workflow_type": workflow.workflow_type,
                        "assigned_node": workflow.assigned_node,
                        "level": workflow.sla_risk,
                    },
                    RISK_VALUE[workflow.sla_risk],
                )
                for workflow in workflow_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_workflow_urgency",
            "gauge",
            "Normalized urgency for each workflow.",
            [
                (
                    {
                        "workflow_id": workflow.workflow_id,
                        "workflow_type": workflow.workflow_type,
                        "assigned_node": workflow.assigned_node,
                        "level": workflow.workflow_urgency,
                    },
                    RISK_VALUE[workflow.workflow_urgency],
                )
                for workflow in workflow_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_workflow_placement_stability",
            "gauge",
            "Normalized placement stability for each workflow.",
            [
                (
                    {
                        "workflow_id": workflow.workflow_id,
                        "workflow_type": workflow.workflow_type,
                        "assigned_node": workflow.assigned_node,
                        "level": workflow.placement_stability,
                    },
                    STABILITY_VALUE[workflow.placement_stability],
                )
                for workflow in workflow_states
            ],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_summary_hotspot_nodes",
            "gauge",
            "Number of hotspot nodes in the latest summary.",
            [({}, float(len(summary.hotspot_nodes)))],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_summary_sla_risk_workflows",
            "gauge",
            "Number of workflows currently flagged with high SLA risk.",
            [({}, float(len(summary.sla_risk_workflows)))],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_summary_recent_migration_count",
            "gauge",
            "Total recent migration count across tracked workflows.",
            [({}, float(summary.recent_migration_count))],
        )
    )
    lines.extend(
        _metric_lines(
            "edge_orch_summary_unstable_workflows",
            "gauge",
            "Number of workflows with unstable or moving placement.",
            [({}, float(len(summary.unstable_workflows)))],
        )
    )

    lines.append("")
    return "\n".join(lines)
