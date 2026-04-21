from datetime import datetime, timezone

from app.models import NodeRawMetrics, WorkflowEvent
from app.normalizer import build_summary, normalize_node_state, normalize_workflow_state


def test_normalize_node_state_marks_high_pressure_and_degraded():
    raw = NodeRawMetrics(
        instance="192.168.0.3:9100",
        hostname="etri-dev0001-jetorn",
        node_type="edge_ai_device",
        up=1.0,
        cpu_utilization=0.92,
        memory_usage_ratio=0.95,
        load_average=4.6,
        network_rx_rate=10_000_000,
        network_tx_rate=15_000_000,
        collected_at=datetime.now(timezone.utc),
    )

    state = normalize_node_state(raw)

    assert state.compute_pressure == "high"
    assert state.memory_pressure == "high"
    assert state.node_health == "degraded"


def test_normalize_workflow_tracks_migrations_and_risk():
    event_time = datetime.now(timezone.utc)
    first = WorkflowEvent(
        event_type="stage_start",
        timestamp=event_time,
        workflow_id="wf-1",
        workflow_type="inference",
        stage_id="stage-a",
        stage_type="decode",
        assigned_node="etri-dev0002-raspi5",
        queue_wait_ms=2000,
        status="running",
    )
    second = WorkflowEvent(
        event_type="migration_event",
        timestamp=event_time,
        workflow_id="wf-1",
        workflow_type="inference",
        stage_id="stage-a",
        stage_type="decode",
        assigned_node="etri-dev0001-jetorn",
        from_node="etri-dev0002-raspi5",
        to_node="etri-dev0001-jetorn",
        transfer_time_ms=15000,
        status="migrating",
    )

    state1 = normalize_workflow_state(first, None, now=event_time)
    state2 = normalize_workflow_state(second, state1, now=event_time)

    assert state2.workflow_urgency == "high"
    assert state2.sla_risk == "medium"
    assert state2.placement_stability == "moving"
    assert state2.migration_count_last_hour == 1


def test_build_summary_surfaces_hotspots_and_risky_workflows():
    node_state = normalize_node_state(
        NodeRawMetrics(
            instance="192.168.0.56:9100",
            hostname="etri-ser0001-CG0MSB",
            node_type="cloud_server",
            up=1.0,
            cpu_utilization=0.91,
            memory_usage_ratio=0.40,
            load_average=2.0,
            network_rx_rate=1_000_000,
            network_tx_rate=1_000_000,
            collected_at=datetime.now(timezone.utc),
        )
    )
    workflow_state = normalize_workflow_state(
        WorkflowEvent(
            event_type="failure_event",
            timestamp=datetime.now(timezone.utc),
            workflow_id="wf-risk",
            workflow_type="inference",
            stage_id="stage-b",
            assigned_node="etri-ser0001-CG0MSB",
            status="failed",
            reason="oom",
        ),
        None,
    )

    summary = build_summary([node_state], [workflow_state])

    assert summary.hotspot_nodes[0]["hostname"] == "etri-ser0001-CG0MSB"
    assert summary.sla_risk_workflows[0]["workflow_id"] == "wf-risk"
