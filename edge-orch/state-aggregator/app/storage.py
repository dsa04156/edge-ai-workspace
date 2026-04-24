from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from threading import Lock

from .models import (
    MigrationCostStats,
    MigrationObservation,
    NodeState,
    StageCostStats,
    StageObservation,
    WorkflowEvent,
    WorkflowState,
)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_stage_observation(payload: dict) -> StageObservation:
    payload = dict(payload)
    payload["started_at"] = _parse_datetime(payload["started_at"])
    payload["completed_at"] = _parse_datetime(payload["completed_at"])
    return StageObservation(**payload)


def _to_migration_observation(payload: dict) -> MigrationObservation:
    payload = dict(payload)
    payload["decided_at"] = _parse_datetime(payload["decided_at"])
    payload["started_at"] = _parse_datetime(payload["started_at"])
    return MigrationObservation(**payload)


class StateStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.node_log = self.data_dir / "node_state.jsonl"
        self.workflow_log = self.data_dir / "workflow_event.jsonl"
        self.stage_observation_log = self.data_dir / "stage_observation.jsonl"
        self.migration_observation_log = self.data_dir / "migration_observation.jsonl"
        self.nodes: dict[str, NodeState] = {}
        self.workflows: dict[str, WorkflowState] = {}
        self.stage_cost_stats: dict[tuple[str, str], StageCostStats] = {}
        self.migration_cost_stats: dict[tuple[str, str, str], MigrationCostStats] = {}
        self._pending_stage_starts: dict[tuple[str, str], WorkflowEvent] = {}
        self._pending_stage_jobs: dict[tuple[str, str], WorkflowEvent] = {}
        self._pending_migrations: dict[tuple[str, str], WorkflowEvent] = {}
        self._stage_observations: list[StageObservation] = []
        self._migration_observations: list[MigrationObservation] = []
        self._lock = Lock()
        self._load_observations()

    def upsert_node_state(self, node_state: NodeState) -> None:
        with self._lock:
            self.nodes[node_state.hostname] = node_state
            self._append_jsonl(self.node_log, node_state.model_dump(mode="json"))

    def record_workflow_event(self, event: WorkflowEvent, workflow_state: WorkflowState) -> None:
        with self._lock:
            self.workflows[workflow_state.workflow_id] = workflow_state
            self._append_jsonl(self.workflow_log, event.model_dump(mode="json"))
            self._process_workflow_event(event)

    def get_node_states(self) -> list[NodeState]:
        with self._lock:
            return list(self.nodes.values())

    def get_workflow_states(self) -> list[WorkflowState]:
        with self._lock:
            return list(self.workflows.values())

    def get_stage_cost_stats(self) -> list[StageCostStats]:
        with self._lock:
            return list(self.stage_cost_stats.values())

    def get_migration_cost_stats(self) -> list[MigrationCostStats]:
        with self._lock:
            return list(self.migration_cost_stats.values())

    def _process_workflow_event(self, event: WorkflowEvent) -> None:
        key = (event.workflow_id, event.stage_id)

        if event.event_type == "stage_job_created":
            self._pending_stage_jobs[key] = event
            return

        if event.event_type == "migration_event":
            self._pending_migrations[key] = event
            return

        if event.event_type == "stage_start":
            self._pending_stage_starts[key] = event
            pending_migration = self._pending_migrations.pop(key, None)
            if (
                pending_migration is not None
                and pending_migration.to_node
                and event.assigned_node == pending_migration.to_node
            ):
                observation = MigrationObservation(
                    workflow_id=event.workflow_id,
                    stage_id=event.stage_id,
                    stage_type=event.stage_type,
                    from_node=pending_migration.from_node or "unknown",
                    to_node=pending_migration.to_node,
                    decided_at=pending_migration.timestamp,
                    started_at=event.timestamp,
                    migration_time_ms=max(
                        0,
                        int((event.timestamp - pending_migration.timestamp).total_seconds() * 1000),
                    ),
                )
                self._migration_observations.append(observation)
                self._append_jsonl(
                    self.migration_observation_log,
                    observation.model_dump(mode="json"),
                )
                self._rebuild_cost_stats()
            return

        if event.event_type == "stage_end":
            stage_start = self._pending_stage_starts.pop(key, None)
            if stage_start is None:
                return
            stage_job = self._pending_stage_jobs.pop(key, None)
            warmup_ms = None
            if stage_job is not None:
                warmup_ms = max(
                    0,
                    int((stage_start.timestamp - stage_job.timestamp).total_seconds() * 1000),
                )
            observation = StageObservation(
                workflow_id=event.workflow_id,
                stage_id=event.stage_id,
                stage_type=event.stage_type or stage_start.stage_type,
                assigned_node=event.assigned_node or stage_start.assigned_node,
                started_at=stage_start.timestamp,
                completed_at=event.timestamp,
                observed_latency_ms=max(
                    0,
                    int((event.timestamp - stage_start.timestamp).total_seconds() * 1000),
                ),
                queue_wait_ms=stage_start.queue_wait_ms,
                transfer_time_ms=event.transfer_time_ms,
                warmup_ms=warmup_ms,
                action_type=event.action_type or stage_start.action_type,
                from_node=event.from_node or stage_start.from_node,
                to_node=event.to_node or stage_start.to_node,
            )
            self._stage_observations.append(observation)
            self._append_jsonl(
                self.stage_observation_log,
                observation.model_dump(mode="json"),
            )
            self._rebuild_cost_stats()

    def _load_observations(self) -> None:
        self._stage_observations = [
            _to_stage_observation(item) for item in self._read_jsonl(self.stage_observation_log)
        ]
        self._migration_observations = [
            _to_migration_observation(item)
            for item in self._read_jsonl(self.migration_observation_log)
        ]
        self._rebuild_cost_stats()

    def _rebuild_cost_stats(self) -> None:
        stage_grouped: dict[tuple[str, str], list[StageObservation]] = defaultdict(list)
        migration_grouped: dict[tuple[str, str, str], list[MigrationObservation]] = defaultdict(list)
        recent_migration_by_stage: dict[str, int] = defaultdict(int)
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(hours=1)

        for item in self._stage_observations:
            if item.stage_type and item.assigned_node:
                stage_grouped[(item.stage_type, item.assigned_node)].append(item)

        for item in self._migration_observations:
            if item.stage_type:
                migration_grouped[(item.stage_type, item.from_node, item.to_node)].append(item)
                if item.decided_at >= recent_cutoff:
                    recent_migration_by_stage[item.stage_type] += 1

        stage_cost_stats: dict[tuple[str, str], StageCostStats] = {}
        for key, items in stage_grouped.items():
            stage_type, node = key
            exec_values = [item.observed_latency_ms for item in items]
            queue_values = [item.queue_wait_ms or 0 for item in items]
            warmup_values = [item.warmup_ms or 0 for item in items]
            ema = 0.0
            for value in exec_values:
                ema = value if ema == 0.0 else (0.5 * value) + (0.5 * ema)
            recent_count = recent_migration_by_stage[stage_type]
            if recent_count >= 3:
                stability = "unstable"
            elif recent_count >= 1:
                stability = "moving"
            else:
                stability = "stable"
            stage_cost_stats[key] = StageCostStats(
                stage_type=stage_type,
                node=node,
                sample_count=len(items),
                exec_median_ms=float(median(exec_values)),
                exec_ema_ms=float(round(ema, 3)),
                queue_median_ms=float(median(queue_values)),
                warmup_median_ms=float(median(warmup_values)),
                recent_migration_count_last_hour=recent_count,
                placement_stability=stability,
            )

        migration_cost_stats: dict[tuple[str, str, str], MigrationCostStats] = {}
        for key, items in migration_grouped.items():
            stage_type, from_node, to_node = key
            values = [item.migration_time_ms for item in items]
            ema = 0.0
            for value in values:
                ema = value if ema == 0.0 else (0.5 * value) + (0.5 * ema)
            migration_cost_stats[key] = MigrationCostStats(
                stage_type=stage_type,
                from_node=from_node,
                to_node=to_node,
                sample_count=len(items),
                migration_median_ms=float(median(values)),
                migration_ema_ms=float(round(ema, 3)),
            )

        self.stage_cost_stats = stage_cost_stats
        self.migration_cost_stats = migration_cost_stats

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True))
            handle.write("\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows: list[dict] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                content = line.strip()
                if not content:
                    continue
                rows.append(json.loads(content))
        return rows
