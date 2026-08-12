from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from .discovery_models import (
    CandidateRegistryDocument,
    DiscoveryAuditEvent,
    DiscoveryPlan,
    RegistrationRecord,
)


SCHEMA_VERSION = 1


class DiscoveryStoreError(RuntimeError):
    """Persistent discovery state could not be read or committed safely."""


class SQLiteDiscoveryStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
            timeout=10,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 10000")
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _migrate(self) -> None:
        with self._lock:
            version = int(
                self._connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if version > SCHEMA_VERSION:
                raise DiscoveryStoreError(
                    f"discovery database schema {version} is newer than supported"
                )
            if version == 0:
                self._connection.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE discovery_candidates (
                        candidate_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE discovery_nodes (
                        node_name TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE discovery_plans (
                        node_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE registration_sagas (
                        candidate_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE discovery_audit_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        candidate_id TEXT,
                        occurred_at TEXT NOT NULL,
                        payload TEXT NOT NULL
                    );
                    CREATE INDEX discovery_audit_candidate_idx
                    ON discovery_audit_events(candidate_id, sequence DESC);
                    CREATE TABLE discovery_idempotency (
                        scope TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        response_payload TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY(scope, request_id)
                    );
                    CREATE TABLE discovery_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    PRAGMA user_version = 1;
                    COMMIT;
                    """
                )

    def is_empty(self) -> bool:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM discovery_candidates)
                  + (SELECT COUNT(*) FROM discovery_nodes)
                """
            ).fetchone()
            return int(row[0]) == 0

    def load_registry(self) -> dict[str, Any]:
        with self._lock:
            candidate_rows = self._connection.execute(
                """
                SELECT payload
                FROM discovery_candidates
                ORDER BY candidate_id
                """
            ).fetchall()
            node_rows = self._connection.execute(
                """
                SELECT payload
                FROM discovery_nodes
                ORDER BY node_name
                """
            ).fetchall()
        return {
            "version": 2,
            "nodes": [json.loads(row["payload"]) for row in node_rows],
            "candidates": [
                json.loads(row["payload"]) for row in candidate_rows
            ],
        }

    def save_registry(self, document: CandidateRegistryDocument) -> None:
        payload = document.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        candidates = payload.get("candidates") or []
        nodes = payload.get("nodes") or []
        candidate_ids = [str(item["candidateId"]) for item in candidates]
        node_names = [str(item["nodeName"]) for item in nodes]
        try:
            with self._lock:
                self._connection.execute("BEGIN IMMEDIATE")
                for item in candidates:
                    self._connection.execute(
                        """
                        INSERT INTO discovery_candidates(
                            candidate_id, payload, updated_at
                        ) VALUES(?, ?, ?)
                        ON CONFLICT(candidate_id) DO UPDATE SET
                            payload = excluded.payload,
                            updated_at = excluded.updated_at
                        """,
                        (
                            item["candidateId"],
                            self._json(item),
                            item["updatedAt"],
                        ),
                    )
                for item in nodes:
                    self._connection.execute(
                        """
                        INSERT INTO discovery_nodes(
                            node_name, payload, updated_at
                        ) VALUES(?, ?, ?)
                        ON CONFLICT(node_name) DO UPDATE SET
                            payload = excluded.payload,
                            updated_at = excluded.updated_at
                        """,
                        (
                            item["nodeName"],
                            self._json(item),
                            item["lastReportAt"],
                        ),
                    )
                self._delete_missing(
                    "discovery_candidates",
                    "candidate_id",
                    candidate_ids,
                )
                self._delete_missing(
                    "discovery_nodes",
                    "node_name",
                    node_names,
                )
                self._connection.execute("COMMIT")
        except sqlite3.Error as exc:
            with self._lock:
                self._connection.execute("ROLLBACK")
            raise DiscoveryStoreError(
                "failed to commit discovery candidate registry"
            ) from exc

    def import_legacy_registry(self, document: dict[str, Any]) -> bool:
        with self._lock:
            imported = self._connection.execute(
                """
                SELECT value
                FROM discovery_metadata
                WHERE key = 'legacy_registry_imported'
                """
            ).fetchone()
            if imported is not None:
                return False
            if not self.is_empty():
                return False
        parsed = CandidateRegistryDocument.model_validate(
            {
                **document,
                "version": 2,
            }
        )
        self.save_registry(parsed)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO discovery_metadata(key, value)
                VALUES('legacy_registry_imported', 'true')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
        return True

    def get_plan(self, node_id: str) -> DiscoveryPlan | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM discovery_plans WHERE node_id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            return None
        return DiscoveryPlan.model_validate_json(row["payload"])

    def put_plan(self, plan: DiscoveryPlan) -> DiscoveryPlan:
        payload = plan.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO discovery_plans(
                    node_id, payload, version, updated_at
                ) VALUES(?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    payload = excluded.payload,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (
                    plan.node_id,
                    self._json(payload),
                    plan.version,
                    payload["updatedAt"],
                ),
            )
        return plan

    def list_plans(self) -> list[DiscoveryPlan]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM discovery_plans ORDER BY node_id"
            ).fetchall()
        return [
            DiscoveryPlan.model_validate_json(row["payload"]) for row in rows
        ]

    def get_registration(self, candidate_id: str) -> RegistrationRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload
                FROM registration_sagas
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        return RegistrationRecord.model_validate_json(row["payload"])

    def put_registration(
        self,
        registration: RegistrationRecord,
    ) -> RegistrationRecord:
        payload = registration.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO registration_sagas(
                    candidate_id, payload, updated_at
                ) VALUES(?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    registration.candidate_id,
                    self._json(payload),
                    payload["updatedAt"],
                ),
            )
        return registration

    def list_registrations(self) -> list[RegistrationRecord]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM registration_sagas ORDER BY candidate_id"
            ).fetchall()
        return [
            RegistrationRecord.model_validate_json(row["payload"])
            for row in rows
        ]

    def append_event(self, event: DiscoveryAuditEvent) -> None:
        payload = event.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO discovery_audit_events(
                    event_id, candidate_id, occurred_at, payload
                ) VALUES(?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.candidate_id,
                    payload["occurredAt"],
                    self._json(payload),
                ),
            )

    def list_events(
        self,
        *,
        candidate_id: str | None = None,
        limit: int = 200,
    ) -> list[DiscoveryAuditEvent]:
        bounded_limit = max(1, min(limit, 2000))
        with self._lock:
            if candidate_id is None:
                rows = self._connection.execute(
                    """
                    SELECT payload
                    FROM discovery_audit_events
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (bounded_limit,),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    """
                    SELECT payload
                    FROM discovery_audit_events
                    WHERE candidate_id = ?
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (candidate_id, bounded_limit),
                ).fetchall()
        return [
            DiscoveryAuditEvent.model_validate_json(row["payload"])
            for row in rows
        ]

    def get_idempotent_response(
        self,
        scope: str,
        request_id: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_hash, response_payload
                FROM discovery_idempotency
                WHERE scope = ? AND request_id = ?
                """,
                (scope, request_id),
            ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise DiscoveryStoreError(
                "idempotency request ID was reused with another payload"
            )
        return json.loads(row["response_payload"])

    def put_idempotent_response(
        self,
        scope: str,
        request_id: str,
        payload_hash: str,
        response: dict[str, Any],
    ) -> None:
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO discovery_idempotency(
                        scope, request_id, payload_hash, response_payload
                    ) VALUES(?, ?, ?, ?)
                    """,
                    (
                        scope,
                        request_id,
                        payload_hash,
                        self._json(response),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                current = self.get_idempotent_response(
                    scope,
                    request_id,
                    payload_hash,
                )
                if current != response:
                    raise DiscoveryStoreError(
                        "idempotent response already exists with another value"
                    ) from exc

    def _delete_missing(
        self,
        table: str,
        field: str,
        values: list[str],
    ) -> None:
        if values:
            placeholders = ",".join("?" for _ in values)
            self._connection.execute(
                f"DELETE FROM {table} WHERE {field} NOT IN ({placeholders})",
                values,
            )
        else:
            self._connection.execute(f"DELETE FROM {table}")

    @staticmethod
    def _json(payload: Any) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
