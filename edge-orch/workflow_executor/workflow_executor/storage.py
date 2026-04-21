from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .models import StageRunState, WorkflowRunState, WorkflowTransition


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowStateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    workflow_id TEXT PRIMARY KEY,
                    workflow_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stage_runs (
                    workflow_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    workflow_type TEXT NOT NULL,
                    stage_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_node TEXT,
                    job_name TEXT,
                    action_type TEXT,
                    decision_reason TEXT,
                    queue_wait_ms INTEGER,
                    exec_time_ms INTEGER,
                    transfer_time_ms INTEGER,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workflow_id, stage_id)
                );

                CREATE TABLE IF NOT EXISTS state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    stage_id TEXT,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def ensure_workflow(self, workflow_id: str, workflow_type: str) -> None:
        now = utc_now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (workflow_id, workflow_type, status, current_stage_id, created_at, updated_at)
                VALUES (?, ?, 'pending', NULL, ?, ?)
                ON CONFLICT(workflow_id) DO NOTHING
                """,
                (workflow_id, workflow_type, now, now),
            )

    def update_workflow_status(
        self,
        workflow_id: str,
        workflow_type: str,
        status: str,
        current_stage_id: str | None,
    ) -> None:
        now = utc_now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (workflow_id, workflow_type, status, current_stage_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    workflow_type=excluded.workflow_type,
                    status=excluded.status,
                    current_stage_id=excluded.current_stage_id,
                    updated_at=excluded.updated_at
                """,
                (workflow_id, workflow_type, status, current_stage_id, now, now),
            )

    def upsert_stage(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        stage_id: str,
        stage_type: str,
        status: str,
        assigned_node: str | None = None,
        job_name: str | None = None,
        action_type: str | None = None,
        decision_reason: str | None = None,
        queue_wait_ms: int | None = None,
        exec_time_ms: int | None = None,
        transfer_time_ms: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        now = utc_now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stage_runs (
                    workflow_id, stage_id, workflow_type, stage_type, status, assigned_node,
                    job_name, action_type, decision_reason, queue_wait_ms, exec_time_ms,
                    transfer_time_ms, started_at, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id, stage_id) DO UPDATE SET
                    workflow_type=excluded.workflow_type,
                    stage_type=excluded.stage_type,
                    status=excluded.status,
                    assigned_node=COALESCE(excluded.assigned_node, stage_runs.assigned_node),
                    job_name=COALESCE(excluded.job_name, stage_runs.job_name),
                    action_type=COALESCE(excluded.action_type, stage_runs.action_type),
                    decision_reason=COALESCE(excluded.decision_reason, stage_runs.decision_reason),
                    queue_wait_ms=COALESCE(excluded.queue_wait_ms, stage_runs.queue_wait_ms),
                    exec_time_ms=COALESCE(excluded.exec_time_ms, stage_runs.exec_time_ms),
                    transfer_time_ms=COALESCE(excluded.transfer_time_ms, stage_runs.transfer_time_ms),
                    started_at=COALESCE(excluded.started_at, stage_runs.started_at),
                    completed_at=COALESCE(excluded.completed_at, stage_runs.completed_at),
                    updated_at=excluded.updated_at
                """,
                (
                    workflow_id,
                    stage_id,
                    workflow_type,
                    stage_type,
                    status,
                    assigned_node,
                    job_name,
                    action_type,
                    decision_reason,
                    queue_wait_ms,
                    exec_time_ms,
                    transfer_time_ms,
                    started_at.isoformat() if started_at else None,
                    completed_at.isoformat() if completed_at else None,
                    now,
                ),
            )

    def append_transition(
        self,
        workflow_id: str,
        status: str,
        *,
        stage_id: str | None = None,
        details: dict[str, str | int | float | None] | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state_transitions (workflow_id, stage_id, status, details_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    stage_id,
                    status,
                    json.dumps(details or {}, ensure_ascii=True, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def get_stage_assignment(self, workflow_id: str, stage_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT assigned_node
                FROM stage_runs
                WHERE workflow_id = ? AND stage_id = ?
                """,
                (workflow_id, stage_id),
            ).fetchone()
        return row["assigned_node"] if row and row["assigned_node"] else None

    def get_workflow(self, workflow_id: str) -> WorkflowRunState | None:
        with self._lock, self._connect() as conn:
            workflow_row = conn.execute(
                """
                SELECT workflow_id, workflow_type, status, current_stage_id, created_at, updated_at
                FROM workflow_runs
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            ).fetchone()
            if workflow_row is None:
                return None

            stage_rows = conn.execute(
                """
                SELECT *
                FROM stage_runs
                WHERE workflow_id = ?
                ORDER BY updated_at ASC, stage_id ASC
                """,
                (workflow_id,),
            ).fetchall()
            transition_rows = conn.execute(
                """
                SELECT workflow_id, stage_id, status, details_json, created_at
                FROM state_transitions
                WHERE workflow_id = ?
                ORDER BY id ASC
                """,
                (workflow_id,),
            ).fetchall()

        return WorkflowRunState(
            workflow_id=workflow_row["workflow_id"],
            workflow_type=workflow_row["workflow_type"],
            status=workflow_row["status"],
            current_stage_id=workflow_row["current_stage_id"],
            created_at=datetime.fromisoformat(workflow_row["created_at"]),
            updated_at=datetime.fromisoformat(workflow_row["updated_at"]),
            stages=[
                StageRunState(
                    workflow_id=row["workflow_id"],
                    workflow_type=row["workflow_type"],
                    stage_id=row["stage_id"],
                    stage_type=row["stage_type"],
                    status=row["status"],
                    assigned_node=row["assigned_node"],
                    job_name=row["job_name"],
                    action_type=row["action_type"],
                    decision_reason=row["decision_reason"],
                    queue_wait_ms=row["queue_wait_ms"],
                    exec_time_ms=row["exec_time_ms"],
                    transfer_time_ms=row["transfer_time_ms"],
                    started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
                    completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in stage_rows
            ],
            transitions=[
                WorkflowTransition(
                    workflow_id=row["workflow_id"],
                    stage_id=row["stage_id"],
                    status=row["status"],
                    details=json.loads(row["details_json"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in transition_rows
            ],
        )

    def list_workflows(self) -> list[WorkflowRunState]:
        with self._lock, self._connect() as conn:
            ids = [
                row["workflow_id"]
                for row in conn.execute(
                    "SELECT workflow_id FROM workflow_runs ORDER BY updated_at DESC, workflow_id ASC"
                ).fetchall()
            ]
        return [workflow for workflow_id in ids if (workflow := self.get_workflow(workflow_id)) is not None]
