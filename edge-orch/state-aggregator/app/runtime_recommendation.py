from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field

from .models import PlacementSelectionResult
from .runtime_recommendation_models import (
    RuntimeRecommendationAction,
    RuntimeRecommendationDecision,
    RuntimeRecommendationDwell,
    RuntimeRecommendationHistoryEntry,
    RuntimeRecommendationMetrics,
    RuntimeRecommendationPolicy,
    RuntimeRecommendationState,
    RuntimeRecommendationTarget,
)


PlacementProvider = Callable[[set[str]], Awaitable[PlacementSelectionResult]]


@dataclass(frozen=True)
class RuntimeRecommendationSignals:
    service_id: str
    namespace: str
    workload_name: str
    current_nodes: list[str]
    workload_kind: str = "Deployment"
    workload_observed: bool = False
    workload_exists: bool = False
    desired_replicas: int = 0
    ready_replicas: int = 0
    pod_restart_count: int = 0
    pod_failure: bool = False
    node_failure: bool = False
    node_observed: bool = True
    input_state: str = "unknown"
    input_valid: bool = False
    model_state: str = "unknown"
    model_ready: bool = False
    performance_valid: bool = False
    resource_valid: bool = False
    cpu_ratio: float | None = None
    memory_ratio: float | None = None
    latency_p95_ms: float | None = None
    backlog: int | None = None
    throughput_per_second: float | None = None
    observation_source: str = "unavailable"
    observation_scope: str = "unknown"


@dataclass(frozen=True)
class RuntimeWorkloadSnapshot:
    namespace: str
    kind: str
    name: str
    observed: bool
    exists: bool
    desired_replicas: int = 0
    ready_replicas: int = 0
    current_nodes: tuple[str, ...] = ()
    pod_restart_count: int = 0
    pod_failure: bool = False
    reason_codes: tuple[str, ...] = ()
    placement_profile: dict | None = None


class _RecommendationMemory(BaseModel):
    service_id: str
    state: RuntimeRecommendationState = "NORMAL"
    resource_active: bool = False
    resource_since: datetime | None = None
    resource_recovery_since: datetime | None = None
    service_active: bool = False
    service_since: datetime | None = None
    service_recovery_since: datetime | None = None
    failure_active: bool = False
    failure_since: datetime | None = None
    failure_recovery_since: datetime | None = None
    last_recommendation_at: datetime | None = None
    history_fingerprint: str | None = None
    latest: RuntimeRecommendationDecision | None = None


class RuntimeRecommendationStore:
    def __init__(self, database_path: Path, *, history_limit: int = 1000) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_limit = max(1, history_limit)
        self._lock = Lock()
        self._initialize()

    def load(self, service_id: str) -> _RecommendationMemory:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM runtime_recommendation_state WHERE service_id = ?",
                (service_id,),
            ).fetchone()
        if row is None:
            return _RecommendationMemory(service_id=service_id)
        return _RecommendationMemory.model_validate_json(row[0])

    def save(
        self,
        memory: _RecommendationMemory,
        decision: RuntimeRecommendationDecision,
    ) -> None:
        fingerprint = _history_fingerprint(decision)
        previous_state = memory.latest.state if memory.latest is not None else None
        record_history = fingerprint != memory.history_fingerprint
        memory.latest = decision
        memory.state = decision.state
        memory.history_fingerprint = fingerprint
        payload = memory.model_dump_json(by_alias=True)
        decision_payload = decision.model_dump_json(by_alias=True)
        recorded_at = decision.observed_at.isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_recommendation_state(service_id, updated_at, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (memory.service_id, recorded_at, payload),
            )
            if record_history:
                connection.execute(
                    """
                    INSERT INTO runtime_recommendation_history(
                        service_id, recorded_at, previous_state, state, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        memory.service_id,
                        recorded_at,
                        previous_state,
                        decision.state,
                        decision_payload,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM runtime_recommendation_history
                    WHERE service_id = ? AND id NOT IN (
                        SELECT id FROM runtime_recommendation_history
                        WHERE service_id = ? ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (memory.service_id, memory.service_id, self.history_limit),
                )
            connection.commit()

    def latest(self, service_id: str) -> RuntimeRecommendationDecision | None:
        return self.load(service_id).latest

    def latest_all(self) -> list[RuntimeRecommendationDecision]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM runtime_recommendation_state ORDER BY service_id"
            ).fetchall()
        latest = []
        for row in rows:
            memory = _RecommendationMemory.model_validate_json(row[0])
            if memory.latest is not None:
                latest.append(memory.latest)
        return latest

    def history(
        self,
        service_id: str,
        *,
        limit: int = 100,
    ) -> list[RuntimeRecommendationHistoryEntry]:
        safe_limit = min(max(1, limit), 500)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, recorded_at, previous_state, state, payload_json
                FROM runtime_recommendation_history
                WHERE service_id = ? ORDER BY id DESC LIMIT ?
                """,
                (service_id, safe_limit),
            ).fetchall()
        return [
            RuntimeRecommendationHistoryEntry(
                sequence=row[0],
                recorded_at=_utc(datetime.fromisoformat(row[1])),
                previous_state=row[2],
                state=row[3],
                decision=RuntimeRecommendationDecision.model_validate_json(row[4]),
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_recommendation_state (
                    service_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_recommendation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    previous_state TEXT,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_recommendation_history_service
                ON runtime_recommendation_history(service_id, id DESC)
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection


class RuntimeRecommendationEngine:
    def __init__(self, store: RuntimeRecommendationStore) -> None:
        self.store = store

    async def evaluate(
        self,
        signals: RuntimeRecommendationSignals,
        policy: RuntimeRecommendationPolicy,
        placement_provider: PlacementProvider,
        *,
        now: datetime | None = None,
    ) -> RuntimeRecommendationDecision:
        observed_at = _utc(now or datetime.now(timezone.utc))
        memory = self.store.load(signals.service_id)
        previous_state = memory.state
        blockers = _blockers(signals)
        if blockers:
            _reset_latches(memory)
            decision = _decision(
                signals,
                policy,
                memory,
                state="BLOCKED",
                previous_state=previous_state,
                reason_codes=blockers,
                now=observed_at,
            )
            self.store.save(memory, decision)
            return decision

        resource_high = _resource_high(signals, policy)
        resource_recovered = _resource_recovered(signals, policy)
        service_high = _service_high(signals, policy)
        service_recovered = _service_recovered(signals, policy)
        failure_high = _runtime_failure(signals, policy)

        (
            memory.resource_active,
            memory.resource_since,
            memory.resource_recovery_since,
            resource_recovering,
        ) = _update_latch(
            memory.resource_active,
            memory.resource_since,
            memory.resource_recovery_since,
            high=resource_high,
            recovered=resource_recovered,
            recovery_seconds=policy.recovery_dwell_seconds,
            now=observed_at,
        )
        (
            memory.service_active,
            memory.service_since,
            memory.service_recovery_since,
            service_recovering,
        ) = _update_latch(
            memory.service_active,
            memory.service_since,
            memory.service_recovery_since,
            high=service_high,
            recovered=service_recovered,
            recovery_seconds=policy.recovery_dwell_seconds,
            now=observed_at,
        )
        (
            memory.failure_active,
            memory.failure_since,
            memory.failure_recovery_since,
            failure_recovering,
        ) = _update_latch(
            memory.failure_active,
            memory.failure_since,
            memory.failure_recovery_since,
            high=failure_high,
            recovered=not failure_high,
            recovery_seconds=policy.recovery_dwell_seconds,
            now=observed_at,
        )

        failure_elapsed = _elapsed(memory.failure_since, observed_at)
        resource_elapsed = _elapsed(memory.resource_since, observed_at)
        service_elapsed = _elapsed(memory.service_since, observed_at)
        if resource_recovering or service_recovering or failure_recovering:
            decision = _decision(
                signals,
                policy,
                memory,
                state="OBSERVING",
                previous_state=previous_state,
                reason_codes=["recovery_dwell_active"],
                now=observed_at,
            )
            self.store.save(memory, decision)
            return decision
        desired_action: RuntimeRecommendationAction = "none"
        reason_codes: list[str] = []
        if (
            memory.failure_active
            and failure_elapsed >= policy.replacement_dwell_seconds
        ):
            desired_action = "replace"
            reason_codes = ["sustained_runtime_failure", *_failure_reasons(signals, policy)]
        elif (
            memory.resource_active
            and memory.service_active
            and resource_elapsed >= policy.resource_dwell_seconds
            and service_elapsed >= policy.service_dwell_seconds
        ):
            desired_action = "augment"
            reason_codes = [
                "sustained_resource_and_service_pressure",
                *_pressure_reasons(signals, policy),
            ]
        elif memory.failure_active or memory.resource_active or memory.service_active:
            if memory.failure_active:
                reason_codes.append("runtime_failure_dwell_active")
                reason_codes.extend(_failure_reasons(signals, policy))
            if memory.resource_active:
                reason_codes.append("resource_pressure_dwell_active")
                reason_codes.extend(_resource_reasons(signals, policy))
            if memory.service_active:
                reason_codes.append("service_pressure_dwell_active")
                reason_codes.extend(_service_reasons(signals, policy))
            if resource_recovering or service_recovering or failure_recovering:
                reason_codes.append("recovery_dwell_active")
            decision = _decision(
                signals,
                policy,
                memory,
                state="OBSERVING",
                previous_state=previous_state,
                reason_codes=_unique(reason_codes),
                now=observed_at,
            )
            self.store.save(memory, decision)
            return decision
        else:
            decision = _decision(
                signals,
                policy,
                memory,
                state="NORMAL",
                previous_state=previous_state,
                reason_codes=["within_operating_envelope"],
                now=observed_at,
            )
            self.store.save(memory, decision)
            return decision

        recommended_state: RuntimeRecommendationState = (
            "REPLACE_RECOMMENDED"
            if desired_action == "replace"
            else "AUGMENT_RECOMMENDED"
        )
        continuing = previous_state == recommended_state
        cooldown_remaining = _cooldown_remaining(memory, policy, observed_at)
        if not continuing and cooldown_remaining > 0:
            decision = _decision(
                signals,
                policy,
                memory,
                state="OBSERVING",
                previous_state=previous_state,
                reason_codes=["recommendation_cooldown_active", *reason_codes],
                now=observed_at,
                cooldown_remaining=cooldown_remaining,
            )
            self.store.save(memory, decision)
            return decision

        placement = await placement_provider(set(signals.current_nodes))
        recommendation = RuntimeRecommendationTarget(
            action=desired_action,
            selected_node=placement.selected_node,
            selected_score=placement.selected_score,
        )
        if placement.status != "selected" or placement.selected_node is None:
            decision = _decision(
                signals,
                policy,
                memory,
                state="BLOCKED",
                previous_state=previous_state,
                reason_codes=[
                    "no_eligible_alternative_node",
                    *reason_codes,
                    *placement.reason_codes,
                ],
                now=observed_at,
                recommendation=recommendation,
                placement=placement,
            )
            self.store.save(memory, decision)
            return decision

        if not continuing:
            memory.last_recommendation_at = observed_at
        decision = _decision(
            signals,
            policy,
            memory,
            state=recommended_state,
            previous_state=previous_state,
            reason_codes=_unique(reason_codes),
            now=observed_at,
            recommendation=recommendation,
            placement=placement,
        )
        self.store.save(memory, decision)
        return decision


def _decision(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
    memory: _RecommendationMemory,
    *,
    state: RuntimeRecommendationState,
    previous_state: RuntimeRecommendationState,
    reason_codes: list[str],
    now: datetime,
    cooldown_remaining: int = 0,
    recommendation: RuntimeRecommendationTarget | None = None,
    placement: PlacementSelectionResult | None = None,
) -> RuntimeRecommendationDecision:
    recovery_starts = [
        value
        for value in (
            memory.resource_recovery_since,
            memory.service_recovery_since,
            memory.failure_recovery_since,
        )
        if value is not None
    ]
    return RuntimeRecommendationDecision(
        service_id=signals.service_id,
        namespace=signals.namespace,
        workload_kind=signals.workload_kind,
        workload_name=signals.workload_name,
        current_nodes=sorted(set(signals.current_nodes)),
        state=state,
        previous_state=previous_state,
        reason_codes=_unique(reason_codes),
        metrics=RuntimeRecommendationMetrics(
            cpu_ratio=signals.cpu_ratio,
            memory_ratio=signals.memory_ratio,
            latency_p95_ms=signals.latency_p95_ms,
            backlog=signals.backlog,
            throughput_per_second=signals.throughput_per_second,
            desired_replicas=signals.desired_replicas,
            ready_replicas=signals.ready_replicas,
            pod_restart_count=signals.pod_restart_count,
        ),
        dwell=RuntimeRecommendationDwell(
            resource_pressure_seconds=_elapsed(memory.resource_since, now),
            resource_required_seconds=policy.resource_dwell_seconds,
            service_pressure_seconds=_elapsed(memory.service_since, now),
            service_required_seconds=policy.service_dwell_seconds,
            runtime_failure_seconds=_elapsed(memory.failure_since, now),
            replacement_required_seconds=policy.replacement_dwell_seconds,
            recovery_seconds=(
                max(_elapsed(value, now) for value in recovery_starts)
                if recovery_starts
                else 0
            ),
            recovery_required_seconds=policy.recovery_dwell_seconds,
        ),
        cooldown_remaining_seconds=cooldown_remaining,
        recommendation=recommendation or RuntimeRecommendationTarget(),
        placement=placement,
        observation_source=signals.observation_source,
        observation_scope=signals.observation_scope,
        observed_at=now,
    )


def _blockers(signals: RuntimeRecommendationSignals) -> list[str]:
    blockers: list[str] = []
    if not signals.workload_observed:
        blockers.append("runtime_workload_observation_unavailable")
    elif not signals.workload_exists:
        blockers.append("runtime_workload_not_found")
    if not signals.current_nodes:
        blockers.append("current_node_unavailable")
    if not signals.node_observed:
        blockers.append("node_observation_unavailable")
    if not signals.input_valid:
        blockers.append(
            {
                "stale": "input_stale",
                "error": "input_error",
            }.get(signals.input_state, "input_unavailable")
        )
    if not signals.model_ready:
        blockers.append("model_not_ready")
    if not signals.performance_valid:
        blockers.append("service_performance_unavailable")
    if not signals.resource_valid:
        blockers.append("resource_observation_unavailable")
    return _unique(blockers)


def _runtime_failure(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> bool:
    return bool(
        signals.node_failure
        or signals.pod_failure
        or signals.ready_replicas < signals.desired_replicas
        or (
            signals.pod_restart_count >= policy.max_restart_count
            and signals.ready_replicas < signals.desired_replicas
        )
    )


def _resource_high(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> bool:
    return bool(
        (signals.cpu_ratio is not None and signals.cpu_ratio >= policy.cpu_high_ratio)
        or (
            signals.memory_ratio is not None
            and signals.memory_ratio >= policy.memory_high_ratio
        )
    )


def _resource_recovered(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> bool:
    return bool(
        signals.cpu_ratio is not None
        and signals.memory_ratio is not None
        and signals.cpu_ratio <= policy.cpu_recovery_ratio
        and signals.memory_ratio <= policy.memory_recovery_ratio
    )


def _service_high(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> bool:
    return bool(
        (
            signals.latency_p95_ms is not None
            and signals.latency_p95_ms >= policy.latency_high_ms
        )
        or (signals.backlog is not None and signals.backlog >= policy.backlog_high)
        or (
            signals.throughput_per_second is not None
            and signals.throughput_per_second < policy.throughput_floor_per_second
        )
    )


def _service_recovered(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> bool:
    return bool(
        signals.latency_p95_ms is not None
        and signals.backlog is not None
        and signals.throughput_per_second is not None
        and signals.latency_p95_ms <= policy.latency_recovery_ms
        and signals.backlog <= policy.backlog_recovery
        and signals.throughput_per_second
        >= policy.throughput_recovery_per_second
    )


def _update_latch(
    active: bool,
    since: datetime | None,
    recovery_since: datetime | None,
    *,
    high: bool,
    recovered: bool,
    recovery_seconds: int,
    now: datetime,
) -> tuple[bool, datetime | None, datetime | None, bool]:
    if high:
        return True, since or now, None, False
    if not active:
        return False, None, None, False
    if not recovered:
        return True, since, None, False
    recovery_start = recovery_since or now
    if _elapsed(recovery_start, now) >= recovery_seconds:
        return False, None, None, False
    return True, since, recovery_start, True


def _reset_latches(memory: _RecommendationMemory) -> None:
    memory.resource_active = False
    memory.resource_since = None
    memory.resource_recovery_since = None
    memory.service_active = False
    memory.service_since = None
    memory.service_recovery_since = None
    memory.failure_active = False
    memory.failure_since = None
    memory.failure_recovery_since = None


def _cooldown_remaining(
    memory: _RecommendationMemory,
    policy: RuntimeRecommendationPolicy,
    now: datetime,
) -> int:
    if memory.last_recommendation_at is None:
        return 0
    elapsed = _elapsed(memory.last_recommendation_at, now)
    return max(0, policy.cooldown_seconds - elapsed)


def _resource_reasons(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> list[str]:
    reasons = []
    if signals.cpu_ratio is not None and signals.cpu_ratio >= policy.cpu_high_ratio:
        reasons.append("cpu_pressure_high")
    if (
        signals.memory_ratio is not None
        and signals.memory_ratio >= policy.memory_high_ratio
    ):
        reasons.append("memory_pressure_high")
    return reasons


def _service_reasons(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> list[str]:
    reasons = []
    if (
        signals.latency_p95_ms is not None
        and signals.latency_p95_ms >= policy.latency_high_ms
    ):
        reasons.append("latency_slo_violated")
    if signals.backlog is not None and signals.backlog >= policy.backlog_high:
        reasons.append("backlog_pressure_high")
    if (
        signals.throughput_per_second is not None
        and signals.throughput_per_second < policy.throughput_floor_per_second
    ):
        reasons.append("throughput_below_floor")
    return reasons


def _pressure_reasons(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> list[str]:
    return _unique(
        [*_resource_reasons(signals, policy), *_service_reasons(signals, policy)]
    )


def _failure_reasons(
    signals: RuntimeRecommendationSignals,
    policy: RuntimeRecommendationPolicy,
) -> list[str]:
    reasons = []
    if signals.node_failure:
        reasons.append("current_node_unhealthy")
    if signals.pod_failure:
        reasons.append("pod_runtime_failure")
    if signals.ready_replicas < signals.desired_replicas:
        reasons.append("workload_ready_replicas_insufficient")
    if (
        signals.pod_restart_count >= policy.max_restart_count
        and signals.ready_replicas < signals.desired_replicas
    ):
        reasons.append("pod_restart_threshold_exceeded")
    return reasons


def _history_fingerprint(decision: RuntimeRecommendationDecision) -> str:
    candidates = []
    if decision.placement is not None:
        candidates = [
            {
                "node": item.node,
                "eligible": item.eligible,
                "reasonCodes": item.reason_codes,
            }
            for item in decision.placement.candidates
        ]
    payload = {
        "state": decision.state,
        "reasons": decision.reason_codes,
        "action": decision.recommendation.action,
        "selectedNode": decision.recommendation.selected_node,
        "placementStatus": (
            decision.placement.status if decision.placement is not None else None
        ),
        "candidates": candidates,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _elapsed(start: datetime | None, now: datetime) -> int:
    return max(0, int((now - _utc(start)).total_seconds())) if start else 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
