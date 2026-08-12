import asyncio
import json
import sys
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from telemetry_plane.clients import EdgeGatewayClient
from telemetry_plane.gateway import (Diagnostics, Heartbeat, HTTPXCoreDataAdapter, MemoryInbox, MemoryReplayGuard,
                                     PostgreSQLInbox, PostgreSQLReplayGuard, RequestAuthenticator, close_owned_resources,
                                     create_app, request_signature)
from telemetry_plane.outbox import EdgeOutbox, EventConflict
from telemetry_plane.commands import CommandExpiredError, CommandUnavailableError


class CoreData:
    def __init__(self, failures=0):
        self.events = []
        self.failures = failures

    async def post_event(self, event):
        if self.failures:
            self.failures -= 1
            raise httpx.ConnectError("Core Data unavailable")
        self.events.append(event)

    async def reconcile_event(self, event):
        return "absent"


def edge_event(identifier="evt-1", reading=10):
    return {"apiVersion": "v3", "id": identifier, "deviceName": "camera-1", "profileName": "camera",
            "sourceName": "camera-1", "origin": 1, "readings": [{"id": "r1", "deviceName": "camera-1",
            "profileName": "camera", "resourceName": "image", "valueType": "Int64", "value": reading, "origin": 1}],
            "tags": {"site": "a"}}
def command_payload(edge_id="edge-a", device_name="camera", **overrides):
    now = time.time()
    payload = {
        "edge_id": edge_id,
        "device_name": device_name,
        "command_id": "cmd-1",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }
    payload.update(overrides)
    return payload



def gateway_app(*args, **kwargs):
    kwargs.setdefault("replay_guard", MemoryReplayGuard())
    return create_app(*args, **kwargs)


def request(app, method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


def signed_headers(edge_id, payload, secret="secret", timestamp=None, signature=None):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(time.time()) if timestamp is None else str(timestamp)
    return raw, {"content-type": "application/json", "X-Edge-Id": edge_id,
                 "X-Edge-Timestamp": timestamp,
                 "X-Edge-Signature": signature or request_signature(secret, edge_id, timestamp, raw)}


def ingest(app, edge_id, event, **kwargs):
    raw, headers = signed_headers(edge_id, event, **kwargs)
    return request(app, "POST", "/v1/ingest/events", content=raw, headers=headers)


def heartbeat_headers(edge_id, payload, timestamp=None):
    raw, headers = signed_headers(edge_id, payload, timestamp=timestamp)
    headers["X-Heartbeat-Timestamp"] = headers.pop("X-Edge-Timestamp")
    headers["X-Heartbeat-Signature"] = headers.pop("X-Edge-Signature")
    return raw, headers
class FakePsycopgConnection:
    def __init__(self, factory):
        self.factory = factory
        self.closed = False
        self.close_calls = 0
        self.schema_statements = []
        self.operation_statements = []
        self.failure = None
        self.failure_sql = None
        self.exit_failure = None
        self.close_failure = None
        self.block_operations = False
        self.operation_started = threading.Event()
        self.release_operation = threading.Event()
        self._operation_active = False
        self._operation_lock = threading.Lock()

    def execute(self, statement, parameters=None):
        self.schema_statements.append(statement)
        return SimpleNamespace(rowcount=1)

    def cursor(self):
        return FakePsycopgCursor(self)

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.exit_failure is not None:
            error, self.exit_failure = self.exit_failure, None
            raise error("transaction outcome is unknown")
        return False

    def close(self):
        self.close_calls += 1
        if self.close_failure is not None:
            error, self.close_failure = self.close_failure, None
            raise error("connection close failed")
        self.closed = True

    def operation(self, statement):
        self.operation_statements.append(statement)
        if self.failure is not None and self.failure_sql in statement:
            error, self.failure = self.failure, None
            raise error("connection is lost")
        if self.block_operations and not self.operation_started.is_set():
            with self._operation_lock:
                if self._operation_active:
                    raise AssertionError("concurrent operation used one connection")
                self._operation_active = True
            self.operation_started.set()
            assert self.release_operation.wait(timeout=2)
            with self._operation_lock:
                self._operation_active = False


class FakePsycopgCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = 1
        self._fetchone = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters=None):
        self.connection.operation(statement)
        if "SELECT state,EXTRACT" in statement:
            self._fetchone = ("reserved", None)
        elif "RETURNING state" in statement:
            self._fetchone = ("reserved",)

    def fetchone(self):
        return self._fetchone


class FakePsycopg:
    class OperationalError(Exception):
        pass

    class InterfaceError(Exception):
        pass

    class AdminShutdown(Exception):
        pass

    def __init__(self):
        self.errors = SimpleNamespace(AdminShutdown=self.AdminShutdown)
        self.connections = []

    def connect(self, dsn, autocommit):
        assert dsn == "postgres://telemetry"
        assert autocommit is True
        connection = FakePsycopgConnection(self)
        self.connections.append(connection)
        return connection


def fake_postgres(monkeypatch):
    psycopg = FakePsycopg()
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    return psycopg


STORE_CASES = [
    (PostgreSQLInbox, "INSERT INTO telemetry_inbox",
     lambda store: store.reserve("edge-a", edge_event()), 3),
    (PostgreSQLReplayGuard, "INSERT INTO telemetry_replay_guard",
     lambda store: store.claim("edge-a", "digest", 20, 10), 1),
]


@pytest.mark.parametrize(("storage_class", "operation_sql", "operation", "schema_count"), STORE_CASES)
@pytest.mark.parametrize("error_type", [
    FakePsycopg.OperationalError,
    FakePsycopg.InterfaceError,
    FakePsycopg.AdminShutdown,
])
def test_postgresql_stores_invalidate_each_disconnect_without_replaying_write(
        monkeypatch, storage_class, operation_sql, operation, schema_count, error_type):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    failed_connection = store.connection
    failed_connection.failure = error_type
    failed_connection.failure_sql = operation_sql

    with pytest.raises(error_type):
        operation(store)

    assert sum(operation_sql in statement for statement in failed_connection.operation_statements) == 1
    assert failed_connection.closed is True
    assert store.connection is None
    assert operation(store) is not None
    assert len(psycopg.connections) == 2
    assert len(psycopg.connections[1].schema_statements) == schema_count


@pytest.mark.parametrize(("storage_class", "operation_sql", "operation"), [
    (PostgreSQLInbox, "UPDATE telemetry_inbox SET",
     lambda store: store.begin_posting("edge-a", "event-id", 10)),
    (PostgreSQLReplayGuard, "INSERT INTO telemetry_replay_guard",
     lambda store: store.claim("edge-a", "digest", 20, 10)),
])
@pytest.mark.parametrize("error_type", [
    FakePsycopg.OperationalError,
    FakePsycopg.InterfaceError,
    FakePsycopg.AdminShutdown,
])
def test_postgresql_stores_do_not_replay_transaction_exit_ambiguity(
        monkeypatch, storage_class, operation_sql, operation, error_type):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    connection = store.connection
    connection.exit_failure = error_type

    with pytest.raises(error_type):
        operation(store)

    assert sum(operation_sql in statement for statement in connection.operation_statements) == 1
    assert connection.closed is True
    assert store.connection is None


@pytest.mark.parametrize(("storage_class", "operation_sql", "operation", "schema_count"), STORE_CASES)
def test_postgresql_stores_serialize_concurrent_first_reconnect_and_schema_initialization(
        monkeypatch, storage_class, operation_sql, operation, schema_count):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    failed_connection = store.connection
    failed_connection.failure = FakePsycopg.OperationalError
    failed_connection.failure_sql = operation_sql

    with pytest.raises(FakePsycopg.OperationalError):
        operation(store)

    results = []
    errors = []

    def run():
        try:
            results.append(operation(store))
        except Exception as error:
            errors.append(error)

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert not errors
    assert len(results) == 2
    assert len(psycopg.connections) == 2
    assert len(psycopg.connections[1].schema_statements) == schema_count


@pytest.mark.parametrize(("storage_class", "operation"), [
    (PostgreSQLInbox, lambda store: store.reserve("edge-a", edge_event())),
    (PostgreSQLReplayGuard, lambda store: store.claim("edge-a", "digest", 20, 10)),
])
def test_postgresql_stores_close_is_terminal_and_idempotent(monkeypatch, storage_class, operation):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    connection = store.connection

    store.close()
    store.close()

    assert connection.close_calls == 1
    assert store.connection is None
    with pytest.raises(RuntimeError, match="closed"):
        operation(store)
    assert len(psycopg.connections) == 1
@pytest.mark.parametrize(("storage_class", "operation", "schema_count"), [
    (PostgreSQLInbox, lambda store: store.reserve("edge-a", edge_event()), 3),
    (PostgreSQLReplayGuard, lambda store: store.claim("edge-a", "digest", 20, 10), 1),
])
def test_postgresql_stores_reconnect_preclosed_cached_connection_without_closing_it(
        monkeypatch, storage_class, operation, schema_count):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    stale_connection = store.connection
    stale_connection.closed = True

    assert operation(store) is not None

    assert stale_connection.close_calls == 0
    assert store.connection is psycopg.connections[1]
    assert len(psycopg.connections) == 2
    assert len(store.connection.schema_statements) == schema_count



@pytest.mark.parametrize(("storage_class", "operation"), [
    (PostgreSQLInbox, lambda store: store.reserve("edge-a", edge_event())),
    (PostgreSQLReplayGuard, lambda store: store.claim("edge-a", "digest", 20, 10)),
])
def test_postgresql_stores_propagate_close_failure_and_allow_close_retry(monkeypatch, storage_class, operation):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    connection = store.connection
    connection.close_failure = RuntimeError

    with pytest.raises(ExceptionGroup, match="failed to close"):
        asyncio.run(close_owned_resources((store,)))

    assert store.connection is connection
    with pytest.raises(RuntimeError, match="closed"):
        operation(store)
    store.close()
    assert connection.close_calls == 2
    assert store.connection is None


@pytest.mark.parametrize(("storage_class", "operation_sql", "operation"),
                         [(storage_class, operation_sql, operation)
                          for storage_class, operation_sql, operation, _ in STORE_CASES])
def test_postgresql_stores_preserve_primary_disconnect_error_when_discard_fails(
        monkeypatch, storage_class, operation_sql, operation):
    psycopg = fake_postgres(monkeypatch)
    store = storage_class("postgres://telemetry")
    connection = store.connection
    connection.failure = FakePsycopg.OperationalError
    connection.failure_sql = operation_sql
    connection.close_failure = RuntimeError

    with pytest.raises(FakePsycopg.OperationalError) as captured:
        operation(store)

    assert "failed to discard PostgreSQL connection" in captured.value.__notes__[0]
    assert store.connection is None
    assert connection.close_calls == 1

def test_gateway_persists_deduplicates_and_rejects_conflicting_event_id():
    core = CoreData()
    app = gateway_app(MemoryInbox(), core, edge_auth_secrets={"edge-a": "secret"})
    first = ingest(app, "edge-a", edge_event())
    assert first.status_code == 201
    assert first.json() == {"edge_id": "edge-a", "event_id": "evt-1", "status": "persisted", "deduplicated": False}
    duplicate = ingest(app, "edge-a", edge_event())
    assert duplicate.status_code == 201
    assert duplicate.json()["deduplicated"] is True
    assert len(core.events) == 1
    assert ingest(app, "edge-a", edge_event(reading=11)).status_code == 409

def test_gateway_offloads_blocking_inbox_work_without_changing_persistence_acknowledgements():
    class BlockingInbox(MemoryInbox):
        def __init__(self):
            super().__init__()
            self.reserve_started = threading.Event()
            self.release_reserve = threading.Event()

        def reserve(self, edge_id, event):
            self.reserve_started.set()
            assert self.release_reserve.wait(timeout=2)
            return super().reserve(edge_id, event)

    class BlockingCoreData(CoreData):
        def __init__(self):
            super().__init__()
            self.post_started = threading.Event()
            self.release_post = threading.Event()

        async def post_event(self, event):
            self.post_started.set()
            assert await asyncio.to_thread(self.release_post.wait, 2)
            self.events.append(event)

    async def run():
        inbox = BlockingInbox()
        core = BlockingCoreData()
        app = gateway_app(inbox, core, edge_auth_secrets={"edge-a": "secret"})
        event = edge_event("threadpool-boundary")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            raw, headers = signed_headers("edge-a", event, timestamp=time.time())
            first = asyncio.create_task(client.post("/v1/ingest/events", content=raw, headers=headers))
            assert await asyncio.to_thread(inbox.reserve_started.wait, 2)
            health = await asyncio.wait_for(client.get("/healthz"), timeout=0.2)
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}

            inbox.release_reserve.set()
            assert await asyncio.to_thread(core.post_started.wait, 2)
            raw, headers = signed_headers("edge-a", event, timestamp=time.time() + 1)
            processing = await client.post("/v1/ingest/events", content=raw, headers=headers)
            core.release_post.set()
            persisted = await first
            raw, headers = signed_headers("edge-a", event, timestamp=time.time() + 2)
            duplicate = await client.post("/v1/ingest/events", content=raw, headers=headers)
        return persisted, processing, duplicate, core

    persisted, processing, duplicate, core = asyncio.run(run())
    assert persisted.status_code == 201
    assert persisted.json() == {
        "edge_id": "edge-a", "event_id": "threadpool-boundary", "status": "persisted", "deduplicated": False,
    }
    assert processing.status_code == 202
    assert processing.json() == {
        "edge_id": "edge-a", "event_id": "threadpool-boundary", "status": "processing", "deduplicated": True,
    }
    assert duplicate.status_code == 201
    assert duplicate.json() == {
        "edge_id": "edge-a", "event_id": "threadpool-boundary", "status": "persisted", "deduplicated": True,
    }
    assert core.events == [edge_event("threadpool-boundary")]
def test_gateway_preserves_event_and_reading_provenance_without_rewriting():
    core = CoreData()
    app = gateway_app(MemoryInbox(), core, edge_auth_secrets={"edge-a": "secret"})
    event = edge_event("provenance")
    event["origin"] = 10
    event["readings"][0]["origin"] = 11

    assert ingest(app, "edge-a", event).status_code == 201
    persisted = core.events[0]

    assert persisted["id"] == "provenance"
    assert persisted["profileName"] == "camera"
    assert persisted["deviceName"] == "camera-1"
    assert persisted["sourceName"] == "camera-1"
    assert persisted["origin"] == 10
    assert persisted["readings"][0]["resourceName"] == "image"
    assert persisted["readings"][0]["origin"] == 11

def test_gateway_allows_same_event_id_from_another_authenticated_edge():
    core = CoreData()
    app = gateway_app(MemoryInbox(), core, edge_auth_secrets={"edge-a": "a", "edge-b": "b"})
    assert ingest(app, "edge-a", edge_event(), secret="a").status_code == 201
    assert ingest(app, "edge-b", edge_event(), secret="b").status_code == 201
    assert len(core.events) == 2


def test_gateway_rejects_unknown_edge_wrong_identity_replay_and_skew():
    app = gateway_app(MemoryInbox(), CoreData(), edge_auth_secrets={"edge-a": "secret"})
    event = edge_event()
    assert ingest(app, "unknown", event).status_code == 401
    raw, headers = signed_headers("edge-a", event)
    headers["X-Edge-Id"] = "edge-b"
    assert request(app, "POST", "/v1/ingest/events", content=raw, headers=headers).status_code == 401
    raw, headers = signed_headers("edge-a", event)
    assert request(app, "POST", "/v1/ingest/events", content=raw, headers=headers).status_code == 201
    assert request(app, "POST", "/v1/ingest/events", content=raw, headers=headers).status_code == 401
    assert ingest(app, "edge-a", edge_event("evt-2"), timestamp=time.time() - 301).status_code == 401


def test_core_data_failure_leaves_record_for_retry():
    core = CoreData(failures=1)
    app = gateway_app(MemoryInbox(), core, edge_auth_secrets={"edge-a": "secret"})
    assert ingest(app, "edge-a", edge_event()).status_code == 502
    retry = ingest(app, "edge-a", edge_event())
    assert retry.status_code == 202
    assert retry.json()["status"] == "processing"
    assert len(core.events) == 0


def test_core_data_adapter_maps_canonical_event_to_add_event_request():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(201)

    async def run():
        adapter = HTTPXCoreDataAdapter("http://core", "gateway", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        event = edge_event("stable-event")
        await adapter.post_event(event)
        await adapter.client.aclose()

    asyncio.run(run())
    assert requests[0].url.path == "/api/v3/event/gateway/camera/camera-1/camera-1"
    assert json.loads(requests[0].content) == {"apiVersion": "v3", "requestId": "stable-event", "event": edge_event("stable-event")}


def test_core_data_adapter_verifies_event_after_conflict():
    event = edge_event("stable-event")
    requests = []

    async def matching_handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(200, json={"apiVersion": "v3", "statusCode": 200, "event": event})

    async def mismatching_handler(request):
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(200, json={"apiVersion": "v3", "statusCode": 200, "event": edge_event("stable-event", reading=11)})

    async def run():
        adapter = HTTPXCoreDataAdapter(
            "http://core", "gateway", httpx.AsyncClient(transport=httpx.MockTransport(matching_handler))
        )
        await adapter.post_event(event)
        await adapter.client.aclose()

        conflicting = HTTPXCoreDataAdapter(
            "http://core", "gateway", httpx.AsyncClient(transport=httpx.MockTransport(mismatching_handler))
        )
        with pytest.raises(EventConflict):
            await conflicting.post_event(event)
        await conflicting.client.aclose()

    asyncio.run(run())
    assert [request.method for request in requests] == ["POST", "GET"]
    assert requests[1].url.path == "/api/v3/event/id/stable-event"
@pytest.mark.parametrize("status", [200, 202, 204])
def test_core_data_adapter_rejects_non_201_new_event_responses(status):
    async def handler(request):
        return httpx.Response(status, request=request)

    async def run():
        adapter = HTTPXCoreDataAdapter(
            "http://core", "gateway", httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.post_event(edge_event())
        await adapter.client.aclose()

    asyncio.run(run())





def test_diagnostics_marks_stale_heartbeat_unhealthy():
    diagnostics = Diagnostics(max_age_seconds=10)
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, diagnostics=diagnostics)
    payload = {"edge_id": "edge-a", "source_seen": True, "source_freshness_seconds": 1, "export_lag_seconds": 2,
               "outbox_oldest_seconds": 11, "observed_at": datetime.now(UTC).isoformat()}
    raw, headers = heartbeat_headers("edge-a", payload)
    assert request(app, "POST", "/v1/heartbeats", content=raw, headers=headers).status_code == 200
    response = request(app, "GET", "/diagnostics")
    assert response.status_code == 503
    assert response.json()["edges"]["edge-a"]["healthy"] is False
def test_diagnostics_rejects_old_producer_observation_despite_recent_receipt():
    diagnostics = Diagnostics(max_age_seconds=10, configured_edges={"edge-a"})
    diagnostics.update(
        Heartbeat.from_payload(
            "edge-a", {"edge_id": "edge-a", "source_seen": True, "source_freshness_seconds": 1,
                       "export_lag_seconds": 1, "outbox_oldest_seconds": 1,
                       "observed_at": "2020-01-01T00:00:00+00:00"}
        ),
        received_at=datetime.now(UTC),
    )
    snapshot = diagnostics.snapshot()
    edge = snapshot["edges"]["edge-a"]
    assert edge["healthy"] is False
    assert edge["receipt_age_seconds"] < 1
    assert edge["observation_age_seconds"] > diagnostics.max_age_seconds



def test_gateway_commands_return_correlated_unavailable_and_expired_terminal_errors():
    class FailingBridge:
        def __init__(self, error):
            self.error = error

        async def request(self, _):
            raise self.error

    payload = command_payload("edge-a", "camera-1")
    for error, status, code in (
        (CommandUnavailableError("edge command is unavailable and was not queued"), 503, "command_unavailable"),
        (CommandExpiredError("command TTL has expired"), 504, "command_expired"),
    ):
        response = request(
            gateway_app(MemoryInbox(), CoreData(), command_bridge=FailingBridge(error),
                        edge_auth_secrets={"edge-a": "secret"}, command_auth_token="command-token",
                        command_targets={"edge-a"}),
            "POST",
            "/v1/commands/edge-a/camera-1",
            json=payload,
            headers={"Authorization": "Bearer command-token"},
        )
        assert response.status_code == status
        assert response.json() == {
            "edge_id": "edge-a",
            "command_id": "cmd-1",
            "status": "failed",
            "error": {"code": code, "message": str(error)},
        }
def test_command_rejects_invalid_token_for_allowed_target():
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, command_bridge=object(),
                      command_auth_token="token", command_targets={"edge-a"})
    assert request(app, "POST", "/v1/commands/edge-a/camera", json=command_payload(),
                   headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_command_rejects_valid_token_for_denied_target():
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, command_bridge=object(),
                      command_auth_token="token", command_targets={"edge-a"})
    assert request(app, "POST", "/v1/commands/edge-b/camera", json=command_payload("edge-b", "camera"),
                   headers={"Authorization": "Bearer token"}).status_code == 401


def test_command_allows_valid_token_for_allowed_target():
    class Bridge:
        async def request(self, _):
            return {"edge_id": "edge-a", "command_id": "cmd-1", "status": "accepted"}

    payload = command_payload()
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, command_bridge=Bridge(),
                      command_auth_token="token", command_targets={"edge-a"})
    assert request(app, "POST", "/v1/commands/edge-a/camera", json=payload,
                   headers={"Authorization": "Bearer token"}).status_code == 200





class FakeClient:
    def __init__(self, response):
        self.response = response

    async def post(self, *args, **kwargs):
        return self.response


def test_client_retains_outbox_item_when_success_ack_is_malformed(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    outbox.enqueue(edge_event())
    client = object.__new__(EdgeGatewayClient)
    client.edge_id = "edge-a"
    client.edge_auth_secret = "secret"
    response = httpx.Response(200, json={"edge_id": "edge-a", "event_id": "evt-1", "status": "accepted", "deduplicated": False},
                              request=httpx.Request("POST", "https://gateway/v1/ingest/events"))
    client.client = FakeClient(response)
    assert asyncio.run(client.flush_one(outbox)) is False
    row = outbox.connection.execute("SELECT state, attempts FROM outbox WHERE event_id = 'evt-1'").fetchone()
    assert tuple(row) == ("pending", 1)
    outbox.close()
@pytest.mark.parametrize("ack", [
    {"edge_id": "edge-b", "event_id": "evt-1", "status": "persisted", "deduplicated": False},
    {"edge_id": "edge-a", "event_id": "evt-2", "status": "persisted", "deduplicated": False},
    {"edge_id": "edge-a", "event_id": "evt-1", "status": "processing", "deduplicated": False},
    {"edge_id": "edge-a", "event_id": "evt-1", "status": "persisted", "deduplicated": "false"},
])
def test_client_retains_outbox_item_for_every_persisted_ack_mismatch(tmp_path, ack):
    outbox = EdgeOutbox(tmp_path / "ack-mismatch.db")
    outbox.enqueue(edge_event())
    client = object.__new__(EdgeGatewayClient)
    client.edge_id = "edge-a"
    client.edge_auth_secret = "secret"
    client.client = FakeClient(httpx.Response(
        200, json=ack, request=httpx.Request("POST", "https://gateway/v1/ingest/events")
    ))
    assert asyncio.run(client.flush_one(outbox)) is False
    assert tuple(outbox.connection.execute("SELECT state, attempts FROM outbox").fetchone()) == ("pending", 1)
    outbox.close()



def test_client_retries_http_429_and_quarantines_http_422(tmp_path):
    retrying_outbox = EdgeOutbox(tmp_path / "retry.db")
    retrying_outbox.enqueue(edge_event())
    retrying_client = object.__new__(EdgeGatewayClient)
    retrying_client.edge_id = "edge-a"
    retrying_client.edge_auth_secret = "secret"
    retrying_client.client = FakeClient(httpx.Response(
        429, request=httpx.Request("POST", "https://gateway/v1/ingest/events")
    ))
    assert asyncio.run(retrying_client.flush_one(retrying_outbox)) is False
    row = retrying_outbox.connection.execute(
        "SELECT state, attempts FROM outbox WHERE event_id = 'evt-1'"
    ).fetchone()
    assert tuple(row) == ("pending", 1)

    rejected_outbox = EdgeOutbox(tmp_path / "rejected.db")
    rejected_outbox.enqueue(edge_event())
    rejected_client = object.__new__(EdgeGatewayClient)
    rejected_client.edge_id = "edge-a"
    rejected_client.edge_auth_secret = "secret"
    rejected_client.client = FakeClient(httpx.Response(
        422, request=httpx.Request("POST", "https://gateway/v1/ingest/events")
    ))
    assert asyncio.run(rejected_client.flush_one(rejected_outbox)) is False
    row = rejected_outbox.connection.execute(
        "SELECT state, attempts FROM outbox WHERE event_id = 'evt-1'"
    ).fetchone()
    assert tuple(row) == ("rejected", 0)
    retrying_outbox.close()
    rejected_outbox.close()
def test_client_deletes_only_exact_201_persisted_ack(tmp_path):
    outbox = EdgeOutbox(tmp_path / "ack.db")
    outbox.enqueue(edge_event())
    client = object.__new__(EdgeGatewayClient)
    client.edge_id = "edge-a"
    client.edge_auth_secret = "secret"
    client.client = FakeClient(httpx.Response(
        201, json={"edge_id": "edge-a", "event_id": "evt-1", "status": "persisted", "deduplicated": False},
        request=httpx.Request("POST", "https://gateway/v1/ingest/events"),
    ))
    assert asyncio.run(client.flush_one(outbox)) is True
    assert outbox.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    outbox.close()
@pytest.mark.parametrize("status", [200, 202])
def test_client_retries_matching_persisted_ack_unless_http_201(tmp_path, status):
    outbox = EdgeOutbox(tmp_path / f"ack-{status}.db")
    outbox.enqueue(edge_event())
    client = object.__new__(EdgeGatewayClient)
    client.edge_id = "edge-a"
    client.edge_auth_secret = "secret"
    client.client = FakeClient(httpx.Response(
        status, json={"edge_id": "edge-a", "event_id": "evt-1", "status": "persisted", "deduplicated": False},
        request=httpx.Request("POST", "https://gateway/v1/ingest/events"),
    ))
    assert asyncio.run(client.flush_one(outbox)) is False
    assert tuple(outbox.connection.execute("SELECT state, attempts FROM outbox").fetchone()) == ("pending", 1)
    outbox.close()




def test_gateway_rejects_malformed_event_nan_and_future_timestamp():
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"})
    malformed = edge_event()
    del malformed["readings"][0]["valueType"]
    assert ingest(app, "edge-a", malformed).status_code == 422
    raw = b'{"not":"strict","number":NaN}'
    timestamp = str(time.time())
    headers = {"X-Edge-Id": "edge-a", "X-Edge-Timestamp": timestamp,
               "X-Edge-Signature": request_signature("secret", "edge-a", timestamp, raw)}
    assert request(app, "POST", "/v1/ingest/events", content=raw, headers=headers).status_code == 422
    assert ingest(app, "edge-a", edge_event("future"), timestamp=time.time() + 301).status_code == 401
    duplicate = b'{"apiVersion":"v3","apiVersion":"v3"}'
    timestamp = str(time.time())
    duplicate_headers = {"X-Edge-Id": "edge-a", "X-Edge-Timestamp": timestamp,
                         "X-Edge-Signature": request_signature("secret", "edge-a", timestamp, duplicate)}
    assert request(app, "POST", "/v1/ingest/events", content=duplicate, headers=duplicate_headers).status_code == 422




def test_diagnostics_reports_configured_unseen_edge_and_command_denial():
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret", "edge-b": "other"})
    result = request(app, "GET", "/diagnostics")
    assert result.status_code == 503
    assert result.json()["edges"]["edge-b"] == {"healthy": False, "source_seen": False, "reason": "never_seen"}

    class Bridge:
        async def request(self, _):
            raise AssertionError("unauthorized command was forwarded")

    command_app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, command_bridge=Bridge(),
                              command_auth_token="token", command_targets={"edge-a"})
    assert request(command_app, "POST", "/v1/commands/edge-b/camera",
                   json=command_payload("edge-b", "camera")).status_code == 401
def test_expired_posting_reconciles_before_a_single_repost():
    class RecoveryCore:
        def __init__(self, result):
            self.result, self.posts = result, 0

        async def reconcile_event(self, _):
            return self.result

        async def post_event(self, _):
            self.posts += 1

    for reconciliation, status, posts in (("equal", 201, 0), ("absent", 201, 1), ("conflict", 409, 0)):
        inbox = MemoryInbox(lease_seconds=1)
        event = edge_event(f"recovery-{reconciliation}")
        inbox.reserve("edge-a", event)
        assert inbox.begin_posting("edge-a", event["id"], 0)[0] == "post"
        core = RecoveryCore(reconciliation)
        app = gateway_app(inbox, core, {"edge-a": "secret"})
        response = ingest(app, "edge-a", event)
        assert response.status_code == status
        assert core.posts == posts
def test_memory_inbox_allows_only_one_concurrent_post_owner():
    inbox = MemoryInbox()
    event = edge_event()
    inbox.reserve("edge-a", event)
    assert inbox.begin_posting("edge-a", event["id"], time.time())[0] == "post"
    assert inbox.begin_posting("edge-a", event["id"], time.time())[0] == "owned"
def test_memory_inbox_fences_expired_recovery_owner():
    inbox = MemoryInbox(lease_seconds=1)
    event = edge_event()
    inbox.reserve("edge-a", event)
    _, first_token = inbox.begin_posting("edge-a", event["id"], 0)
    action, recovery_token = inbox.begin_posting("edge-a", event["id"], 2)
    assert action == "recover"
    with pytest.raises(ValueError):
        inbox.mark_persisted("edge-a", event["id"], first_token)
    inbox.mark_persisted("edge-a", event["id"], recovery_token)


def test_memory_replay_guard_shares_claims_and_fails_closed_at_capacity():
    guard = MemoryReplayGuard(capacity=1)
    assert guard.claim("edge-a", "first", 100, 0)
    assert not guard.claim("edge-a", "first", 100, 0)
    assert not guard.claim("edge-a", "second", 100, 0)
    assert guard.claim("edge-a", "second", 200, 101)


def test_gateway_rejects_chunked_oversize_without_content_length():
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 4
            yield b"x" * 4

    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, max_body_bytes=7)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            return await client.post("/v1/commands/edge-a/camera", content=Chunks())

    assert asyncio.run(run()).status_code == 413
def test_future_dated_request_replay_claim_survives_its_accepted_window(monkeypatch):
    guard = MemoryReplayGuard()
    authenticator = RequestAuthenticator({"edge-a": "secret"}, guard, max_skew_seconds=10)
    issued_at = 1_000.0
    payload = b"{}"
    timestamp = str(issued_at + 9)
    signature = request_signature("secret", "edge-a", timestamp, payload)
    monkeypatch.setattr("telemetry_plane.gateway.time.time", lambda: issued_at)
    authenticator.verify("edge-a", timestamp, signature, payload)
    monkeypatch.setattr("telemetry_plane.gateway.time.time", lambda: issued_at + 11)
    with pytest.raises(Exception) as error:
        authenticator.verify("edge-a", timestamp, signature, payload)
    assert error.value.status_code == 401
    assert error.value.detail == "replayed request"


@pytest.mark.parametrize("timestamp, signature", [
    ("not-a-timestamp", "0" * 64),
    (str(time.time()), "not-a-signature"),
    ("１", "0" * 64),
    (str(time.time()), "é" * 64),
])
def test_authenticator_rejects_malformed_untrusted_header_text(timestamp, signature):
    authenticator = RequestAuthenticator({"edge-a": "secret"}, MemoryReplayGuard())
    with pytest.raises(Exception) as error:
        authenticator.verify("edge-a", timestamp, signature, b"{}")
    assert error.value.status_code == 401


def test_gateway_denies_malformed_ingest_heartbeat_and_command_credentials():
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, command_bridge=object(),
                      command_auth_token="token", command_targets={"edge-a"})
    event = edge_event()
    raw = json.dumps(event).encode()
    for path, headers in (
        ("/v1/ingest/events", {"X-Edge-Id": "edge-a", "X-Edge-Timestamp": "invalid", "X-Edge-Signature": "0" * 64}),
        ("/v1/heartbeats", {"X-Edge-Id": "edge-a", "X-Heartbeat-Timestamp": "invalid", "X-Heartbeat-Signature": "0" * 64}),
    ):
        assert request(app, "POST", path, content=raw, headers=headers).status_code == 401
    assert request(app, "POST", "/v1/commands/edge-a/camera", json=command_payload(),
                   headers={"Authorization": "Basic token"}).status_code == 401


def test_gateway_lifespan_closes_owned_dependencies_once():
    calls = []

    class SyncResource:
        def close(self):
            calls.append("sync")

    class AsyncResource:
        async def aclose(self):
            calls.append("async")

    class BridgeResource:
        def __init__(self):
            self.client = AsyncResource()

        async def aclose(self):
            await self.client.aclose()

        async def request(self, _):
            raise AssertionError("not called")

    sync = SyncResource()
    bridge = BridgeResource()
    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"}, command_bridge=bridge,
                      command_auth_token="token", command_targets={"edge-a"},
                      owned_resources=(sync, bridge, sync, None))

    async def run():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run())
    assert calls == ["async", "sync"]
def test_gateway_lifespan_attempts_all_owned_cleanup_after_failure():
    calls = []

    class Resource:
        def __init__(self, name, fails=False):
            self.name, self.fails = name, fails

        def close(self):
            calls.append(self.name)
            if self.fails:
                raise RuntimeError(self.name)

    app = gateway_app(MemoryInbox(), CoreData(), {"edge-a": "secret"},
                      owned_resources=(Resource("sync"), Resource("async", fails=True)))

    async def run():
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(ExceptionGroup, match="failed to close"):
        asyncio.run(run())
    assert calls == ["async", "sync"]
def test_close_owned_resources_rejects_missing_explicit_closer():
    class Wrapper:
        def __init__(self):
            self.client = object()

    async def run():
        await close_owned_resources((Wrapper(),))

    with pytest.raises(ExceptionGroup, match="failed to close"):
        asyncio.run(run())

def test_build_app_owns_and_closes_all_production_dependencies(monkeypatch):
    from telemetry_plane import main as gateway_main

    calls = []

    class Inbox:
        def __init__(self, _):
            pass

        def close(self):
            calls.append("inbox")

    class ReplayGuard:
        def __init__(self, _):
            pass

        def close(self):
            calls.append("replay")

    class CoreDataAdapter:
        def __init__(self, *_):
            pass

        async def close(self):
            calls.append("core")

    class CommandBridge:
        def __init__(self, *_args, **_kwargs):
            self.client = self

        async def aclose(self):
            calls.append("command")

    monkeypatch.setattr(gateway_main, "PostgreSQLInbox", Inbox)
    monkeypatch.setattr(gateway_main, "PostgreSQLReplayGuard", ReplayGuard)
    monkeypatch.setattr(gateway_main, "HTTPXCoreDataAdapter", CoreDataAdapter)
    monkeypatch.setattr(gateway_main, "HTTPSCommandBridge", CommandBridge)
    settings = SimpleNamespace(
        database_url="postgresql://unused",
        core_data_url="https://core",
        core_data_service_name="gateway",
        edge_auth_secrets={"edge-a": "secret"},
        command_enabled=True,
        command_endpoints={"edge-a": "https://edge:8443"},
        tls=object(),
        command_timeout_seconds=1,
        command_max_ttl_seconds=1,
        command_auth_token="token",
    )
    app = gateway_main.build_app(settings)

    async def run():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run())
    assert calls == ["command", "replay", "core", "inbox"]
