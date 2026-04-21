from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx
from pydantic import BaseModel

from .client import WorkflowReporter
from .helpers import (
    report_failure,
    report_migration,
    report_stage_end,
    report_stage_start,
    report_workflow_end,
)


class StageMetadata(BaseModel):
    stage_type: str
    requires_accelerator: bool
    compute_intensity: str
    memory_intensity: str
    latency_sensitivity: str
    input_size_kb: int
    output_size_kb: int


class StageSpec(BaseModel):
    stage_id: str
    stage_metadata: StageMetadata
    queue_wait_ms: int = 0
    exec_time_ms: int = 100
    transfer_time_ms: int = 0


class PlacementDecision(BaseModel):
    workflow_id: str
    stage_id: str
    target_node: str | None
    decision_reason: str
    action_type: str
    score_breakdown: dict[str, float] = {}


class StageRunResult(BaseModel):
    stage_id: str
    target_node: str
    action_type: str
    decision_reason: str


class WorkflowRunResult(BaseModel):
    workflow_id: str
    workflow_type: str
    stages: list[StageRunResult]


@dataclass(frozen=True)
class Settings:
    placement_engine_url: str = os.getenv(
        "PLACEMENT_ENGINE_URL",
        "http://placement-engine:8001",
    )
    workflow_id: str = os.getenv("WORKFLOW_ID", "wf-vision-demo-001")
    workflow_type: str = os.getenv("WORKFLOW_TYPE", "vision_pipeline")
    simulate_delay: bool = os.getenv("SIMULATE_DELAY", "false").lower() == "true"


def build_default_node_profiles() -> list[dict]:
    return [
        {
            "hostname": "etri-ser0001-CG0MSB",
            "node_type": "cloud_server",
            "arch": "x86_64",
            "compute_class": "high",
            "memory_class": "high",
            "accelerator_type": "gpu_server",
            "preferred_workload": ["large_model_serving", "postprocess"],
            "risky_workload": ["sensor_ingest"],
        },
        {
            "hostname": "etri-dev0001-jetorn",
            "node_type": "edge_ai_device",
            "arch": "aarch64",
            "compute_class": "medium",
            "memory_class": "low",
            "accelerator_type": "gpu_embedded",
            "preferred_workload": ["edge_inference", "preprocess"],
            "risky_workload": ["large_model_serving"],
        },
        {
            "hostname": "etri-dev0002-raspi5",
            "node_type": "edge_light_device",
            "arch": "aarch64",
            "compute_class": "low",
            "memory_class": "low",
            "accelerator_type": "none",
            "preferred_workload": ["capture", "sensor_ingest", "preprocess"],
            "risky_workload": ["large_model_serving", "inference"],
        },
    ]


def build_vision_pipeline() -> list[StageSpec]:
    return [
        StageSpec(
            stage_id="capture",
            stage_metadata=StageMetadata(
                stage_type="capture",
                requires_accelerator=False,
                compute_intensity="low",
                memory_intensity="low",
                latency_sensitivity="high",
                input_size_kb=128,
                output_size_kb=512,
            ),
            queue_wait_ms=30,
            exec_time_ms=80,
            transfer_time_ms=20,
        ),
        StageSpec(
            stage_id="preprocess",
            stage_metadata=StageMetadata(
                stage_type="preprocess",
                requires_accelerator=False,
                compute_intensity="medium",
                memory_intensity="low",
                latency_sensitivity="high",
                input_size_kb=512,
                output_size_kb=1024,
            ),
            queue_wait_ms=60,
            exec_time_ms=140,
            transfer_time_ms=40,
        ),
        StageSpec(
            stage_id="inference",
            stage_metadata=StageMetadata(
                stage_type="inference",
                requires_accelerator=True,
                compute_intensity="high",
                memory_intensity="medium",
                latency_sensitivity="medium",
                input_size_kb=1024,
                output_size_kb=256,
            ),
            queue_wait_ms=120,
            exec_time_ms=900,
            transfer_time_ms=120,
        ),
        StageSpec(
            stage_id="postprocess",
            stage_metadata=StageMetadata(
                stage_type="postprocess",
                requires_accelerator=False,
                compute_intensity="medium",
                memory_intensity="low",
                latency_sensitivity="medium",
                input_size_kb=256,
                output_size_kb=128,
            ),
            queue_wait_ms=40,
            exec_time_ms=110,
            transfer_time_ms=30,
        ),
        StageSpec(
            stage_id="result_delivery",
            stage_metadata=StageMetadata(
                stage_type="result_delivery",
                requires_accelerator=False,
                compute_intensity="low",
                memory_intensity="low",
                latency_sensitivity="high",
                input_size_kb=64,
                output_size_kb=32,
            ),
            queue_wait_ms=10,
            exec_time_ms=60,
            transfer_time_ms=10,
        ),
    ]


def request_stage_placement(
    *,
    placement_engine_url: str,
    workflow_id: str,
    workflow_type: str,
    stage: StageSpec,
    node_profiles: list[dict],
    current_placement: str | None,
) -> PlacementDecision:
    response = httpx.post(
        f"{placement_engine_url.rstrip('/')}/placement/decide",
        json={
            "workflow_id": workflow_id,
            "stage_id": stage.stage_id,
            "workflow_type": workflow_type,
            "stage_metadata": stage.stage_metadata.model_dump(),
            "node_profiles": node_profiles,
            "current_placement": current_placement,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return PlacementDecision(**response.json()["decision"])


def run_vision_pipeline(
    *,
    workflow_id: str,
    workflow_type: str = "vision_pipeline",
    placement_engine_url: str = "http://placement-engine:8001",
    node_profiles: list[dict] | None = None,
    current_placement: dict[str, str] | None = None,
    reporter: WorkflowReporter | None = None,
    simulate_delay: bool = False,
) -> WorkflowRunResult:
    active_reporter = reporter or WorkflowReporter()
    profiles = node_profiles or build_default_node_profiles()
    stage_results: list[StageRunResult] = []
    placements = dict(current_placement or {})
    stages = build_vision_pipeline()

    for stage in stages:
        previous_node = placements.get(stage.stage_id)
        decision = request_stage_placement(
            placement_engine_url=placement_engine_url,
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage=stage,
            node_profiles=profiles,
            current_placement=previous_node,
        )

        if not decision.target_node or decision.action_type == "reject":
            report_failure(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                stage_id=stage.stage_id,
                stage_type=stage.stage_metadata.stage_type,
                assigned_node=previous_node or "unassigned",
                reason=decision.decision_reason,
                reporter=active_reporter,
            )
            raise RuntimeError(
                f"Stage {stage.stage_id} could not be placed: {decision.decision_reason}"
            )

        if previous_node and previous_node != decision.target_node:
            report_migration(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                stage_id=stage.stage_id,
                stage_type=stage.stage_metadata.stage_type,
                from_node=previous_node,
                to_node=decision.target_node,
                transfer_time_ms=stage.transfer_time_ms,
                reason=decision.decision_reason,
                reporter=active_reporter,
            )

        report_stage_start(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage.stage_id,
            stage_type=stage.stage_metadata.stage_type,
            assigned_node=decision.target_node,
            queue_wait_ms=stage.queue_wait_ms,
            reporter=active_reporter,
        )

        if simulate_delay:
            time.sleep(stage.exec_time_ms / 1000.0)

        report_stage_end(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            stage_id=stage.stage_id,
            stage_type=stage.stage_metadata.stage_type,
            assigned_node=decision.target_node,
            exec_time_ms=stage.exec_time_ms,
            reporter=active_reporter,
        )

        placements[stage.stage_id] = decision.target_node
        stage_results.append(
            StageRunResult(
                stage_id=stage.stage_id,
                target_node=decision.target_node,
                action_type=decision.action_type,
                decision_reason=decision.decision_reason,
            )
        )

    last_stage = stages[-1]
    last_node = placements[last_stage.stage_id]
    report_workflow_end(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        stage_id=last_stage.stage_id,
        stage_type=last_stage.stage_metadata.stage_type,
        assigned_node=last_node,
        reporter=active_reporter,
    )

    return WorkflowRunResult(
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        stages=stage_results,
    )


def main() -> None:
    settings = Settings()
    result = run_vision_pipeline(
        workflow_id=settings.workflow_id,
        workflow_type=settings.workflow_type,
        placement_engine_url=settings.placement_engine_url,
        simulate_delay=settings.simulate_delay,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
