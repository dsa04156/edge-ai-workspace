from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from .models import PlacementSelectionResult, SchedulingModel
from .runtime_recommendation_models import (
    RuntimeRecommendationAction,
    RuntimeRecommendationDecision,
    RuntimeRecommendationState,
)


RuntimeExecutionPlanStatus = Literal["planned", "not_applicable", "blocked"]
RuntimeExecutionMode = Literal["always", "on_failure"]
RuntimeExecutionStepAction = Literal[
    "create_candidate",
    "verify_ready",
    "distribute_traffic",
    "switch_traffic",
    "terminate_current",
    "rollback",
]
RuntimeExecutionWorkloadRole = Literal["current", "candidate"]


class RuntimeExecutionCondition(SchedulingModel):
    code: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=500)


class RuntimeExecutionWorkload(SchedulingModel):
    namespace: str = Field(min_length=1, max_length=253)
    kind: Literal["Deployment", "StatefulSet"]
    name: str = Field(min_length=1, max_length=253)
    role: RuntimeExecutionWorkloadRole


class RuntimeExecutionTarget(SchedulingModel):
    node: str = Field(min_length=1, max_length=253)
    workload: RuntimeExecutionWorkload


class RuntimeExecutionStep(SchedulingModel):
    step_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    action: RuntimeExecutionStepAction
    execution_mode: RuntimeExecutionMode = "always"
    targets: list[RuntimeExecutionTarget] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    prerequisites: list[RuntimeExecutionCondition] = Field(min_length=1)
    failure_conditions: list[RuntimeExecutionCondition] = Field(min_length=1)


class RuntimeExecutionPlan(SchedulingModel):
    plan_id: str = Field(min_length=1, max_length=128)
    service_id: str
    recommendation_state: RuntimeRecommendationState
    action: RuntimeRecommendationAction
    status: RuntimeExecutionPlanStatus
    reason_codes: list[str] = Field(default_factory=list)
    current_nodes: list[str] = Field(default_factory=list)
    selected_node: str | None = None
    source_observed_at: datetime
    generated_at: datetime
    steps: list[RuntimeExecutionStep] = Field(default_factory=list)
    placement: PlacementSelectionResult | None = None
    mode: Literal["read_only"] = "read_only"


def build_runtime_execution_plan(
    decision: RuntimeRecommendationDecision,
    *,
    now: datetime | None = None,
    candidate_namespace: str | None = None,
) -> RuntimeExecutionPlan:
    generated_at = _utc(now or datetime.now(timezone.utc))
    plan_id, suffix = _identity(decision)
    common = {
        "plan_id": plan_id,
        "service_id": decision.service_id,
        "recommendation_state": decision.state,
        "current_nodes": sorted(set(decision.current_nodes)),
        "source_observed_at": decision.observed_at,
        "generated_at": generated_at,
        "placement": decision.placement,
    }
    if decision.state in {"NORMAL", "OBSERVING"}:
        return RuntimeExecutionPlan(
            **common,
            action="none",
            status="not_applicable",
            reason_codes=["runtime_recommendation_not_actionable"],
        )
    if decision.state == "BLOCKED":
        return RuntimeExecutionPlan(
            **common,
            action="none",
            status="blocked",
            reason_codes=_unique(
                ["runtime_recommendation_blocked", *decision.reason_codes]
            ),
        )

    expected_action: RuntimeRecommendationAction = (
        "augment" if decision.state == "AUGMENT_RECOMMENDED" else "replace"
    )
    validation_errors = _validate_actionable(decision, expected_action)
    if validation_errors:
        return RuntimeExecutionPlan(
            **common,
            action=expected_action,
            status="blocked",
            reason_codes=validation_errors,
            selected_node=decision.recommendation.selected_node,
        )

    selected_node = decision.recommendation.selected_node
    assert selected_node is not None
    candidate_name = _candidate_name(
        decision.workload_name,
        expected_action,
        suffix,
    )
    current_targets = [
        _target(
            decision,
            node=node,
            name=decision.workload_name,
            role="current",
        )
        for node in sorted(set(decision.current_nodes))
    ]
    candidate_target = _target(
        decision,
        node=selected_node,
        name=candidate_name,
        role="candidate",
        namespace=candidate_namespace,
    )
    steps = (
        _augment_steps(candidate_target, current_targets)
        if expected_action == "augment"
        else _replacement_steps(candidate_target, current_targets)
    )
    return RuntimeExecutionPlan(
        **common,
        action=expected_action,
        status="planned",
        reason_codes=_unique(["execution_plan_generated", *decision.reason_codes]),
        selected_node=selected_node,
        steps=steps,
    )


def _augment_steps(
    candidate: RuntimeExecutionTarget,
    current: list[RuntimeExecutionTarget],
) -> list[RuntimeExecutionStep]:
    return [
        RuntimeExecutionStep(
            step_id="create-candidate",
            sequence=1,
            action="create_candidate",
            targets=[candidate],
            prerequisites=_conditions(
                ("recommendation_still_current", "The source recommendation is still current."),
                ("selected_node_still_eligible", "The selected node still satisfies placement constraints."),
                ("workload_spec_available", "A reviewed workload specification and immutable image are available."),
            ),
            failure_conditions=_conditions(
                ("candidate_workload_conflict", "The planned candidate workload name already exists."),
                ("candidate_creation_failed", "The candidate workload cannot be created."),
                ("candidate_scheduling_failed", "The candidate cannot be scheduled on the selected node."),
            ),
        ),
        RuntimeExecutionStep(
            step_id="verify-ready",
            sequence=2,
            action="verify_ready",
            targets=[candidate],
            depends_on=["create-candidate"],
            prerequisites=_conditions(
                ("candidate_created", "The candidate workload was created on the selected node."),
                ("readiness_contract_available", "A service readiness contract is available."),
            ),
            failure_conditions=_conditions(
                ("candidate_ready_timeout", "The candidate does not become Ready before the approved timeout."),
                ("candidate_pod_failed", "A candidate Pod reports an unrecoverable failure."),
                ("candidate_node_unavailable", "The selected node becomes unavailable."),
            ),
        ),
        RuntimeExecutionStep(
            step_id="distribute-traffic",
            sequence=3,
            action="distribute_traffic",
            targets=[*current, candidate],
            depends_on=["verify-ready"],
            prerequisites=_conditions(
                ("candidate_ready", "The candidate is Ready and passes its service health check."),
                ("current_instance_healthy", "At least one current instance remains healthy during distribution."),
                ("traffic_policy_approved", "An approved traffic distribution policy is available."),
            ),
            failure_conditions=_conditions(
                ("traffic_distribution_failed", "Traffic cannot be distributed to the candidate."),
                ("post_distribution_health_degraded", "Service health degrades after traffic distribution."),
            ),
        ),
    ]


def _replacement_steps(
    candidate: RuntimeExecutionTarget,
    current: list[RuntimeExecutionTarget],
) -> list[RuntimeExecutionStep]:
    return [
        RuntimeExecutionStep(
            step_id="create-candidate",
            sequence=1,
            action="create_candidate",
            targets=[candidate],
            prerequisites=_conditions(
                ("recommendation_still_current", "The source recommendation is still current."),
                ("selected_node_still_eligible", "The selected node still satisfies placement constraints."),
                ("replacement_spec_available", "A reviewed replacement specification and immutable image are available."),
            ),
            failure_conditions=_conditions(
                ("candidate_workload_conflict", "The planned replacement workload name already exists."),
                ("replacement_creation_failed", "The replacement workload cannot be created."),
                ("replacement_scheduling_failed", "The replacement cannot be scheduled on the selected node."),
            ),
        ),
        RuntimeExecutionStep(
            step_id="verify-ready",
            sequence=2,
            action="verify_ready",
            targets=[candidate],
            depends_on=["create-candidate"],
            prerequisites=_conditions(
                ("candidate_created", "The replacement workload was created on the selected node."),
                ("readiness_contract_available", "A service readiness contract is available."),
            ),
            failure_conditions=_conditions(
                ("candidate_ready_timeout", "The replacement does not become Ready before the approved timeout."),
                ("candidate_pod_failed", "A replacement Pod reports an unrecoverable failure."),
                ("candidate_node_unavailable", "The selected node becomes unavailable."),
            ),
        ),
        RuntimeExecutionStep(
            step_id="switch-traffic",
            sequence=3,
            action="switch_traffic",
            targets=[*current, candidate],
            depends_on=["verify-ready"],
            prerequisites=_conditions(
                ("candidate_ready", "The replacement is Ready and passes its service health check."),
                ("traffic_cutover_approved", "Traffic cutover has explicit operator or controller approval."),
                ("rollback_material_retained", "The current workload specification and routing state are retained."),
            ),
            failure_conditions=_conditions(
                ("traffic_cutover_failed", "Traffic cannot be switched to the replacement."),
                ("post_cutover_health_degraded", "Service health degrades after traffic cutover."),
            ),
        ),
        RuntimeExecutionStep(
            step_id="terminate-current",
            sequence=4,
            action="terminate_current",
            targets=current,
            depends_on=["switch-traffic"],
            prerequisites=_conditions(
                ("cutover_verified", "Traffic cutover and service health have been verified."),
                ("candidate_serving", "The replacement is serving the expected workload."),
                ("rollback_material_retained", "The previous workload and routing specifications remain recoverable."),
            ),
            failure_conditions=_conditions(
                ("current_termination_failed", "A current instance cannot be terminated cleanly."),
                ("candidate_health_lost", "The replacement loses health before termination completes."),
            ),
        ),
        RuntimeExecutionStep(
            step_id="rollback",
            sequence=5,
            action="rollback",
            execution_mode="on_failure",
            targets=[*current, candidate],
            depends_on=["terminate-current"],
            prerequisites=_conditions(
                ("rollback_triggered", "A post-cutover or termination failure requires compensation."),
                ("rollback_material_retained", "The previous workload and routing specifications remain recoverable."),
                ("traffic_control_available", "The traffic control plane is available for restoration."),
            ),
            failure_conditions=_conditions(
                ("current_restore_failed", "The previous workload cannot be restored to a healthy state."),
                ("traffic_rollback_failed", "Traffic cannot be restored to the previous healthy target."),
                ("rollback_health_failed", "Service health does not recover after rollback."),
            ),
        ),
    ]


def _validate_actionable(
    decision: RuntimeRecommendationDecision,
    expected_action: RuntimeRecommendationAction,
) -> list[str]:
    errors: list[str] = []
    selected_node = decision.recommendation.selected_node
    if not decision.current_nodes:
        errors.append("current_node_unavailable")
    if decision.recommendation.action != expected_action:
        errors.append("recommendation_action_mismatch")
    if selected_node is None:
        errors.append("selected_node_unavailable")
    elif selected_node in decision.current_nodes:
        errors.append("selected_node_is_current_node")
    placement = decision.placement
    if placement is None or placement.status != "selected":
        errors.append("placement_not_selected")
    elif placement.selected_node != selected_node:
        errors.append("placement_selected_node_mismatch")
    return _unique(errors)


def _target(
    decision: RuntimeRecommendationDecision,
    *,
    node: str,
    name: str,
    role: RuntimeExecutionWorkloadRole,
    namespace: str | None = None,
) -> RuntimeExecutionTarget:
    return RuntimeExecutionTarget(
        node=node,
        workload=RuntimeExecutionWorkload(
            namespace=namespace or decision.namespace,
            kind=decision.workload_kind,
            name=name,
            role=role,
        ),
    )


def _conditions(*values: tuple[str, str]) -> list[RuntimeExecutionCondition]:
    return [
        RuntimeExecutionCondition(code=code, description=description)
        for code, description in values
    ]


def _identity(decision: RuntimeRecommendationDecision) -> tuple[str, str]:
    seed = "|".join(
        (
            decision.service_id,
            decision.namespace,
            decision.workload_kind,
            decision.workload_name,
            decision.state,
            decision.recommendation.selected_node or "none",
            _utc(decision.observed_at).isoformat(),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"runtime-plan-{digest[:16]}", digest[:8]


def _candidate_name(base: str, action: str, suffix: str) -> str:
    tail = f"-{action}-{suffix}"
    return f"{base[: 63 - len(tail)].rstrip('-')}{tail}"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
