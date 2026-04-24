from datetime import datetime, timedelta, timezone

from app.models import WorkflowEvent, WorkflowState
from app.storage import StateStore


def _workflow_state(workflow_id: str) -> WorkflowState:
    now = datetime.now(timezone.utc)
    return WorkflowState(
        workflow_id=workflow_id,
        workflow_type="vision_pipeline",
        last_event_type="stage_end",
        last_stage_id="preprocess",
        last_stage_type="preprocess",
        assigned_node="etri-ser0001-cg0msb",
        last_status="completed",
        latest_timestamp=now,
        workflow_urgency="low",
        sla_risk="low",
        placement_stability="stable",
        recent_event={},
    )


def test_store_builds_stage_and_migration_cost_stats(tmp_path):
    store = StateStore(tmp_path)
    base = datetime.now(timezone.utc)

    for idx in range(3):
        workflow_id = f"wf-{idx}"
        state = _workflow_state(workflow_id)
        migration_time = 150 + idx * 10
        warmup_time = 200 + idx * 5
        exec_time = 1000 + idx * 100
        store.record_workflow_event(
            WorkflowEvent(
                event_type="migration_event",
                timestamp=base + timedelta(seconds=idx * 10),
                workflow_id=workflow_id,
                workflow_type="vision_pipeline",
                stage_id="preprocess",
                stage_type="preprocess",
                assigned_node="etri-dev0001-jetorn",
                from_node="etri-dev0001-jetorn",
                to_node="etri-ser0001-cg0msb",
                status="migrating",
            ),
            state,
        )
        store.record_workflow_event(
            WorkflowEvent(
                event_type="stage_job_created",
                timestamp=base + timedelta(seconds=idx * 10, milliseconds=10),
                workflow_id=workflow_id,
                workflow_type="vision_pipeline",
                stage_id="preprocess",
                stage_type="preprocess",
                assigned_node="etri-ser0001-cg0msb",
                status="scheduled",
                action_type="offload_to_cloud",
            ),
            state,
        )
        start_ts = base + timedelta(
            seconds=idx * 10,
            milliseconds=migration_time,
        )
        store.record_workflow_event(
            WorkflowEvent(
                event_type="stage_start",
                timestamp=start_ts,
                workflow_id=workflow_id,
                workflow_type="vision_pipeline",
                stage_id="preprocess",
                stage_type="preprocess",
                assigned_node="etri-ser0001-cg0msb",
                queue_wait_ms=50,
                status="running",
                action_type="offload_to_cloud",
            ),
            state,
        )
        store.record_workflow_event(
            WorkflowEvent(
                event_type="stage_end",
                timestamp=start_ts + timedelta(milliseconds=exec_time),
                workflow_id=workflow_id,
                workflow_type="vision_pipeline",
                stage_id="preprocess",
                stage_type="preprocess",
                assigned_node="etri-ser0001-cg0msb",
                transfer_time_ms=25,
                status="completed",
                action_type="offload_to_cloud",
            ),
            state,
        )

    stage_stats = store.get_stage_cost_stats()
    migration_stats = store.get_migration_cost_stats()

    assert len(stage_stats) == 1
    assert stage_stats[0].stage_type == "preprocess"
    assert stage_stats[0].sample_count == 3
    assert stage_stats[0].queue_median_ms == 50.0
    assert stage_stats[0].warmup_median_ms > 0

    assert len(migration_stats) == 1
    assert migration_stats[0].sample_count == 3
    assert migration_stats[0].migration_median_ms == 160.0


def test_store_reloads_observations_on_restart(tmp_path):
    first = StateStore(tmp_path)
    state = _workflow_state("wf-reload")
    ts = datetime.now(timezone.utc)
    first.record_workflow_event(
        WorkflowEvent(
            event_type="stage_job_created",
            timestamp=ts,
            workflow_id="wf-reload",
            workflow_type="vision_pipeline",
            stage_id="capture",
            stage_type="capture",
            assigned_node="etri-dev0002-raspi5",
            status="scheduled",
        ),
        state,
    )
    first.record_workflow_event(
        WorkflowEvent(
            event_type="stage_start",
            timestamp=ts + timedelta(milliseconds=100),
            workflow_id="wf-reload",
            workflow_type="vision_pipeline",
            stage_id="capture",
            stage_type="capture",
            assigned_node="etri-dev0002-raspi5",
            status="running",
        ),
        state,
    )
    first.record_workflow_event(
        WorkflowEvent(
            event_type="stage_end",
            timestamp=ts + timedelta(milliseconds=900),
            workflow_id="wf-reload",
            workflow_type="vision_pipeline",
            stage_id="capture",
            stage_type="capture",
            assigned_node="etri-dev0002-raspi5",
            status="completed",
        ),
        state,
    )

    second = StateStore(tmp_path)
    stats = second.get_stage_cost_stats()

    assert len(stats) == 1
    assert stats[0].stage_type == "capture"
    assert stats[0].sample_count == 1
