from workflow_reporter import (
    WorkflowReporter,
    report_migration,
    report_stage_end,
    report_stage_start,
)


def main() -> None:
    reporter = WorkflowReporter()

    report_stage_start(
        workflow_id="wf-demo-001",
        workflow_type="edge_inference",
        stage_id="preprocess",
        stage_type="preprocess",
        assigned_node="etri-dev0002-raspi5",
        queue_wait_ms=120,
        reporter=reporter,
    )

    report_migration(
        workflow_id="wf-demo-001",
        workflow_type="edge_inference",
        stage_id="inference",
        stage_type="inference",
        from_node="etri-dev0002-raspi5",
        to_node="etri-dev0001-jetorn",
        transfer_time_ms=780,
        reason="gpu_required",
        reporter=reporter,
    )

    report_stage_end(
        workflow_id="wf-demo-001",
        workflow_type="edge_inference",
        stage_id="inference",
        stage_type="inference",
        assigned_node="etri-dev0001-jetorn",
        exec_time_ms=1640,
        reporter=reporter,
    )


if __name__ == "__main__":
    main()
