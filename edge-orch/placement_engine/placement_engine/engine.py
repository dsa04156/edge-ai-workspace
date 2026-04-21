from __future__ import annotations

from math import inf

from .models import NodeProfile, NodeState, PlacementDecision, StageMetadata


COMPUTE_LEVEL = {"low": 1, "medium": 2, "high": 3}
MEMORY_LEVEL = {"low": 1, "medium": 2, "high": 3}


def _is_heavy_inference(stage: StageMetadata, workflow_type: str | None) -> bool:
    return (
        stage.stage_type in {"inference", "large_inference"}
        and stage.compute_intensity == "high"
    ) or workflow_type == "large_model_serving"


def _is_source_near(stage: StageMetadata, workflow_type: str | None) -> bool:
    return (
        stage.stage_type in {"capture", "preprocess", "sensor_ingest"}
        or workflow_type == "preprocess"
        or stage.latency_sensitivity == "high"
    )


def _supports_accelerator(profile: NodeProfile) -> bool:
    return profile.node_type in {"cloud_server", "edge_ai_device"} or (
        profile.accelerator_type not in {None, "", "none"}
    )


def _disqualify(
    profile: NodeProfile,
    state: NodeState,
    stage: StageMetadata,
    workflow_type: str | None,
) -> str | None:
    if state.node_health == "unavailable":
        return "node unavailable"
    if stage.requires_accelerator and not _supports_accelerator(profile):
        return "accelerator required"
    if stage.compute_intensity == "high" and state.memory_pressure == "high":
        return "memory pressure high for heavy stage"
    if _is_heavy_inference(stage, workflow_type) and profile.node_type != "cloud_server":
        return "heavy inference prefers server"
    return None


def _compute_score(
    profile: NodeProfile,
    state: NodeState,
    stage: StageMetadata,
    workflow_type: str | None,
    current_placement: str | None,
) -> tuple[float, dict[str, float]]:
    compute_delay = COMPUTE_LEVEL[stage.compute_intensity] * 2.0
    transfer_cost = 0.0
    memory_penalty = 0.0
    overload_penalty = 0.0
    migration_penalty = 0.0

    if profile.compute_class == "high":
        compute_delay -= 1.8
    elif profile.compute_class == "medium":
        compute_delay -= 0.9

    if stage.memory_intensity == "high" and profile.memory_class == "low":
        memory_penalty += 3.0
    elif stage.memory_intensity == "medium" and profile.memory_class == "low":
        memory_penalty += 1.5

    if state.compute_pressure == "high":
        overload_penalty += 3.0
    elif state.compute_pressure == "medium":
        overload_penalty += 1.5
    if state.memory_pressure == "high":
        overload_penalty += 3.0
    elif state.memory_pressure == "medium":
        overload_penalty += 1.5

    if stage.input_size_kb + stage.output_size_kb > 2048:
        transfer_cost += 2.0
    elif stage.input_size_kb + stage.output_size_kb > 256:
        transfer_cost += 0.8

    if _is_source_near(stage, workflow_type):
        if profile.node_type == "edge_light_device":
            transfer_cost -= 2.2
            compute_delay -= 0.4
        elif profile.node_type == "edge_ai_device":
            transfer_cost -= 0.4
        elif profile.node_type == "cloud_server":
            transfer_cost += 1.8

    if _is_heavy_inference(stage, workflow_type):
        if profile.node_type == "cloud_server":
            compute_delay -= 1.5
        else:
            compute_delay += 4.0

    if stage.requires_accelerator and profile.node_type == "edge_ai_device":
        compute_delay -= 1.0

    if current_placement and current_placement != profile.hostname:
        migration_penalty += 1.0
    elif current_placement == profile.hostname:
        migration_penalty -= 0.8

    if workflow_type in profile.preferred_workload:
        compute_delay -= 0.5
    if workflow_type in profile.risky_workload:
        overload_penalty += 2.0

    weighted_sum = (
        compute_delay * 1.4
        + transfer_cost * 1.0
        + memory_penalty * 1.1
        + overload_penalty * 1.5
        + migration_penalty * 0.8
    )

    return weighted_sum, {
        "compute_delay": round(compute_delay, 3),
        "transfer_cost": round(transfer_cost, 3),
        "memory_penalty": round(memory_penalty, 3),
        "overload_penalty": round(overload_penalty, 3),
        "migration_penalty": round(migration_penalty, 3),
        "weighted_sum": round(weighted_sum, 3),
    }


def decide_stage_placement(
    workflow_id: str,
    stage_id: str,
    node_profiles: list[NodeProfile] | list[dict],
    node_states: list[NodeState] | list[dict],
    stage_metadata: StageMetadata | dict,
    current_placement: str | None = None,
    workflow_type: str | None = None,
) -> PlacementDecision:
    profiles = [item if isinstance(item, NodeProfile) else NodeProfile(**item) for item in node_profiles]
    normalized_states = [
        item if isinstance(item, NodeState) else NodeState(**item) for item in node_states
    ]
    states = {item.hostname: item for item in normalized_states}
    stage = stage_metadata if isinstance(stage_metadata, StageMetadata) else StageMetadata(**stage_metadata)

    best_profile: NodeProfile | None = None
    best_score = inf
    best_breakdown: dict[str, float] = {}
    rejection_reasons: list[str] = []

    for profile in profiles:
        state = states.get(profile.hostname)
        if state is None:
            rejection_reasons.append(f"{profile.hostname}: missing state")
            continue

        reason = _disqualify(profile, state, stage, workflow_type)
        if reason:
            rejection_reasons.append(f"{profile.hostname}: {reason}")
            continue

        score, breakdown = _compute_score(profile, state, stage, workflow_type, current_placement)
        if score < best_score:
            best_score = score
            best_profile = profile
            best_breakdown = breakdown

    if best_profile is None:
        cloud_profile = next((profile for profile in profiles if profile.node_type == "cloud_server"), None)
        if cloud_profile and "heavy inference prefers server" in " | ".join(rejection_reasons):
            return PlacementDecision(
                workflow_id=workflow_id,
                stage_id=stage_id,
                target_node=cloud_profile.hostname,
                decision_reason="fallback offload to cloud server",
                action_type="offload_to_cloud",
                score_breakdown={},
            )
        return PlacementDecision(
            workflow_id=workflow_id,
            stage_id=stage_id,
            target_node=None,
            decision_reason="; ".join(rejection_reasons) or "no eligible nodes",
            action_type="reject",
            score_breakdown={},
        )

    action_type = "keep" if current_placement == best_profile.hostname else "migrate"
    if best_profile.node_type == "cloud_server" and current_placement and current_placement != best_profile.hostname:
        action_type = "offload_to_cloud"

    decision_reason = f"selected {best_profile.hostname} with lowest weighted score"
    return PlacementDecision(
        workflow_id=workflow_id,
        stage_id=stage_id,
        target_node=best_profile.hostname,
        decision_reason=decision_reason,
        action_type=action_type,
        score_breakdown=best_breakdown,
    )


def replan_workflow(
    workflow_id: str,
    stages: list[dict],
    node_profiles: list[NodeProfile] | list[dict],
    node_states: list[NodeState] | list[dict],
    current_placement: dict[str, str] | None = None,
    workflow_type: str | None = None,
) -> list[PlacementDecision]:
    decisions: list[PlacementDecision] = []
    current = current_placement or {}

    for stage in stages:
        decision = decide_stage_placement(
            workflow_id=workflow_id,
            stage_id=stage["stage_id"],
            node_profiles=node_profiles,
            node_states=node_states,
            stage_metadata=stage["stage_metadata"],
            current_placement=current.get(stage["stage_id"]),
            workflow_type=workflow_type,
        )
        decisions.append(decision)
    return decisions
