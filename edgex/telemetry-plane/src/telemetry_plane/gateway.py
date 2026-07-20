"""Central HTTPS gateway: authenticated durable ingestion and diagnostics."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from contextlib import asynccontextmanager
from inspect import isawaitable
import re

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .commands import CommandBridge, CommandError, CommandExpiredError, CommandUnavailableError, command_from_payload
from .clients import request_signature
from .outbox import EventConflict, EventValidationError, canonical_event, fingerprint

InboxState = Literal["reserved", "posting", "persisted", "conflict"]
Reconciliation = Literal["equal", "conflict", "absent"]
MAX_BODY_BYTES = 1024 * 1024
TIMESTAMP_WIRE_FORMAT = re.compile(r"[0-9]{1,20}(?:\.[0-9]{1,9})?")
SIGNATURE_WIRE_FORMAT = re.compile(r"[0-9a-f]{64}")


def _strict_json(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value!r}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)


@dataclass
class InboxRecord:
    edge_id: str
    event_id: str
    digest: str
    payload: dict[str, Any]
    state: InboxState = "reserved"
    lease_expires_at: float | None = None
    ownership_token: str | None = None


class Inbox(Protocol):
    def reserve(self, edge_id: str, event: dict[str, Any]) -> tuple[InboxRecord, bool]: ...
    def begin_posting(self, edge_id: str, event_id: str, now: float) -> tuple[Literal["post", "owned", "recover"], str | None]: ...
    def mark_persisted(self, edge_id: str, event_id: str, ownership_token: str) -> None: ...
    def mark_conflict(self, edge_id: str, event_id: str, ownership_token: str) -> None: ...


class MemoryInbox:
    """Thread-safe test implementation of the PostgreSQL inbox contract."""
    def __init__(self, lease_seconds: float = 30.0) -> None:
        if lease_seconds <= 0:
            raise ValueError("inbox lease_seconds must be positive")
        self.lease_seconds = lease_seconds
        self.records: dict[tuple[str, str], InboxRecord] = {}
        self._lock = threading.RLock()

    def reserve(self, edge_id: str, event: dict[str, Any]) -> tuple[InboxRecord, bool]:
        event_id, digest = event["id"], fingerprint(event)
        key = (edge_id, event_id)
        with self._lock:
            current = self.records.get(key)
            if current:
                if current.digest != digest:
                    raise EventConflict(f"event ID {event_id!r} conflicts with existing payload for edge {edge_id!r}")
                return current, False
            record = InboxRecord(edge_id, event_id, digest, event)
            self.records[key] = record
            return record, True

    def begin_posting(self, edge_id: str, event_id: str, now: float) -> tuple[Literal["post", "owned", "recover"], str | None]:
        with self._lock:
            record = self.records[(edge_id, event_id)]
            if record.state in ("persisted", "conflict"):
                return "owned", None
            if record.state == "posting" and record.lease_expires_at is not None and record.lease_expires_at > now:
                return "owned", None
            action: Literal["post", "recover"] = "recover" if record.state == "posting" else "post"
            token = str(uuid.uuid4())
            record.state, record.lease_expires_at, record.ownership_token = "posting", now + self.lease_seconds, token
            return action, token

    def _owned(self, edge_id: str, event_id: str, ownership_token: str) -> InboxRecord:
        record = self.records[(edge_id, event_id)]
        if record.state != "posting" or not hmac.compare_digest(record.ownership_token or "", ownership_token):
            raise ValueError("inbox ownership token no longer owns this record")
        return record


    def mark_persisted(self, edge_id: str, event_id: str, ownership_token: str) -> None:
        with self._lock:
            record = self._owned(edge_id, event_id, ownership_token)
            record.state, record.lease_expires_at, record.ownership_token = "persisted", None, None

    def mark_conflict(self, edge_id: str, event_id: str, ownership_token: str) -> None:
        with self._lock:
            record = self._owned(edge_id, event_id, ownership_token)
            record.state, record.lease_expires_at, record.ownership_token = "conflict", None, None


class PostgreSQLInbox:
    """Durable, token-fenced inbox keyed by producer identity and Event ID."""
    def __init__(self, dsn: str, lease_seconds: float = 30.0) -> None:
        if lease_seconds <= 0:
            raise ValueError("inbox lease_seconds must be positive")
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("PostgreSQLInbox requires edgex-telemetry-plane[postgres]") from error
        self.lease_seconds = lease_seconds
        self._dsn = dsn
        self._psycopg = psycopg
        self._connect = psycopg.connect
        self._lock = threading.RLock()
        self.connection: Any | None = None
        self._closed = False
        with self._lock:
            self._ensure_connection_locked()

    def _initialize_connection(self, connection: Any) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS telemetry_inbox (
            edge_id TEXT NOT NULL, event_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            payload JSONB NOT NULL, state TEXT NOT NULL CHECK(state IN ('reserved','posting','persisted','conflict')),
            lease_expires_at TIMESTAMPTZ NULL, ownership_token UUID NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(), persisted_at TIMESTAMPTZ NULL,
            PRIMARY KEY (edge_id, event_id))""")
        connection.execute("ALTER TABLE telemetry_inbox ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ NULL")
        connection.execute("ALTER TABLE telemetry_inbox ADD COLUMN IF NOT EXISTS ownership_token UUID NULL")

    def _connection_error(self, error: Exception) -> bool:
        error_types = (getattr(self._psycopg, "OperationalError", None),
                       getattr(self._psycopg, "InterfaceError", None),
                       getattr(getattr(self._psycopg, "errors", None), "AdminShutdown", None))
        return any(isinstance(error, error_type) for error_type in error_types if isinstance(error_type, type))

    def _discard_connection_locked(self, connection: Any) -> Exception | None:
        if self.connection is connection:
            self.connection = None
        try:
            connection.close()
        except Exception as error:
            return error
        return None

    def _ensure_connection_locked(self) -> Any:
        if self._closed:
            raise RuntimeError("PostgreSQLInbox is closed")
        if self.connection is not None and not getattr(self.connection, "closed", False):
            return self.connection
        if self.connection is not None:
            self.connection = None
        connection = self._connect(self._dsn, autocommit=True)
        try:
            self._initialize_connection(connection)
        except Exception as error:
            close_error = self._discard_connection_locked(connection)
            if close_error is not None:
                error.add_note(f"failed to discard PostgreSQL connection: {close_error!r}")
            raise
        self.connection = connection
        return connection

    def _operate(self, operation: Any) -> Any:
        with self._lock:
            connection = self._ensure_connection_locked()
            try:
                return operation(connection)
            except Exception as error:
                if self._connection_error(error):
                    close_error = self._discard_connection_locked(connection)
                    if close_error is not None:
                        error.add_note(f"failed to discard PostgreSQL connection: {close_error!r}")
                raise

    def reserve(self, edge_id: str, event: dict[str, Any]) -> tuple[InboxRecord, bool]:
        event_id, digest = event["id"], fingerprint(event)

        def reserve(connection: Any) -> tuple[InboxRecord, bool]:
            with connection.cursor() as cursor:
                cursor.execute("""INSERT INTO telemetry_inbox (edge_id,event_id,fingerprint,payload,state)
                    VALUES (%s,%s,%s,%s::jsonb,'reserved') ON CONFLICT (edge_id,event_id) DO NOTHING RETURNING state""",
                    (edge_id, event_id, digest, json.dumps(event, allow_nan=False)))
                if cursor.fetchone() is not None:
                    return InboxRecord(edge_id, event_id, digest, event), True
                cursor.execute("""SELECT fingerprint,payload,state,EXTRACT(EPOCH FROM lease_expires_at),ownership_token
                    FROM telemetry_inbox WHERE edge_id=%s AND event_id=%s""", (edge_id,event_id))
                existing = cursor.fetchone()
            if existing is None or existing[0] != digest:
                raise EventConflict(f"event ID {event_id!r} conflicts with existing payload for edge {edge_id!r}")
            return InboxRecord(edge_id, event_id, digest, existing[1], existing[2], existing[3],
                               str(existing[4]) if existing[4] is not None else None), False

        return self._operate(reserve)

    def begin_posting(self, edge_id: str, event_id: str, now: float) -> tuple[Literal["post", "owned", "recover"], str | None]:
        def begin_posting(connection: Any) -> tuple[Literal["post", "owned", "recover"], str | None]:
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute("""SELECT state,EXTRACT(EPOCH FROM lease_expires_at) FROM telemetry_inbox
                    WHERE edge_id=%s AND event_id=%s FOR UPDATE""", (edge_id,event_id))
                state, expiry = cursor.fetchone()
                if state in ("persisted", "conflict") or (state == "posting" and expiry is not None and expiry > now):
                    return "owned", None
                action: Literal["post", "recover"] = "recover" if state == "posting" else "post"
                token = str(uuid.uuid4())
                cursor.execute("""UPDATE telemetry_inbox SET state='posting', lease_expires_at=to_timestamp(%s),
                    ownership_token=%s::uuid WHERE edge_id=%s AND event_id=%s""",
                    (now + self.lease_seconds, token, edge_id, event_id))
                return action, token

        return self._operate(begin_posting)

    def _transition(self, state: InboxState, edge_id: str, event_id: str, ownership_token: str) -> None:
        persisted_at = ",persisted_at=now()" if state == "persisted" else ""

        def transition(connection: Any) -> None:
            changed = connection.execute(f"""UPDATE telemetry_inbox SET state=%s,lease_expires_at=NULL,
                ownership_token=NULL{persisted_at} WHERE edge_id=%s AND event_id=%s AND state='posting'
                AND ownership_token=%s::uuid""", (state, edge_id, event_id, ownership_token)).rowcount
            if changed != 1:
                raise ValueError("inbox ownership token no longer owns this record")

        self._operate(transition)


    def mark_persisted(self, edge_id: str, event_id: str, ownership_token: str) -> None:
        self._transition("persisted", edge_id, event_id, ownership_token)

    def mark_conflict(self, edge_id: str, event_id: str, ownership_token: str) -> None:
        self._transition("conflict", edge_id, event_id, ownership_token)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            connection = self.connection
            if connection is None:
                return
            connection.close()
            if self.connection is connection:
                self.connection = None



class ReplayGuard(Protocol):
    def claim(self, edge_id: str, request_digest: str, expires_at: float, now: float) -> bool: ...


class MemoryReplayGuard:
    """Bounded replay guard for tests; it rejects new requests once full."""
    def __init__(self, capacity: int = 10000) -> None:
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("replay capacity must be positive")
        self.capacity = capacity
        self._claims: dict[tuple[str, str], float] = {}
        self._lock = threading.RLock()

    def claim(self, edge_id: str, request_digest: str, expires_at: float, now: float) -> bool:
        with self._lock:
            self._claims = {key: expiry for key, expiry in self._claims.items() if expiry >= now}
            key = (edge_id, request_digest)
            if key in self._claims or len(self._claims) >= self.capacity:
                return False
            self._claims[key] = expires_at
            return True


class PostgreSQLReplayGuard:
    """Shared replay protection that survives gateway process restarts."""
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("PostgreSQLReplayGuard requires edgex-telemetry-plane[postgres]") from error
        self._dsn = dsn
        self._psycopg = psycopg
        self._connect = psycopg.connect
        self._lock = threading.RLock()
        self.connection: Any | None = None
        self._closed = False
        with self._lock:
            self._ensure_connection_locked()

    def _initialize_connection(self, connection: Any) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS telemetry_replay_guard (
            edge_id TEXT NOT NULL, request_digest TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (edge_id, request_digest))""")

    def _connection_error(self, error: Exception) -> bool:
        error_types = (getattr(self._psycopg, "OperationalError", None),
                       getattr(self._psycopg, "InterfaceError", None),
                       getattr(getattr(self._psycopg, "errors", None), "AdminShutdown", None))
        return any(isinstance(error, error_type) for error_type in error_types if isinstance(error_type, type))

    def _discard_connection_locked(self, connection: Any) -> Exception | None:
        if self.connection is connection:
            self.connection = None
        try:
            connection.close()
        except Exception as error:
            return error
        return None

    def _ensure_connection_locked(self) -> Any:
        if self._closed:
            raise RuntimeError("PostgreSQLReplayGuard is closed")
        if self.connection is not None and not getattr(self.connection, "closed", False):
            return self.connection
        if self.connection is not None:
            self.connection = None
        connection = self._connect(self._dsn, autocommit=True)
        try:
            self._initialize_connection(connection)
        except Exception as error:
            close_error = self._discard_connection_locked(connection)
            if close_error is not None:
                error.add_note(f"failed to discard PostgreSQL connection: {close_error!r}")
            raise
        self.connection = connection
        return connection

    def _operate(self, operation: Any) -> Any:
        with self._lock:
            connection = self._ensure_connection_locked()
            try:
                return operation(connection)
            except Exception as error:
                if self._connection_error(error):
                    close_error = self._discard_connection_locked(connection)
                    if close_error is not None:
                        error.add_note(f"failed to discard PostgreSQL connection: {close_error!r}")
                raise

    def claim(self, edge_id: str, request_digest: str, expires_at: float, now: float) -> bool:
        def claim(connection: Any) -> bool:
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute("DELETE FROM telemetry_replay_guard WHERE expires_at < to_timestamp(%s)", (now,))
                cursor.execute("""INSERT INTO telemetry_replay_guard (edge_id,request_digest,expires_at)
                    VALUES (%s,%s,to_timestamp(%s)) ON CONFLICT (edge_id,request_digest) DO NOTHING""",
                    (edge_id, request_digest, expires_at))
                return cursor.rowcount == 1

        return self._operate(claim)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            connection = self.connection
            if connection is None:
                return
            connection.close()
            if self.connection is connection:
                self.connection = None


class CoreDataAdapter(Protocol):
    async def post_event(self, event: dict[str, Any]) -> None: ...
    async def reconcile_event(self, event: dict[str, Any]) -> Reconciliation: ...


class HTTPXCoreDataAdapter:
    """Maps Events to AddEventRequest and reconciles Core Data's v3 response envelope."""
    def __init__(self, base_url: str, service_name: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url, self.service_name = base_url.rstrip("/"), service_name
        self.client = client or httpx.AsyncClient(timeout=10.0)
    async def close(self) -> None:
        await self.client.aclose()


    @staticmethod
    def add_event_request(event: dict[str, Any]) -> dict[str, Any]:
        return {"apiVersion": "v3", "requestId": str(event["id"]), "event": event}

    async def reconcile_event(self, event: dict[str, Any]) -> Reconciliation:
        from urllib.parse import quote
        response = await self.client.get(f"{self.base_url}/api/v3/event/id/{quote(str(event['id']), safe='')}")
        if response.status_code == 404:
            return "absent"
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as error:
            raise httpx.HTTPError("Core Data reconciliation is not JSON") from error
        if not isinstance(body, dict) or body.get("apiVersion") != "v3" or body.get("statusCode") != 200 or not isinstance(body.get("event"), dict):
            raise httpx.HTTPError("Core Data reconciliation has an invalid v3 response envelope")
        return "equal" if fingerprint(body["event"]) == fingerprint(event) else "conflict"

    async def post_event(self, event: dict[str, Any]) -> None:
        from urllib.parse import quote
        path = "/api/v3/event/{}/{}/{}/{}".format(quote(self.service_name,safe=""),quote(event["profileName"],safe=""),quote(event["deviceName"],safe=""),quote(event["sourceName"],safe=""))
        response = await self.client.post(f"{self.base_url}{path}", json=self.add_event_request(event))
        if response.status_code == 201:
            return
        if response.status_code != 409:
            raise httpx.HTTPStatusError("Core Data must return 201 for a newly persisted Event",
                                        request=response.request, response=response)
        status = await self.reconcile_event(event)
        if status == "equal":
            return
        if status == "conflict":
            raise EventConflict(f"Core Data event ID {event['id']!r} conflicts with canonical Event")
        raise httpx.HTTPStatusError("Core Data rejected an Event absent from reconciliation", request=response.request, response=response)


@dataclass(frozen=True)
class Heartbeat:
    edge_id: str
    source_seen: bool
    source_freshness_seconds: float | None
    export_lag_seconds: float
    outbox_oldest_seconds: float
    observed_at: datetime

    @classmethod
    def from_payload(cls, edge_id: str, payload: dict[str, Any], now: datetime | None = None) -> "Heartbeat":
        required = ("edge_id","source_seen","export_lag_seconds","outbox_oldest_seconds","observed_at")
        if not isinstance(payload,dict) or any(key not in payload for key in required) or payload["edge_id"] != edge_id or not isinstance(payload["source_seen"],bool):
            raise ValueError("heartbeat fields are missing or edge_id does not match")
        source_seen = payload["source_seen"]
        if source_seen != ("source_freshness_seconds" in payload):
            raise ValueError("source_freshness_seconds must be present exactly when source_seen is true")
        try:
            observed = datetime.fromisoformat(str(payload["observed_at"]).replace("Z","+00:00"))
            values = [float(payload[key]) for key in ("export_lag_seconds","outbox_oldest_seconds")]
            freshness = float(payload["source_freshness_seconds"]) if source_seen else None
        except (TypeError,ValueError) as error:
            raise ValueError("heartbeat timestamps and durations must be numeric") from error
        if observed.tzinfo is None or any(not math.isfinite(value) or value < 0 for value in values) or (freshness is not None and (not math.isfinite(freshness) or freshness < 0)):
            raise ValueError("heartbeat requires timezone-aware timestamps and finite non-negative durations")
        observed = observed.astimezone(UTC)
        if observed > (now or datetime.now(UTC)).astimezone(UTC) + timedelta(seconds=300):
            raise ValueError("heartbeat observation is implausibly in the future")
        return cls(edge_id,source_seen,freshness,*values,observed)


class Diagnostics:
    def __init__(self, max_age_seconds: float, configured_edges: set[str] | None = None) -> None:
        self.max_age_seconds, self.configured_edges, self.heartbeats = max_age_seconds, set(configured_edges or ()), {}
        self.received_at: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def update(self, heartbeat: Heartbeat, received_at: datetime | None = None) -> None:
        with self._lock:
            self.heartbeats[heartbeat.edge_id] = heartbeat
            self.received_at[heartbeat.edge_id] = received_at or datetime.now(UTC)

    def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        with self._lock:
            ids = self.configured_edges | set(self.heartbeats)
            beats, receipts = dict(self.heartbeats), dict(self.received_at)
        edges: dict[str, Any] = {}
        for edge_id in sorted(ids):
            beat = beats.get(edge_id)
            if beat is None:
                edges[edge_id] = {"healthy": False, "source_seen": False, "reason": "never_seen"}
                continue
            receipt_age = max(0.0, (now - receipts[edge_id]).total_seconds())
            observation_age = max(0.0, (now - beat.observed_at).total_seconds())
            stale = (receipt_age > self.max_age_seconds or observation_age > self.max_age_seconds
                     or not beat.source_seen or any(value > self.max_age_seconds for value in
                     (beat.source_freshness_seconds, beat.export_lag_seconds, beat.outbox_oldest_seconds)
                     if value is not None))
            edges[edge_id] = {"healthy": not stale, "receipt_age_seconds": receipt_age,
                              "observation_age_seconds": observation_age, "source_seen": beat.source_seen,
                              "source_freshness_seconds": beat.source_freshness_seconds,
                              "export_lag_seconds": beat.export_lag_seconds,
                              "outbox_oldest_seconds": beat.outbox_oldest_seconds,
                              "observed_at": beat.observed_at.isoformat()}
        return {"healthy": bool(edges) and all(item["healthy"] for item in edges.values()), "edges": edges}


class RequestAuthenticator:
    def __init__(self, edge_auth_secrets: dict[str, str], replay_guard: ReplayGuard,
                 max_skew_seconds: float = 300.0) -> None:
        if not edge_auth_secrets or any(not isinstance(edge, str) or not edge or not isinstance(secret, str) or not secret
                                        for edge, secret in edge_auth_secrets.items()):
            raise ValueError("edge_auth_secrets must map non-empty edge IDs to non-empty secrets")
        if not math.isfinite(max_skew_seconds) or max_skew_seconds <= 0 or replay_guard is None:
            raise ValueError("authentication bounds and replay_guard are required")
        self.edge_auth_secrets, self.replay_guard, self.max_skew_seconds = (
            dict(edge_auth_secrets), replay_guard, max_skew_seconds)

    def verify(self, edge_id: str | None, timestamp: str | None, signature: str | None, payload: bytes) -> None:
        if not isinstance(timestamp, str) or TIMESTAMP_WIRE_FORMAT.fullmatch(timestamp) is None:
            raise HTTPException(401, "invalid request timestamp")
        if not isinstance(signature, str) or SIGNATURE_WIRE_FORMAT.fullmatch(signature) is None:
            raise HTTPException(401, "invalid request signature")
        issued_at = float(timestamp)
        now = time.time()
        if not math.isfinite(issued_at) or issued_at <= 0 or issued_at > now + self.max_skew_seconds or now - issued_at > self.max_skew_seconds:
            raise HTTPException(401, "request timestamp outside accepted clock skew")
        if not isinstance(edge_id, str):
            raise HTTPException(401, "unknown edge")
        secret = self.edge_auth_secrets.get(edge_id)
        if secret is None:
            raise HTTPException(401, "unknown edge")
        try:
            expected = request_signature(secret, edge_id, timestamp, payload).encode("ascii")
        except UnicodeError:
            raise HTTPException(401, "invalid request signature")
        supplied = signature.encode("ascii")
        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(401, "invalid request signature")
        digest = hashlib.sha256(timestamp.encode("ascii") + b"\0" + supplied).hexdigest()
        if not self.replay_guard.claim(edge_id, digest, issued_at + self.max_skew_seconds, now):
            raise HTTPException(401, "replayed request")

async def close_owned_resources(resources: tuple[object, ...]) -> None:
    """Close each production-owned dependency once in reverse construction order."""
    seen: set[int] = set()
    unique_resources: list[object] = []
    for resource in resources:
        if resource is None or id(resource) in seen:
            continue
        seen.add(id(resource))
        unique_resources.append(resource)

    errors: list[Exception] = []
    for resource in reversed(unique_resources):
        try:
            async_closer = getattr(resource, "aclose", None)
            sync_closer = getattr(resource, "close", None)
            if async_closer is not None and callable(async_closer):
                await async_closer()
            elif sync_closer is not None and callable(sync_closer):
                result = await run_in_threadpool(sync_closer)
                if isawaitable(result):
                    await result
            else:
                raise TypeError(f"owned resource {resource!r} has no close or aclose method")
        except Exception as error:
            errors.append(error)
    if errors:
        raise ExceptionGroup("failed to close owned resources", errors)


def create_app(inbox: Inbox, core_data: CoreDataAdapter, edge_auth_secrets: dict[str, str], replay_guard: ReplayGuard,
               diagnostics: Diagnostics | None = None, command_bridge: CommandBridge | None = None, *,
               command_auth_token: str | None = None, command_targets: set[str] | None = None,
               max_body_bytes: int = MAX_BODY_BYTES, owned_resources: tuple[object, ...] = ()) -> FastAPI:
    if inbox is None or core_data is None or replay_guard is None:
        raise ValueError("inbox, core_data, and replay_guard are required")
    if not isinstance(max_body_bytes, int) or max_body_bytes < 1:
        raise ValueError("max_body_bytes must be positive")
    if command_bridge is not None and (not command_auth_token or not command_targets):
        raise ValueError("configured command bridge requires command_auth_token and command_targets")
    if command_auth_token is not None and not command_auth_token.isascii():
        raise ValueError("command_auth_token must be ASCII")
    authenticator = RequestAuthenticator(edge_auth_secrets, replay_guard)
    diagnostics = diagnostics or Diagnostics(120.0, set(edge_auth_secrets))
    diagnostics.configured_edges.update(edge_auth_secrets)
    resources_closed = False

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal resources_closed
        try:
            yield
        finally:
            if not resources_closed:
                resources_closed = True
                await close_owned_resources(owned_resources)

    app = FastAPI(lifespan=lifespan)


    async def body(request: Request) -> bytes:
        length = request.headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal():
                raise HTTPException(400, "invalid Content-Length")
            if int(length) > max_body_bytes:
                raise HTTPException(413, "request body too large")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > max_body_bytes:
                raise HTTPException(413, "request body too large")
            data.extend(chunk)
        return bytes(data)


    @app.get("/healthz")
    async def healthz() -> dict[str,str]: return {"status":"ok"}

    @app.get("/diagnostics")
    async def diagnostics_endpoint() -> JSONResponse:
        result=diagnostics.snapshot(); return JSONResponse(result,status_code=200 if result["healthy"] else 503)

    @app.post("/v1/ingest/events")
    async def ingest(request: Request,x_edge_id: str | None=Header(None),x_edge_timestamp: str | None=Header(None),x_edge_signature: str | None=Header(None)) -> JSONResponse:
        raw=await body(request); await run_in_threadpool(authenticator.verify, x_edge_id, x_edge_timestamp, x_edge_signature, raw)
        try:
            event=_strict_json(raw); canonical_event(event)
        except (ValueError,EventValidationError) as error: raise HTTPException(422,str(error)) from error
        try: record,inserted=await run_in_threadpool(inbox.reserve, x_edge_id, event)
        except EventConflict as error: raise HTTPException(409,str(error)) from error
        if record.state == "persisted": return JSONResponse({"edge_id":x_edge_id,"event_id":record.event_id,"status":"persisted","deduplicated":True}, status_code=201)
        if record.state == "conflict": raise HTTPException(409,f"event ID {record.event_id!r} conflicts with Core Data")
        action, ownership_token = await run_in_threadpool(inbox.begin_posting, x_edge_id, record.event_id, time.time())
        if action == "owned":
            return JSONResponse({"edge_id": x_edge_id, "event_id": record.event_id, "status": "processing",
                                 "deduplicated": not inserted}, status_code=202)
        if ownership_token is None:
            raise RuntimeError("inbox acquired posting state without an ownership token")
        if action == "recover":
            try:
                reconciliation = await core_data.reconcile_event(record.payload)
            except httpx.HTTPError as error:
                raise HTTPException(502, f"Core Data reconciliation failed: {error}") from error
            if reconciliation == "equal":
                await run_in_threadpool(inbox.mark_persisted, x_edge_id, record.event_id, ownership_token)
                return JSONResponse({"edge_id": x_edge_id, "event_id": record.event_id, "status": "persisted",
                                     "deduplicated": True}, status_code=201)
            if reconciliation == "conflict":
                await run_in_threadpool(inbox.mark_conflict, x_edge_id, record.event_id, ownership_token)
                raise HTTPException(409, f"event ID {record.event_id!r} conflicts with Core Data")
        try:
            await core_data.post_event(record.payload)
        except EventConflict as error:
            await run_in_threadpool(inbox.mark_conflict, x_edge_id, record.event_id, ownership_token)
            raise HTTPException(409, str(error)) from error
        except httpx.HTTPError as error:
            raise HTTPException(502, f"Core Data delivery failed: {error}") from error
        await run_in_threadpool(inbox.mark_persisted, x_edge_id, record.event_id, ownership_token)
        return JSONResponse({"edge_id":x_edge_id,"event_id":record.event_id,"status":"persisted","deduplicated":not inserted}, status_code=201)

    @app.post("/v1/heartbeats")
    async def heartbeat(request: Request,x_edge_id: str | None=Header(None),x_heartbeat_timestamp: str | None=Header(None),x_heartbeat_signature: str | None=Header(None)) -> dict[str,str]:
        raw=await body(request); await run_in_threadpool(authenticator.verify, x_edge_id, x_heartbeat_timestamp, x_heartbeat_signature, raw)
        try: diagnostics.update(Heartbeat.from_payload(x_edge_id,_strict_json(raw)))
        except (ValueError,json.JSONDecodeError) as error: raise HTTPException(422,str(error)) from error
        return {"status":"accepted"}

    @app.post("/v1/commands/{edge_id}/{device_name}")
    async def command(edge_id: str,device_name: str,request: Request,authorization: str | None=Header(None)) -> JSONResponse:
        raw=await body(request)
        if command_bridge is None: return JSONResponse({"edge_id":edge_id,"command_id":"","status":"failed","error":{"code":"command_unavailable","message":"command bridge is not configured"}},status_code=503)
        expected_authorization = f"Bearer {command_auth_token}".encode("ascii")
        if (edge_id not in command_targets or authorization is None or not authorization.isascii()
                or not hmac.compare_digest(expected_authorization, authorization.encode("ascii"))):
            raise HTTPException(401,"command authorization failed")
        try: payload=_strict_json(raw)
        except ValueError as error: raise HTTPException(422,str(error)) from error
        command_id=payload.get("command_id","") if isinstance(payload,dict) else ""
        def failure(code: str,message: str,status: int) -> JSONResponse: return JSONResponse({"edge_id":edge_id,"command_id":command_id,"status":"failed","error":{"code":code,"message":message}},status_code=status)
        try: command_request=command_from_payload(edge_id,device_name,payload)
        except CommandExpiredError as error: return failure("command_expired",str(error),504)
        except CommandError as error: return failure("invalid_command",str(error),400)
        try: return JSONResponse(await command_bridge.request(command_request))
        except CommandExpiredError as error: return failure("command_expired",str(error),504)
        except CommandUnavailableError as error: return failure("command_unavailable",str(error),503)
        except CommandError as error: return failure("invalid_command",str(error),400)
    return app
