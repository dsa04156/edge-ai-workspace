from __future__ import annotations

from datetime import datetime, timezone

from app.models import PlacementSelectionResult, PlacementServiceProfileRef
from app.runtime_execution_plan import build_runtime_execution_plan
from app.runtime_recommendation_models import (
    RuntimeRecommendationDecision,
    RuntimeRecommendationDwell,
    RuntimeRecommendationMetrics,
    RuntimeRecommendationTarget,
)


NOW = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)


def _placement(selected_node: str = "server-b") -> PlacementSelectionResult:
    return PlacementSelectionResult(
        generated_at=NOW,
        status="selected",
        service_profile=PlacementServiceProfileRef(
            namespace="factory",
            service="quality-ai",
            pod_count=1,
            request_coverage_ratio=1,
        ),
        selected_node=selected_node,
        selected_score=91,
        reason_codes=["selected_highest_score"],
    )


def _decision(state: str = "AUGMENT_RECOMMENDED") -> RuntimeRecommendationDecision:
    action = "augment" if state == "AUGMENT_RECOMMENDED" else "replace"
    return RuntimeRecommendationDecision(
        service_id="quality-ai",
        namespace="factory",
        workload_kind="Deployment",
        workload_name="quality-ai",
        current_nodes=["edge-a"],
        state=state,
        previous_state="OBSERVING",
        reason_codes=["sustained_resource_and_service_pressure"],
        metrics=RuntimeRecommendationMetrics(
            desired_replicas=1,
            ready_replicas=1,
        ),
        dwell=RuntimeRecommendationDwell(),
        recommendation=RuntimeRecommendationTarget(
            action=action,
            selected_node="server-b",
            selected_score=91,
        ),
        placement=_placement(),
        observation_source="container-cadvisor",
        observation_scope="container",
        observed_at=NOW,
    )


def test_augment_plan_has_create_ready_and_traffic_distribution_steps() -> None:
    decision = _decision()

    plan = build_runtime_execution_plan(decision, now=NOW)
    repeated = build_runtime_execution_plan(decision, now=NOW)

    assert plan.status == "planned"
    assert plan.action == "augment"
    assert plan.plan_id == repeated.plan_id
    assert [step.action for step in plan.steps] == [
        "create_candidate",
        "verify_ready",
        "validate_candidate_pre_activation",
        "handoff_execution_ownership",
        "verify_active_candidate",
        "distribute_traffic",
        "rollback_execution_ownership",
    ]
    assert all(step.execution_mode == "always" for step in plan.steps[:-1])
    assert plan.steps[-1].execution_mode == "on_failure"
    assert all(step.prerequisites for step in plan.steps)
    assert all(step.failure_conditions for step in plan.steps)
    candidate = plan.steps[0].targets[0]
    assert candidate.node == "server-b"
    assert candidate.workload.role == "candidate"
    assert candidate.workload.name.startswith("quality-ai-augment-")
    traffic_targets = plan.steps[5].targets
    assert {(item.node, item.workload.role) for item in traffic_targets} == {
        ("edge-a", "current"),
        ("server-b", "candidate"),
    }
    assert plan.mode == "read_only"


def test_replace_plan_has_cutover_termination_and_conditional_rollback() -> None:
    decision = _decision("REPLACE_RECOMMENDED")
    decision.reason_codes = ["sustained_runtime_failure", "pod_not_ready"]

    plan = build_runtime_execution_plan(decision, now=NOW)

    assert plan.status == "planned"
    assert plan.action == "replace"
    assert [step.action for step in plan.steps] == [
        "create_candidate",
        "verify_ready",
        "validate_candidate_pre_activation",
        "handoff_execution_ownership",
        "verify_active_candidate",
        "switch_traffic",
        "verify_switched_traffic",
        "terminate_current",
        "rollback_traffic",
        "rollback_execution_ownership",
    ]
    assert plan.steps[-1].execution_mode == "on_failure"
    assert plan.steps[-1].depends_on == [
        "handoff-execution-ownership",
        "verify-active-candidate",
        "switch-traffic",
        "verify-switched-traffic",
    ]
    assert {target.workload.role for target in plan.steps[-1].targets} == {
        "current",
        "candidate",
    }
    terminate = plan.steps[7]
    assert terminate.targets[0].node == "edge-a"
    assert terminate.targets[0].workload.name == "quality-ai"


def test_non_actionable_and_blocked_recommendations_never_create_steps() -> None:
    normal = _decision()
    normal.state = "NORMAL"
    normal.recommendation = RuntimeRecommendationTarget()
    normal.placement = None
    blocked = _decision()
    blocked.state = "BLOCKED"
    blocked.recommendation = RuntimeRecommendationTarget()
    blocked.placement = None
    blocked.reason_codes = ["input_stale"]

    normal_plan = build_runtime_execution_plan(normal, now=NOW)
    blocked_plan = build_runtime_execution_plan(blocked, now=NOW)

    assert normal_plan.status == "not_applicable"
    assert normal_plan.steps == []
    assert normal_plan.reason_codes == ["runtime_recommendation_not_actionable"]
    assert blocked_plan.status == "blocked"
    assert blocked_plan.steps == []
    assert blocked_plan.reason_codes == ["runtime_recommendation_blocked", "input_stale"]


def test_inconsistent_recommendation_fails_closed_without_steps() -> None:
    decision = _decision()
    decision.recommendation.selected_node = "edge-a"

    plan = build_runtime_execution_plan(decision, now=NOW)

    assert plan.status == "blocked"
    assert plan.steps == []
    assert "selected_node_is_current_node" in plan.reason_codes

    missing_current = _decision()
    missing_current.current_nodes = []
    missing_current_plan = build_runtime_execution_plan(missing_current, now=NOW)

    assert missing_current_plan.status == "blocked"
    assert missing_current_plan.steps == []
    assert "current_node_unavailable" in missing_current_plan.reason_codes
