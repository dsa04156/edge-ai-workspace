from __future__ import annotations

from math import inf

from .models import MigrationCostStats, NodeProfile, NodeState, PlacementDecision, StageCostStats, StageMetadata


COMPUTE_LEVEL = {"low": 1, "medium": 2, "high": 3}
MEMORY_LEVEL = {"low": 1, "medium": 2, "high": 3}
TRANSFER_BASE_MS = {"small": 20.0, "medium": 80.0, "large": 200.0}
NETWORK_MULTIPLIER = {"low": 1.0, "medium": 1.5, "high": 2.0}
WARMUP_FALLBACK_MS = {
    "cloud_server": 150.0,
    "edge_ai_device": 250.0,
    "edge_light_device": 250.0,
}
MIGRATION_FALLBACK_MS = 150.0
RESOURCE_OVERLOAD_MS = {"low": 0.0, "medium": 375.0, "high": 750.0}
RESOURCE_MEMORY_MS = {"low": 0.0, "medium": 0.0, "high": 0.0}
INSTABILITY_PENALTY_MS = 500.0


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


def _legacy_components(
    profile: NodeProfile,
    state: NodeState,
    stage: StageMetadata,
    workflow_type: str | None,
    current_placement: str | None,
) -> dict[str, float]:
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

    return {
        "compute_delay": compute_delay,
        "transfer_cost": transfer_cost,
        "memory_penalty": memory_penalty,
        "overload_penalty": overload_penalty,
        "migration_penalty": migration_penalty,
    }


def _transfer_bucket(total_size_kb: int) -> str:
    if total_size_kb > 2048:
        return "large"
    if total_size_kb > 256:
        return "medium"
    return "small"


def _to_stage_cost_map(stats: list[StageCostStats] | list[dict] | None) -> dict[tuple[str, str], StageCostStats]:
    items = stats or []
    result: dict[tuple[str, str], StageCostStats] = {}
    for item in items:
        normalized = item if isinstance(item, StageCostStats) else StageCostStats(**item)
        result[(normalized.stage_type, normalized.node)] = normalized
    return result


def _to_migration_cost_map(
    stats: list[MigrationCostStats] | list[dict] | None,
) -> dict[tuple[str, str, str], MigrationCostStats]:
    items = stats or []
    result: dict[tuple[str, str, str], MigrationCostStats] = {}
    for item in items:
        normalized = item if isinstance(item, MigrationCostStats) else MigrationCostStats(**item)
        result[(normalized.stage_type, normalized.from_node, normalized.to_node)] = normalized
    return result


def _expected_transfer_ms(
    profile: NodeProfile,
    state: NodeState,
    stage: StageMetadata,
    workflow_type: str | None,
) -> float:
    total_size_kb = stage.input_size_kb + stage.output_size_kb
    transfer_ms = TRANSFER_BASE_MS[_transfer_bucket(total_size_kb)] * NETWORK_MULTIPLIER[state.network_pressure]
    legacy = _legacy_components(profile, state, stage, workflow_type, None)
    transfer_ms += legacy["transfer_cost"] * 250.0
    if _is_source_near(stage, workflow_type):
        if profile.node_type == "edge_light_device":
            transfer_ms -= 250.0
        elif profile.node_type == "edge_ai_device":
            transfer_ms -= 80.0
        elif profile.node_type == "cloud_server":
            transfer_ms += 250.0
    return max(0.0, transfer_ms)


def _expected_exec_ms(
    stage: StageMetadata,
    profile: NodeProfile,
    state: NodeState,
    workflow_type: str | None,
    current_placement: str | None,
    stage_cost_stats: StageCostStats | None,
) -> tuple[float, bool, dict[str, float]]:
    legacy = _legacy_components(profile, state, stage, workflow_type, current_placement)
    if stage_cost_stats is not None and stage_cost_stats.sample_count >= 3:
        empirical = (stage_cost_stats.exec_median_ms + stage_cost_stats.exec_ema_ms) / 2.0
        return empirical, False, legacy
    fallback = max(0.0, legacy["compute_delay"]) * 300.0
    if _is_source_near(stage, workflow_type):
        if profile.node_type == "edge_light_device":
            fallback = max(0.0, fallback - 400.0)
        elif profile.node_type == "edge_ai_device":
            fallback = max(0.0, fallback - 100.0)
    return fallback, True, legacy


def _expected_queue_ms(stage_cost_stats: StageCostStats | None) -> float:
    if stage_cost_stats is not None and stage_cost_stats.sample_count >= 3:
        return stage_cost_stats.queue_median_ms
    return 0.0


def _expected_warmup_ms(profile: NodeProfile, stage_cost_stats: StageCostStats | None) -> float:
    if stage_cost_stats is not None and stage_cost_stats.sample_count >= 3:
        return stage_cost_stats.warmup_median_ms
    return WARMUP_FALLBACK_MS.get(profile.node_type, 250.0)


def _expected_migration_ms(
    stage: StageMetadata,
    current_placement: str | None,
    profile: NodeProfile,
    migration_cost_stats: MigrationCostStats | None,
) -> tuple[float, bool]:
    if current_placement is None or current_placement == profile.hostname:
        return 0.0, False
    if migration_cost_stats is not None and migration_cost_stats.sample_count >= 3:
        return (
            (migration_cost_stats.migration_median_ms + migration_cost_stats.migration_ema_ms) / 2.0,
            False,
        )
    return MIGRATION_FALLBACK_MS, True


def _resource_penalty_ms(legacy: dict[str, float], state: NodeState) -> float:
    overload_ms = RESOURCE_OVERLOAD_MS[state.compute_pressure] + RESOURCE_OVERLOAD_MS[state.memory_pressure]
    memory_ms = max(0.0, legacy["memory_penalty"]) * 300.0 + RESOURCE_MEMORY_MS[state.memory_pressure]
    risky_ms = max(0.0, legacy["overload_penalty"]) * 100.0
    return overload_ms + memory_ms + risky_ms


def _instability_penalty_ms(stage_cost_stats: StageCostStats | None) -> float:
    if stage_cost_stats is None:
        return 0.0
    if stage_cost_stats.recent_migration_count_last_hour >= 3:
        return INSTABILITY_PENALTY_MS
    return 0.0


def _decision_margin_ms(
    current_state: NodeState | None,
    current_stage_stats: StageCostStats | None,
) -> float:
    if current_state is not None and (
        current_state.compute_pressure == "high" or current_state.node_health == "degraded"
    ):
        margin = 600.0
    else:
        margin = 900.0
    if current_stage_stats is not None and current_stage_stats.placement_stability == "unstable":
        margin += 300.0
    return margin


def _action_type_for_target(profile: NodeProfile, current_placement: str | None) -> str:
    if current_placement == profile.hostname:
        return "keep"
    if profile.node_type == "cloud_server" and current_placement and current_placement != profile.hostname:
        return "offload_to_cloud"
    return "migrate"


def _evaluate_candidate(
    profile: NodeProfile,
    state: NodeState,
    stage: StageMetadata,
    workflow_type: str | None,
    current_placement: str | None,
    stage_cost_stats: StageCostStats | None,
    migration_cost_stats: MigrationCostStats | None,
) -> dict[str, float | int | bool | str | None]:
    exec_ms, used_exec_fallback, legacy = _expected_exec_ms(
        stage,
        profile,
        state,
        workflow_type,
        current_placement,
        stage_cost_stats,
    )
    queue_ms = _expected_queue_ms(stage_cost_stats)
    transfer_ms = _expected_transfer_ms(profile, state, stage, workflow_type)
    warmup_ms = _expected_warmup_ms(profile, stage_cost_stats)
    migration_ms, used_migration_fallback = _expected_migration_ms(
        stage,
        current_placement,
        profile,
        migration_cost_stats,
    )
    resource_penalty_ms = _resource_penalty_ms(legacy, state)
    instability_penalty_ms = _instability_penalty_ms(stage_cost_stats)
    expected_cost_ms = (
        exec_ms
        + queue_ms
        + transfer_ms
        + warmup_ms
        + migration_ms
        + resource_penalty_ms
        + instability_penalty_ms
    )

    return {
        "target_node": profile.hostname,
        "expected_cost_ms": round(expected_cost_ms, 3),
        "exec_ms": round(exec_ms, 3),
        "queue_ms": round(queue_ms, 3),
        "transfer_ms": round(transfer_ms, 3),
        "warmup_ms": round(warmup_ms, 3),
        "migration_ms": round(migration_ms, 3),
        "resource_penalty_ms": round(resource_penalty_ms, 3),
        "instability_penalty_ms": round(instability_penalty_ms, 3),
        "used_exec_fallback": used_exec_fallback,
        "used_migration_fallback": used_migration_fallback,
        "legacy_compute_delay": round(legacy["compute_delay"], 3),
        "legacy_transfer_cost": round(legacy["transfer_cost"], 3),
        "legacy_memory_penalty": round(legacy["memory_penalty"], 3),
        "legacy_overload_penalty": round(legacy["overload_penalty"], 3),
    }


def decide_stage_placement(
    workflow_id: str,
    stage_id: str,
    node_profiles: list[NodeProfile] | list[dict],
    node_states: list[NodeState] | list[dict],
    stage_metadata: StageMetadata | dict,
    current_placement: str | None = None,
    workflow_type: str | None = None,
    stage_cost_stats: list[StageCostStats] | list[dict] | None = None,
    migration_cost_stats: list[MigrationCostStats] | list[dict] | None = None,
) -> PlacementDecision:
    profiles = [item if isinstance(item, NodeProfile) else NodeProfile(**item) for item in node_profiles]
    normalized_states = [
        item if isinstance(item, NodeState) else NodeState(**item) for item in node_states
    ]
    states = {item.hostname: item for item in normalized_states}
    stage = stage_metadata if isinstance(stage_metadata, StageMetadata) else StageMetadata(**stage_metadata)
    stage_cost_map = _to_stage_cost_map(stage_cost_stats)
    migration_cost_map = _to_migration_cost_map(migration_cost_stats)

    eligible: list[tuple[NodeProfile, NodeState, dict[str, float | int | bool | str | None]]] = []
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

        candidate = _evaluate_candidate(
            profile=profile,
            state=state,
            stage=stage,
            workflow_type=workflow_type,
            current_placement=current_placement,
            stage_cost_stats=stage_cost_map.get((stage.stage_type, profile.hostname)),
            migration_cost_stats=migration_cost_map.get(
                (stage.stage_type, current_placement or "", profile.hostname)
            ),
        )
        eligible.append((profile, state, candidate))

    if not eligible:
        cloud_profile = next((profile for profile in profiles if profile.node_type == "cloud_server"), None)
        if cloud_profile and "heavy inference prefers server" in " | ".join(rejection_reasons):
            return PlacementDecision(
                workflow_id=workflow_id,
                stage_id=stage_id,
                target_node=cloud_profile.hostname,
                decision_reason="fallback offload to cloud server",
                action_type="offload_to_cloud",
                score_breakdown={"selected_policy": "fallback_cloud_server"},
            )
        return PlacementDecision(
            workflow_id=workflow_id,
            stage_id=stage_id,
            target_node=None,
            decision_reason="; ".join(rejection_reasons) or "no eligible nodes",
            action_type="reject",
            score_breakdown={"selected_policy": "reject_no_eligible_node"},
        )

    eligible.sort(key=lambda item: float(item[2]["expected_cost_ms"]))
    best_profile, _, best_candidate = eligible[0]
    current_entry = next((item for item in eligible if item[0].hostname == current_placement), None)

    if current_entry is None:
        selected_policy = "initial_lowest_cost" if current_placement is None else "current_ineligible"
        action_type = _action_type_for_target(best_profile, current_placement)
        return PlacementDecision(
            workflow_id=workflow_id,
            stage_id=stage_id,
            target_node=best_profile.hostname,
            decision_reason=f"selected {best_profile.hostname} with lowest expected cost",
            action_type=action_type,
            score_breakdown={
                **best_candidate,
                "expected_keep_cost_ms": None,
                "expected_target_cost_ms": best_candidate["expected_cost_ms"],
                "net_gain_ms": None,
                "decision_margin_ms": None,
                "selected_policy": selected_policy,
            },
        )

    current_profile, current_state, current_candidate = current_entry
    current_stage_stats = stage_cost_map.get((stage.stage_type, current_profile.hostname))
    keep_cost = float(current_candidate["expected_cost_ms"])
    target_cost = float(best_candidate["expected_cost_ms"])
    net_gain = keep_cost - target_cost
    decision_margin = _decision_margin_ms(current_state, current_stage_stats)

    if best_profile.hostname == current_profile.hostname:
        return PlacementDecision(
            workflow_id=workflow_id,
            stage_id=stage_id,
            target_node=current_profile.hostname,
            decision_reason=f"kept {current_profile.hostname}; current node remains lowest expected cost",
            action_type="keep",
            score_breakdown={
                **current_candidate,
                "expected_keep_cost_ms": keep_cost,
                "expected_target_cost_ms": target_cost,
                "net_gain_ms": round(net_gain, 3),
                "decision_margin_ms": round(decision_margin, 3),
                "selected_policy": "selective_keep_best_node",
            },
        )

    if net_gain < decision_margin:
        return PlacementDecision(
            workflow_id=workflow_id,
            stage_id=stage_id,
            target_node=current_profile.hostname,
            decision_reason=(
                f"kept {current_profile.hostname}; predicted gain {round(net_gain, 3)} ms "
                f"below margin {round(decision_margin, 3)} ms"
            ),
            action_type="keep",
            score_breakdown={
                **best_candidate,
                "expected_keep_cost_ms": keep_cost,
                "expected_target_cost_ms": target_cost,
                "net_gain_ms": round(net_gain, 3),
                "decision_margin_ms": round(decision_margin, 3),
                "selected_policy": "selective_keep_below_margin",
            },
        )

    action_type = _action_type_for_target(best_profile, current_placement)
    return PlacementDecision(
        workflow_id=workflow_id,
        stage_id=stage_id,
        target_node=best_profile.hostname,
        decision_reason=(
            f"selected {best_profile.hostname}; predicted gain {round(net_gain, 3)} ms "
            f"exceeds margin {round(decision_margin, 3)} ms"
        ),
        action_type=action_type,
        score_breakdown={
            **best_candidate,
            "expected_keep_cost_ms": keep_cost,
            "expected_target_cost_ms": target_cost,
            "net_gain_ms": round(net_gain, 3),
            "decision_margin_ms": round(decision_margin, 3),
            "selected_policy": "selective_migrate_above_margin",
        },
    )


def replan_workflow(
    workflow_id: str,
    stages: list[dict],
    node_profiles: list[NodeProfile] | list[dict],
    node_states: list[NodeState] | list[dict],
    current_placement: dict[str, str] | None = None,
    workflow_type: str | None = None,
    stage_cost_stats: list[StageCostStats] | list[dict] | None = None,
    migration_cost_stats: list[MigrationCostStats] | list[dict] | None = None,
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
            stage_cost_stats=stage_cost_stats,
            migration_cost_stats=migration_cost_stats,
        )
        decisions.append(decision)
    return decisions
