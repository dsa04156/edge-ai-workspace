"""SQLite WAL-backed, durable edge export queue."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class EventConflict(ValueError):
    """An event ID was reused for different canonical EdgeX event data."""


class EventValidationError(ValueError):
    """An event cannot be represented by the durable EdgeX outbox."""


class OutboxMigrationError(RuntimeError):
    """A legacy row cannot be safely upgraded to the stream-aware schema."""


class OutboxCapacityExceeded(RuntimeError):
    """The durable queue cannot admit another unacknowledged event."""


_SIMPLE_INTEGER_TYPES = {"Int8", "Int16", "Int32", "Int64", "Uint8", "Uint16", "Uint32", "Uint64"}
_INTEGER_RANGES = {
    "Int8": (-(2 ** 7), 2 ** 7 - 1), "Int16": (-(2 ** 15), 2 ** 15 - 1),
    "Int32": (-(2 ** 31), 2 ** 31 - 1), "Int64": (-(2 ** 63), 2 ** 63 - 1),
    "Uint8": (0, 2 ** 8 - 1), "Uint16": (0, 2 ** 16 - 1),
    "Uint32": (0, 2 ** 32 - 1), "Uint64": (0, 2 ** 64 - 1),
}
_SIMPLE_FLOAT_TYPES = {"Float32", "Float64"}
_SIMPLE_TYPES = _SIMPLE_INTEGER_TYPES | _SIMPLE_FLOAT_TYPES | {"Bool", "String"}
_EVENT_FIELDS = {"apiVersion", "id", "deviceName", "profileName", "sourceName", "origin", "readings", "tags"}
_EVENT_GENERATED_FIELDS = {"created", "modified"}
_READING_FIELDS = {"deviceName", "profileName", "resourceName", "valueType", "origin", "value", "binaryValue", "objectValue"}
_READING_GENERATED_FIELDS = {"id", "created", "modified"}
_FLOAT32_MAX = 3.4028234663852886e38


def _finite_float(value: Any, value_type: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventValidationError(f"EdgeX {value_type} reading value must be finite numeric")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise EventValidationError(f"EdgeX {value_type} reading value must be finite numeric") from error
    if not math.isfinite(converted):
        raise EventValidationError(f"EdgeX {value_type} reading value must be finite numeric")
    if value_type == "Float32" and abs(converted) > _FLOAT32_MAX:
        raise EventValidationError("EdgeX Float32 reading value is outside its supported range")
    return converted




def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"EdgeX event requires a non-empty string {field}")
    return value


def _origin(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EventValidationError(f"EdgeX {field} must be a non-negative integer")
    return value


def _strict_json(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        raise EventValidationError(f"EdgeX {field} must be finite")
    if isinstance(value, list):
        return [_strict_json(item, field) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise EventValidationError(f"EdgeX {field} must have string object keys")
        return {key: _strict_json(item, field) for key, item in value.items()}
    raise EventValidationError(f"EdgeX {field} is not strict JSON")


def _canonical_reading(reading: Any, device_name: str, profile_name: str) -> dict[str, Any]:
    if not isinstance(reading, dict):
        raise EventValidationError("EdgeX event readings must be objects")
    unknown = set(reading) - _READING_FIELDS - _READING_GENERATED_FIELDS
    if unknown:
        raise EventValidationError(f"EdgeX reading has unknown fields: {', '.join(sorted(unknown))}")
    reading_device = _non_empty_string(reading.get("deviceName"), "reading.deviceName")
    reading_profile = _non_empty_string(reading.get("profileName"), "reading.profileName")
    if reading_device != device_name or reading_profile != profile_name:
        raise EventValidationError("EdgeX reading deviceName and profileName must match its Event")
    value_type = _non_empty_string(reading.get("valueType"), "reading.valueType")
    variants = [name for name in ("value", "binaryValue", "objectValue") if name in reading]
    if len(variants) != 1:
        raise EventValidationError("EdgeX reading requires exactly one value, binaryValue, or objectValue")
    variant = variants[0]
    canonical: dict[str, Any] = {
        "deviceName": reading_device,
        "profileName": reading_profile,
        "resourceName": _non_empty_string(reading.get("resourceName"), "reading.resourceName"),
        "origin": _origin(reading.get("origin"), "reading.origin"),
        "valueType": value_type,
    }
    value = reading[variant]
    if value_type in _SIMPLE_TYPES:
        if variant != "value":
            raise EventValidationError(f"EdgeX {value_type} readings require value")
        if value_type == "Bool" and not isinstance(value, bool):
            raise EventValidationError("EdgeX Bool reading value must be a boolean")
        if value_type in _SIMPLE_INTEGER_TYPES:
            if isinstance(value, bool) or not isinstance(value, int):
                raise EventValidationError(f"EdgeX {value_type} reading value must be an integer")
            minimum, maximum = _INTEGER_RANGES[value_type]
            if not minimum <= value <= maximum:
                raise EventValidationError(f"EdgeX {value_type} reading value is outside its supported range")
        if value_type in _SIMPLE_FLOAT_TYPES:
            _finite_float(value, value_type)
        if value_type == "String" and not isinstance(value, str):
            raise EventValidationError("EdgeX String reading value must be a string")
        canonical["value"] = value
    elif value_type == "Binary":
        if variant != "binaryValue" or not isinstance(value, str):
            raise EventValidationError("EdgeX Binary reading requires a base64 binaryValue")
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise EventValidationError("EdgeX Binary reading binaryValue must be base64") from error
        canonical["binaryValue"] = value
    elif value_type == "Object":
        if variant != "objectValue" or not isinstance(value, dict):
            raise EventValidationError("EdgeX Object reading requires an objectValue object")
        canonical["objectValue"] = _strict_json(value, "reading.objectValue")
    else:
        raise EventValidationError(f"EdgeX reading valueType {value_type!r} is unsupported")
    return canonical


def canonical_event(event: Any) -> dict[str, Any]:
    """Validate and project the authoritative EdgeX v3 Event semantics.

    Only EdgeX Core-generated timestamps and Reading IDs are omitted from the
    stored representation and fingerprint; all remaining fields are explicit.
    """
    if not isinstance(event, dict):
        raise EventValidationError("EdgeX event must be an object")
    unknown = set(event) - _EVENT_FIELDS - _EVENT_GENERATED_FIELDS
    if unknown:
        raise EventValidationError(f"EdgeX event has unknown fields: {', '.join(sorted(unknown))}")
    if event.get("apiVersion") != "v3":
        raise EventValidationError("EdgeX apiVersion must be 'v3'")
    device_name = _non_empty_string(event.get("deviceName"), "deviceName")
    profile_name = _non_empty_string(event.get("profileName"), "profileName")
    readings = event.get("readings")
    if not isinstance(readings, list) or not readings:
        raise EventValidationError("EdgeX event readings must be a non-empty array")
    canonical: dict[str, Any] = {
        "apiVersion": "v3",
        "id": _non_empty_string(event.get("id"), "id"),
        "deviceName": device_name,
        "profileName": profile_name,
        "sourceName": _non_empty_string(event.get("sourceName"), "sourceName"),
        "origin": _origin(event.get("origin"), "origin"),
        "readings": [_canonical_reading(reading, device_name, profile_name) for reading in readings],
    }
    if "tags" in event:
        tags = event["tags"]
        if not isinstance(tags, dict) or any(
            not isinstance(key, str) or not key.strip() or not isinstance(value, str) for key, value in tags.items()
        ):
            raise EventValidationError("EdgeX event tags must be a string-to-string object with non-empty keys")
        canonical["tags"] = dict(tags)
    return canonical


def _canonical_bytes(event: Any) -> bytes:
    return json.dumps(canonical_event(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def fingerprint(event: Any) -> str:
    """Digest the validated stable EdgeX Event identity."""
    return hashlib.sha256(_canonical_bytes(event)).hexdigest()


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    payload: dict[str, Any]
    attempts: int
    claim_token: int


@dataclass(frozen=True)
class OutboxDiagnostics:
    pending_count: int
    pending_bytes: int
    oldest_pending_age: float | None
    rejected_count: int = 0
    rejected_bytes: int = 0
    retained_count: int = 0
    retained_bytes: int = 0


class EdgeOutbox:
    """Thread-safe SQLite queue with FIFO streams and token-fenced persisted ACKs."""

    def __init__(self, path: str | Path, *, max_bytes: int = 256 * 1024 * 1024, lease_seconds: float = 30.0) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.max_bytes = max_bytes
        self.lease_seconds = lease_seconds
        self._lock = threading.RLock()
        self._closed = False
        self.connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        with self._lock:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA busy_timeout=5000")
            self._create_or_migrate()

    def _create_outbox_table(self, name: str) -> None:
        self.connection.execute(f"""CREATE TABLE {name} (
            event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
            stream_device TEXT NOT NULL DEFAULT '', stream_source TEXT NOT NULL DEFAULT '',
            stream_sequence INTEGER NOT NULL DEFAULT 0, payload_bytes INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL CHECK(state IN ('pending', 'inflight', 'delivered', 'rejected')),
            attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL,
            lease_expires_at REAL, lease_token INTEGER NOT NULL DEFAULT 0, last_error TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")

    def _create_or_migrate(self) -> None:
        with self._transaction():
            table = self.connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'outbox'"
            ).fetchone()
            if table is None:
                self._create_outbox_table("outbox")
            elif not self._is_canonical_schema(table["sql"]):
                self._rebuild_legacy_table()
            self.connection.execute("""CREATE TABLE IF NOT EXISTS outbox_stream_sequences (
                stream_device TEXT NOT NULL, stream_source TEXT NOT NULL, last_sequence INTEGER NOT NULL,
                PRIMARY KEY (stream_device, stream_source))""")
            self.connection.execute("""INSERT INTO outbox_stream_sequences (stream_device, stream_source, last_sequence)
                SELECT stream_device, stream_source, MAX(stream_sequence) FROM outbox
                GROUP BY stream_device, stream_source
                ON CONFLICT(stream_device, stream_source) DO UPDATE SET last_sequence = MAX(last_sequence, excluded.last_sequence)""")
            self.connection.execute("CREATE INDEX IF NOT EXISTS outbox_stream_fifo ON outbox(stream_device, stream_source, stream_sequence, state, next_attempt_at)")

    @staticmethod
    def _is_canonical_schema(sql: str | None) -> bool:
        if sql is None:
            return False
        normalized = "".join(sql.lower().split())
        return ("statetextnotnullcheck(statein('pending','inflight','delivered','rejected'))" in normalized
                and all(name in normalized for name in (
                    "stream_device", "stream_source", "stream_sequence", "payload_bytes",
                    "lease_expires_at", "lease_token",
                )))

    def _rebuild_legacy_table(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(outbox)")}
        has_sequence_metadata = "stream_sequence" in columns
        order = "created_at, event_id, rowid" if {"created_at", "event_id"} <= columns else "rowid"
        rows = self.connection.execute(f"SELECT rowid, * FROM outbox ORDER BY {order}").fetchall()
        self.connection.execute("DROP TABLE IF EXISTS outbox_rebuilt")
        self._create_outbox_table("outbox_rebuilt")
        sequences: dict[tuple[str, str], int] = {}
        seen_sequences: dict[tuple[str, str], set[int]] = {}
        allowed_states = {"pending", "inflight", "delivered", "rejected"}
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                canonical = canonical_event(payload)
                if canonical["id"] != row["event_id"]:
                    raise EventValidationError("payload ID does not match outbox row ID")
                body = _canonical_bytes(canonical).decode()
                device, source = self._stream(canonical)
            except (json.JSONDecodeError, EventValidationError, TypeError, UnicodeDecodeError) as error:
                raise OutboxMigrationError(f"cannot safely reconstruct legacy event {row['event_id']!r}") from error
            state = row["state"] if "state" in columns else "pending"
            if state not in allowed_states:
                raise OutboxMigrationError(f"legacy event {row['event_id']!r} has unknown state {state!r}")
            stream = (device, source)
            if {"stream_device", "stream_source"} <= columns and (
                row["stream_device"] != device or row["stream_source"] != source
            ):
                raise OutboxMigrationError(
                    f"legacy event {row['event_id']!r} has stream metadata that disagrees with its payload"
                )
            if has_sequence_metadata:
                sequence = row["stream_sequence"]
                if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
                    raise OutboxMigrationError(
                        f"legacy event {row['event_id']!r} has invalid stream sequence {sequence!r}"
                    )
                if stream in seen_sequences and sequence in seen_sequences[stream]:
                    raise OutboxMigrationError(
                        f"legacy event {row['event_id']!r} duplicates stream sequence {sequence}"
                    )
                seen_sequences.setdefault(stream, set()).add(sequence)
                sequences[stream] = max(sequences.get(stream, 0), sequence)
            else:
                sequence = sequences.get(stream, 0) + 1
                sequences[stream] = sequence
            created_at = row["created_at"] if "created_at" in columns else time.time()
            updated_at = row["updated_at"] if "updated_at" in columns else created_at
            next_attempt_at = row["next_attempt_at"] if "next_attempt_at" in columns else created_at
            attempts = row["attempts"] if "attempts" in columns else 0
            last_error = row["last_error"] if "last_error" in columns else None
            self.connection.execute("""INSERT INTO outbox_rebuilt (
                event_id, payload, fingerprint, stream_device, stream_source, stream_sequence,
                payload_bytes, state, attempts, next_attempt_at, lease_expires_at, lease_token,
                last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, ?)""", (
                canonical["id"], body, hashlib.sha256(body.encode()).hexdigest(), device, source, sequence,
                len(body.encode()), "pending" if state == "inflight" else state, attempts, next_attempt_at,
                last_error, created_at, updated_at,
            ))
        self.connection.execute("DROP TABLE outbox")
        self.connection.execute("ALTER TABLE outbox_rebuilt RENAME TO outbox")
        self.connection.execute("DROP INDEX IF EXISTS outbox_stream_fifo")
        self.connection.execute("DROP TABLE IF EXISTS outbox_stream_sequences")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("outbox is closed")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    @staticmethod
    def _stream(event: dict[str, Any]) -> tuple[str, str]:
        return (_non_empty_string(event.get("deviceName"), "deviceName"), _non_empty_string(event.get("sourceName"), "sourceName"))

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self.connection.close()
                self._closed = True

    def enqueue(self, event: dict[str, Any], now: float | None = None) -> bool:
        canonical = canonical_event(event)
        event_id = canonical["id"]
        now = time.time() if now is None else now
        body = _canonical_bytes(canonical).decode()
        digest = hashlib.sha256(body.encode()).hexdigest()
        device, source = self._stream(canonical)
        body_bytes = len(body.encode())
        with self._lock:
            self._ensure_open()
            with self._transaction():
                existing = self.connection.execute("SELECT fingerprint FROM outbox WHERE event_id = ?", (event_id,)).fetchone()
                if existing is not None:
                    if existing["fingerprint"] != digest:
                        raise EventConflict(f"event ID {event_id!r} conflicts with existing payload")
                    return False
                used = self.connection.execute("SELECT COALESCE(SUM(payload_bytes), 0) AS bytes FROM outbox WHERE state IN ('pending', 'inflight', 'rejected')").fetchone()["bytes"]
                if used + body_bytes > self.max_bytes:
                    raise OutboxCapacityExceeded(f"outbox admission exceeds {self.max_bytes} byte capacity ({used} bytes retained, {body_bytes} bytes requested)")
                self.connection.execute("INSERT INTO outbox_stream_sequences (stream_device, stream_source, last_sequence) VALUES (?, ?, 0) ON CONFLICT(stream_device, stream_source) DO NOTHING", (device, source))
                self.connection.execute("UPDATE outbox_stream_sequences SET last_sequence = last_sequence + 1 WHERE stream_device = ? AND stream_source = ?", (device, source))
                sequence = self.connection.execute("SELECT last_sequence FROM outbox_stream_sequences WHERE stream_device = ? AND stream_source = ?", (device, source)).fetchone()["last_sequence"]
                self.connection.execute("""INSERT INTO outbox (event_id, payload, fingerprint, stream_device, stream_source, stream_sequence,
                    payload_bytes, state, attempts, next_attempt_at, lease_expires_at, lease_token, last_error, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, 0, NULL, ?, ?)""", (event_id, body, digest, device, source, sequence, body_bytes, now, now, now))
                return True

    def claim(self, now: float | None = None) -> OutboxEvent | None:
        now = time.time() if now is None else now
        with self._lock:
            self._ensure_open()
            with self._transaction():
                self.connection.execute("UPDATE outbox SET state = 'pending', lease_expires_at = NULL WHERE state = 'inflight' AND lease_expires_at <= ?", (now,))
                row = self.connection.execute("""SELECT candidate.event_id, candidate.payload, candidate.attempts, candidate.lease_token
                    FROM outbox AS candidate WHERE candidate.state = 'pending' AND candidate.next_attempt_at <= ?
                    AND NOT EXISTS (SELECT 1 FROM outbox AS earlier WHERE earlier.stream_device = candidate.stream_device
                        AND earlier.stream_source = candidate.stream_source AND earlier.stream_sequence < candidate.stream_sequence
                        AND earlier.state IN ('pending', 'inflight'))
                    ORDER BY candidate.created_at, candidate.stream_sequence, candidate.event_id LIMIT 1""", (now,)).fetchone()
                if row is None:
                    return None
                token = row["lease_token"] + 1
                changed = self.connection.execute("""UPDATE outbox SET state = 'inflight', lease_expires_at = ?, lease_token = ?, updated_at = ?
                    WHERE event_id = ? AND state = 'pending' AND lease_token = ?""", (now + self.lease_seconds, token, now, row["event_id"], row["lease_token"])).rowcount
                if changed != 1:
                    return None
                return OutboxEvent(row["event_id"], json.loads(row["payload"]), row["attempts"], token)

    def delivered(self, event_id: str, claim_token: int, now: float | None = None) -> None:
        with self._lock:
            self._ensure_open()
            changed = self.connection.execute("DELETE FROM outbox WHERE event_id = ? AND state = 'inflight' AND lease_token = ?", (event_id, claim_token)).rowcount
            if changed != 1:
                raise ValueError(f"event {event_id!r} is not owned by this inflight lease")

    def reject(self, event_id: str, claim_token: int, error: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._ensure_open()
            changed = self.connection.execute("""UPDATE outbox SET state = 'rejected', lease_expires_at = NULL, last_error = ?, updated_at = ?
                WHERE event_id = ? AND state = 'inflight' AND lease_token = ?""", (error[:1000], now, event_id, claim_token)).rowcount
            if changed != 1:
                raise ValueError(f"event {event_id!r} is not owned by this inflight lease")

    def discard_rejected(self, event_id: str) -> None:
        with self._lock:
            self._ensure_open()
            if self.connection.execute("DELETE FROM outbox WHERE event_id = ? AND state = 'rejected'", (event_id,)).rowcount != 1:
                raise ValueError(f"event {event_id!r} is not rejected")

    def requeue_rejected(self, event_id: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._ensure_open()
            if self.connection.execute("""UPDATE outbox SET state = 'pending', next_attempt_at = ?, lease_expires_at = NULL,
                last_error = NULL, updated_at = ? WHERE event_id = ? AND state = 'rejected'""", (now, now, event_id)).rowcount != 1:
                raise ValueError(f"event {event_id!r} is not rejected")

    def failed(self, event_id: str, claim_token: int, error: str, now: float | None = None) -> float:
        now = time.time() if now is None else now
        with self._lock:
            self._ensure_open()
            with self._transaction():
                row = self.connection.execute("SELECT attempts FROM outbox WHERE event_id = ? AND state = 'inflight' AND lease_token = ?", (event_id, claim_token)).fetchone()
                if row is None:
                    raise ValueError(f"event {event_id!r} is not owned by this inflight lease")
                attempts = row["attempts"] + 1
                delay = min(300.0, float(2 ** min(attempts, 8)))
                changed = self.connection.execute("""UPDATE outbox SET state = 'pending', attempts = ?, next_attempt_at = ?,
                    lease_expires_at = NULL, last_error = ?, updated_at = ? WHERE event_id = ? AND state = 'inflight' AND lease_token = ?""", (attempts, now + delay, error[:1000], now, event_id, claim_token)).rowcount
                if changed != 1:
                    raise ValueError(f"event {event_id!r} is not owned by this inflight lease")
                return delay

    def diagnostics(self, now: float | None = None) -> OutboxDiagnostics:
        now = time.time() if now is None else now
        with self._lock:
            self._ensure_open()
            row = self.connection.execute("""SELECT
                COALESCE(SUM(CASE WHEN state IN ('pending', 'inflight') THEN 1 ELSE 0 END), 0) AS pending_count,
                COALESCE(SUM(CASE WHEN state IN ('pending', 'inflight') THEN payload_bytes ELSE 0 END), 0) AS pending_bytes,
                MIN(CASE WHEN state IN ('pending', 'inflight') THEN created_at END) AS oldest,
                COALESCE(SUM(CASE WHEN state = 'rejected' THEN 1 ELSE 0 END), 0) AS rejected_count,
                COALESCE(SUM(CASE WHEN state = 'rejected' THEN payload_bytes ELSE 0 END), 0) AS rejected_bytes,
                COALESCE(SUM(CASE WHEN state IN ('pending', 'inflight', 'rejected') THEN 1 ELSE 0 END), 0) AS retained_count,
                COALESCE(SUM(CASE WHEN state IN ('pending', 'inflight', 'rejected') THEN payload_bytes ELSE 0 END), 0) AS retained_bytes
                FROM outbox""").fetchone()
            return OutboxDiagnostics(row["pending_count"], row["pending_bytes"], None if row["oldest"] is None else max(0.0, now - row["oldest"]), row["rejected_count"], row["rejected_bytes"], row["retained_count"], row["retained_bytes"])

    def oldest_pending_age(self, now: float | None = None) -> float | None:
        return self.diagnostics(now).oldest_pending_age
