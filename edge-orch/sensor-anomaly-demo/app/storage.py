from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

from .models import AlertTransition, LatestObservation, StorageStatus

SCHEMA_VERSION = 1


class ResultStore:
    """Application-owned derived-result store.

    It does not write to EdgeX Core Data tables. Raw sensor inventory and
    telemetry remain authoritative in EdgeX; this database only persists the
    anomaly service's derived observations and alert transitions.
    """

    def __init__(self, path: str, retention_rows: int) -> None:
        if retention_rows < 1:
            raise ValueError("retention_rows must be positive")
        self.path = path
        self.retention_rows = retention_rows
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in {0, SCHEMA_VERSION}:
                raise RuntimeError(
                    f"unsupported result database schema version {current}"
                )
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inference_results (
                    origin INTEGER PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    anomaly INTEGER NOT NULL CHECK (anomaly IN (0, 1)),
                    score REAL NOT NULL,
                    model_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_inference_results_anomaly_origin
                    ON inference_results(anomaly, origin DESC);

                CREATE TABLE IF NOT EXISTS alert_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL,
                    transition TEXT NOT NULL CHECK (transition IN ('opened', 'cleared')),
                    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
                    origin INTEGER NOT NULL,
                    observed_at TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    model_version TEXT NOT NULL,
                    message TEXT NOT NULL,
                    UNIQUE(alert_id, transition, origin)
                );
                CREATE INDEX IF NOT EXISTS idx_alert_transitions_origin
                    ON alert_transitions(origin DESC);

                CREATE TABLE IF NOT EXISTS service_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def record_result(
        self,
        observation: LatestObservation,
        *,
        asset_id: str,
    ) -> AlertTransition | None:
        transitions = self.record_results([observation], asset_id=asset_id)
        return transitions[0] if transitions else None

    def record_results(
        self,
        observations: list[LatestObservation],
        *,
        asset_id: str,
    ) -> list[AlertTransition]:
        if not observations:
            return []
        transitions: list[AlertTransition] = []
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                for observation in observations:
                    payload = observation.model_dump_json(by_alias=True)
                    inserted = connection.execute(
                        """
                        INSERT OR IGNORE INTO inference_results(
                            origin, observed_at, anomaly, score,
                            model_version, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            observation.origin,
                            observation.observed_at.isoformat(),
                            int(observation.anomaly),
                            observation.score,
                            observation.model_version,
                            payload,
                        ),
                    ).rowcount
                    if inserted == 0:
                        continue

                    current_status = self._state_value("alert_status") or "closed"
                    open_alert_id = self._state_value("open_alert_id")
                    transition: AlertTransition | None = None
                    if observation.anomaly and current_status != "open":
                        alert_id = self._alert_id(
                            asset_id,
                            observation.origin,
                            observation.model_version,
                        )
                        transition = AlertTransition(
                            alert_id=alert_id,
                            transition="opened",
                            status="open",
                            origin=observation.origin,
                            observed_at=observation.observed_at,
                            asset_id=asset_id,
                            score=observation.score,
                            model_version=observation.model_version,
                            message="펌프·모터 이상 점수가 임계 상태로 전환되었습니다.",
                        )
                        self._insert_alert(transition)
                        self._set_state("alert_status", "open")
                        self._set_state("open_alert_id", alert_id)
                    elif (
                        not observation.anomaly
                        and current_status == "open"
                        and open_alert_id
                    ):
                        transition = AlertTransition(
                            alert_id=open_alert_id,
                            transition="cleared",
                            status="closed",
                            origin=observation.origin,
                            observed_at=observation.observed_at,
                            asset_id=asset_id,
                            score=observation.score,
                            model_version=observation.model_version,
                            message="펌프·모터 이상 상태가 정상 범위로 복귀했습니다.",
                        )
                        self._insert_alert(transition)
                        self._set_state("alert_status", "closed")
                        self._set_state("open_alert_id", "")
                    if transition is not None:
                        transitions.append(transition)

                connection.execute(
                    """
                    DELETE FROM inference_results
                    WHERE origin IN (
                        SELECT origin FROM inference_results
                        ORDER BY origin DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.retention_rows,),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return transitions

    def results(
        self,
        limit: int,
        *,
        anomaly: bool | None = None,
        from_origin: int | None = None,
        to_origin: int | None = None,
    ) -> list[LatestObservation]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be from 1 through 1000")
        clauses: list[str] = []
        values: list[int] = []
        if anomaly is not None:
            clauses.append("anomaly = ?")
            values.append(int(anomaly))
        if from_origin is not None:
            clauses.append("origin >= ?")
            values.append(from_origin)
        if to_origin is not None:
            clauses.append("origin <= ?")
            values.append(to_origin)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT payload_json FROM inference_results
                {where}
                ORDER BY origin DESC
                LIMIT ?
                """,
                (*values, limit),
            ).fetchall()
        return [
            LatestObservation.model_validate_json(row["payload_json"])
            for row in reversed(rows)
        ]

    def alerts(
        self,
        limit: int,
        *,
        status: str | None = None,
    ) -> list[AlertTransition]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be from 1 through 1000")
        if status not in {None, "open", "closed"}:
            raise ValueError("status must be open or closed")
        where = "WHERE status = ?" if status else ""
        parameters = (status, limit) if status else (limit,)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT alert_id, transition, status, origin, observed_at,
                       asset_id, score, model_version, message
                FROM alert_transitions
                {where}
                ORDER BY origin DESC, id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [AlertTransition.model_validate(dict(row)) for row in rows]

    def status(self) -> StorageStatus:
        with self._lock:
            result_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM inference_results"
                ).fetchone()[0]
            )
            alert_count = int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM alert_transitions"
                ).fetchone()[0]
            )
            open_count = 1 if self._state_value("alert_status") == "open" else 0
        return StorageStatus(
            durable=self.path != ":memory:",
            result_count=result_count,
            alert_event_count=alert_count,
            open_alert_count=open_count,
            retention_rows=self.retention_rows,
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _state_value(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM service_state WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row is not None else None

    def _set_state(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO service_state(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _insert_alert(self, transition: AlertTransition) -> None:
        self._connection.execute(
            """
            INSERT INTO alert_transitions(
                alert_id, transition, status, origin, observed_at,
                asset_id, score, model_version, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition.alert_id,
                transition.transition,
                transition.status,
                transition.origin,
                transition.observed_at.isoformat(),
                transition.asset_id,
                transition.score,
                transition.model_version,
                transition.message,
            ),
        )

    @staticmethod
    def _alert_id(asset_id: str, origin: int, model_version: str) -> str:
        digest = hashlib.sha256(
            f"{asset_id}|{origin}|{model_version}".encode()
        ).hexdigest()[:24]
        return f"pump-anomaly-{digest}"
