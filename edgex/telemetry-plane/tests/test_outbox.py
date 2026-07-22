import json
import sqlite3
import threading

import pytest

from telemetry_plane.outbox import (
    EdgeOutbox,
    EventConflict,
    EventValidationError,
    OutboxCapacityExceeded,
    OutboxMigrationError,
    fingerprint,
    canonical_event,
)


def event(identifier="11111111-1111-4111-8111-111111111111", value=1, device="device-1", source="source-1"):
    return {
        "apiVersion": "v3",
        "id": identifier,
        "deviceName": device,
        "profileName": "profile-1",
        "sourceName": source,
        "origin": 100,
        "tags": {"site": "a"},
        "readings": [{
            "id": "22222222-2222-4222-8222-222222222222",
            "deviceName": device,
            "profileName": "profile-1",
            "resourceName": "value",
            "origin": 100,
            "valueType": "String" if isinstance(value, str) else "Int64",
            "value": value,
        }],
    }


def test_deduplicates_identical_event_and_rejects_conflict(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    assert outbox.enqueue(event()) is True
    assert outbox.enqueue(event()) is False
    with pytest.raises(EventConflict):
        outbox.enqueue(event(value=2))


def test_event_admission_rejects_malformed_stream_identity(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    for field, value in (("id", ""), ("deviceName", ""), ("sourceName", ""),
                         ("deviceName", None), ("sourceName", 1)):
        payload = event()
        payload[field] = value
        with pytest.raises(EventValidationError):
            outbox.enqueue(payload)
    assert outbox.diagnostics().pending_count == 0


def test_fingerprint_ignores_server_generated_fields_but_not_reading_value():
    original = event()
    server_enriched = json.loads(json.dumps(original))
    server_enriched["created"] = 101
    server_enriched["modified"] = 102
    server_enriched["readings"][0].update({"id": "reading-id", "created": 103, "modified": 104})
    assert fingerprint(server_enriched) == fingerprint(original)

    changed = json.loads(json.dumps(server_enriched))
    changed["readings"][0]["value"] = 2
    assert fingerprint(changed) != fingerprint(original)


def test_fingerprint_validates_stable_field_types():
    invalid = event()
    invalid["origin"] = "100"
    with pytest.raises(EventValidationError):
        fingerprint(invalid)
    invalid = event()
    invalid["tags"] = {"site": 1}
    with pytest.raises(EventValidationError):
        fingerprint(invalid)
    invalid = event()
    invalid["readings"] = {"value": 1}
    with pytest.raises(EventValidationError):
        fingerprint(invalid)


def test_concurrent_enqueue_is_durable_and_idempotent(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    results = []
    errors = []

    def enqueue() -> None:
        try:
            results.append(outbox.enqueue(event()))
        except Exception as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    threads = [threading.Thread(target=enqueue) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results.count(True) == 1
    assert results.count(False) == 15
    assert outbox.diagnostics().pending_count == 1


def test_persisted_delivery_removes_the_outbox_row(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    outbox.enqueue(event(), now=100)
    claimed = outbox.claim(now=100)
    assert claimed and claimed.attempts == 0
    outbox.delivered(claimed.event_id, claimed.claim_token, now=100)
    assert outbox.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    assert outbox.diagnostics(now=100).pending_count == 0
    assert outbox.claim(now=999) is None


def test_retries_with_backoff(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    outbox.enqueue(event(), now=100)
    claimed = outbox.claim(now=100)
    assert claimed
    assert outbox.failed(claimed.event_id, claimed.claim_token, "network unavailable", now=100) == 2
    assert outbox.claim(now=101) is None
    retried = outbox.claim(now=102)
    assert retried and retried.attempts == 1


def test_second_handle_preserves_unexpired_lease_and_expired_lease_recovers(tmp_path):
    path = tmp_path / "outbox.db"
    owner = EdgeOutbox(path, lease_seconds=10)
    owner.enqueue(event(), now=100)
    assert owner.claim(now=100)

    observer = EdgeOutbox(path, lease_seconds=10)
    assert observer.claim(now=101) is None
    assert observer.claim(now=110).event_id == "11111111-1111-4111-8111-111111111111"
    owner.close()
    observer.close()


def test_fifo_is_enforced_per_stream_without_blocking_other_streams(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    outbox.enqueue(event("a-1", device="a", source="s"), now=100)
    outbox.enqueue(event("b-1", device="b", source="s"), now=101)
    outbox.enqueue(event("a-2", device="a", source="s"), now=102)

    first = outbox.claim(now=102)
    assert first and first.event_id == "a-1"
    second = outbox.claim(now=102)
    assert second and second.event_id == "b-1"
    outbox.delivered(second.event_id, second.claim_token, now=102)
    assert outbox.failed(first.event_id, first.claim_token, "offline", now=102) == 2
    assert outbox.claim(now=103) is None  # a-2 cannot pass a-1's retry.
    retried = outbox.claim(now=104)
    assert retried and retried.event_id == "a-1"
    outbox.delivered(retried.event_id, retried.claim_token, now=104)
    assert outbox.claim(now=104).event_id == "a-2"


def test_legacy_migration_reconstructs_stream_metadata_and_sequences(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE outbox (
            event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at REAL NOT NULL,
            last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
        )"""
    )
    for identifier, created_at in (("first", 100), ("second", 101)):
        payload = event(identifier)
        connection.execute(
            "INSERT INTO outbox VALUES (?, ?, ?, 'pending', 0, ?, NULL, ?, ?)",
            (identifier, json.dumps(payload), fingerprint(payload), created_at, created_at, created_at),
        )
    connection.commit()
    connection.close()

    outbox = EdgeOutbox(path)
    rows = outbox.connection.execute(
        "SELECT stream_device, stream_source, stream_sequence, payload_bytes FROM outbox "
        "ORDER BY stream_sequence"
    ).fetchall()
    assert [(row["stream_device"], row["stream_source"], row["stream_sequence"]) for row in rows] == [
        ("device-1", "source-1", 1), ("device-1", "source-1", 2)
    ]
    assert all(row["payload_bytes"] > 0 for row in rows)


def test_legacy_migration_fails_for_unreconstructable_stream(tmp_path):
    path = tmp_path / "invalid-legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE outbox (
            event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at REAL NOT NULL,
            last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
        )"""
    )
    payload = {"id": "bad", "sourceName": "source"}
    connection.execute(
        "INSERT INTO outbox VALUES ('bad', ?, 'digest', 'pending', 0, 1, NULL, 1, 1)",
        (json.dumps(payload),),
    )
    connection.commit()
    connection.close()

    with pytest.raises(OutboxMigrationError):
        EdgeOutbox(path)


def test_capacity_rejection_preserves_unacknowledged_data_and_reports_diagnostics(tmp_path):
    payload = event(value="x" * 32)
    body_size = len(json.dumps(canonical_event(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    outbox = EdgeOutbox(tmp_path / "outbox.db", max_bytes=body_size)
    assert outbox.enqueue(payload, now=100)
    with pytest.raises(OutboxCapacityExceeded):
        outbox.enqueue(event("event-2", value="x"), now=101)
    diagnostics = outbox.diagnostics(now=110)
    assert diagnostics.pending_count == 1
    assert diagnostics.pending_bytes == body_size
    assert diagnostics.oldest_pending_age == 10


def test_rejected_record_releases_same_stream_and_has_operator_lifecycle(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db")
    outbox.enqueue(event("bad"), now=100)
    outbox.enqueue(event("next"), now=101)
    claimed = outbox.claim(now=101)
    assert claimed and claimed.event_id == "bad"
    outbox.reject(claimed.event_id, claimed.claim_token, "gateway rejected envelope", now=101)
    next_item = outbox.claim(now=101)
    assert next_item and next_item.event_id == "next"

    diagnostics = outbox.diagnostics(now=101)
    assert diagnostics.rejected_count == 1
    assert diagnostics.rejected_bytes > 0
    outbox.requeue_rejected("bad", now=102)
    assert outbox.diagnostics(now=102).rejected_count == 0
    outbox.delivered("next", next_item.claim_token, now=102)
    assert outbox.claim(now=102).event_id == "bad"


def test_rejected_records_consume_capacity_until_explicit_discard(tmp_path):
    payload = event(value="x" * 32)
    body_size = len(json.dumps(canonical_event(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    outbox = EdgeOutbox(tmp_path / "outbox.db", max_bytes=body_size)
    outbox.enqueue(payload, now=100)
    claimed = outbox.claim(now=100)
    assert claimed
    outbox.reject(claimed.event_id, claimed.claim_token, "invalid event", now=100)

    diagnostics = outbox.diagnostics(now=110)
    assert diagnostics.pending_count == 0
    assert diagnostics.pending_bytes == 0
    assert diagnostics.rejected_count == 1
    assert diagnostics.rejected_bytes == body_size
    with pytest.raises(OutboxCapacityExceeded):
        outbox.enqueue(event("event-2"), now=110)
    outbox.discard_rejected(claimed.event_id)
    assert outbox.diagnostics(now=110).pending_bytes == 0
    assert outbox.enqueue(event("event-2"), now=110)


def test_stream_sequence_remains_monotonic_after_delivery_and_reopen(tmp_path):
    path = tmp_path / "outbox.db"
    outbox = EdgeOutbox(path)
    outbox.enqueue(event("first"), now=100)
    claimed = outbox.claim(now=100)
    assert claimed and claimed.event_id == "first"
    outbox.delivered(claimed.event_id, claimed.claim_token, now=100)
    outbox.close()

    reopened = EdgeOutbox(path)
    reopened.enqueue(event("second"), now=101)
    row = reopened.connection.execute(
        "SELECT stream_sequence FROM outbox WHERE event_id = 'second'"
    ).fetchone()
    assert row["stream_sequence"] == 2
    reopened.close()
def test_canonical_bytes_variants_and_token_fence(tmp_path):
    outbox = EdgeOutbox(tmp_path / "outbox.db", lease_seconds=1)
    payload = event()
    payload["created"] = 1
    payload["readings"][0].update({"id": "core-id", "created": 2, "modified": 3})
    assert outbox.enqueue(payload, now=100)
    stored = outbox.connection.execute("SELECT payload FROM outbox").fetchone()["payload"]
    assert json.loads(stored) == canonical_event(payload)
    first = outbox.claim(now=100)
    assert first
    recovered = outbox.claim(now=101)
    assert recovered and recovered.claim_token != first.claim_token
    with pytest.raises(ValueError):
        outbox.delivered(first.event_id, first.claim_token)
    outbox.delivered(recovered.event_id, recovered.claim_token)

@pytest.mark.parametrize(("value_type", "field", "value"), [
    ("Bool", "value", True), ("String", "value", "text"),
    ("Binary", "binaryValue", "AA=="), ("Object", "objectValue", {"key": 1}),
])
def test_reading_variants_are_discriminated(value_type, field, value):
    payload = event()
    reading = payload["readings"][0]
    reading["valueType"] = value_type
    reading.pop("value")
    reading[field] = value
    assert canonical_event(payload)["readings"][0][field] == value

@pytest.mark.parametrize("mutation", [
    lambda payload: payload.update(apiVersion="v2"),
    lambda payload: payload.update(origin=-1),
    lambda payload: payload["readings"][0].update(origin=1.5),
    lambda payload: payload["readings"][0].update(deviceName="other"),
    lambda payload: payload["readings"][0].update(valueType="Binary"),
    lambda payload: payload["readings"][0].update(extra=True),
])
def test_canonical_event_rejects_ambiguous_or_invalid_models(mutation):
    payload = event()
    mutation(payload)
    with pytest.raises(EventValidationError):
        canonical_event(payload)

def test_legacy_migration_rejects_mismatched_id_and_recovers_inflight(tmp_path):
    path = tmp_path / "legacy-fenced.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE outbox (
        event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
        state TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at REAL NOT NULL,
        last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
    payload = event("legacy")
    connection.execute("INSERT INTO outbox VALUES (?, ?, 'old', 'inflight', 0, 1, NULL, 1, 1)",
                       ("legacy", json.dumps(payload)))
    connection.commit()
    connection.close()
    migrated = EdgeOutbox(path)
    row = migrated.connection.execute("SELECT state, lease_expires_at, payload FROM outbox").fetchone()
    assert row["state"] == "pending"
    assert row["lease_expires_at"] is None
    assert json.loads(row["payload"]) == canonical_event(payload)

    bad_path = tmp_path / "legacy-mismatched.db"
    connection = sqlite3.connect(bad_path)
    connection.execute("""CREATE TABLE outbox (
        event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
        state TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at REAL NOT NULL,
        last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
    connection.execute("INSERT INTO outbox VALUES ('row-id', ?, 'old', 'pending', 0, 1, NULL, 1, 1)",
                       (json.dumps(event("payload-id")),))
    connection.commit()
    connection.close()
    with pytest.raises(OutboxMigrationError):
        EdgeOutbox(bad_path)
@pytest.mark.parametrize(("value_type", "minimum", "maximum"), [
    ("Int8", -(2 ** 7), 2 ** 7 - 1), ("Int16", -(2 ** 15), 2 ** 15 - 1),
    ("Int32", -(2 ** 31), 2 ** 31 - 1), ("Int64", -(2 ** 63), 2 ** 63 - 1),
    ("Uint8", 0, 2 ** 8 - 1), ("Uint16", 0, 2 ** 16 - 1),
    ("Uint32", 0, 2 ** 32 - 1), ("Uint64", 0, 2 ** 64 - 1),
])
def test_canonical_readings_enforce_integer_widths(value_type, minimum, maximum):
    payload = event()
    payload["readings"][0].update(valueType=value_type, value=minimum)
    assert canonical_event(payload)["readings"][0]["value"] == minimum
    payload["readings"][0]["value"] = maximum
    assert canonical_event(payload)["readings"][0]["value"] == maximum
    for overflow in (minimum - 1, maximum + 1):
        payload["readings"][0]["value"] = overflow
        with pytest.raises(EventValidationError):
            canonical_event(payload)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_canonical_readings_reject_nonfinite_float_values(value):
    payload = event()
    payload["readings"][0].update(valueType="Float64", value=value)
    with pytest.raises(EventValidationError):
        canonical_event(payload)
@pytest.mark.parametrize("value", [-3.4028234663852886e38, 3.4028234663852886e38])
def test_canonical_readings_accept_float32_finite_boundaries(value):
    payload = event()
    payload["readings"][0].update(valueType="Float32", value=value)
    assert canonical_event(payload)["readings"][0]["value"] == value


@pytest.mark.parametrize(("value_type", "value"), [
    ("Float32", -3.402823466385289e38),
    ("Float32", 3.402823466385289e38),
    ("Float32", 10 ** 400),
    ("Float64", 10 ** 400),
])
def test_canonical_readings_reject_float_width_overflow_as_validation_error(value_type, value):
    payload = event()
    payload["readings"][0].update(valueType=value_type, value=value)
    with pytest.raises(EventValidationError):
        canonical_event(payload)


def test_canonical_readings_accept_float64_finite_boundary():
    payload = event()
    maximum = float.fromhex("0x1.fffffffffffffp+1023")
    payload["readings"][0].update(valueType="Float64", value=maximum)
    assert canonical_event(payload)["readings"][0]["value"] == maximum




def test_rebuilds_check_constrained_legacy_table_into_canonical_schema(tmp_path):
    path = tmp_path / "check-constrained.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE outbox (
        event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
        stream_device TEXT NOT NULL DEFAULT '', stream_source TEXT NOT NULL DEFAULT '',
        stream_sequence INTEGER NOT NULL DEFAULT 0, payload_bytes INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL CHECK(state = 'pending'), attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at REAL NOT NULL, lease_expires_at REAL, lease_token INTEGER NOT NULL DEFAULT 0,
        last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""")
    payload = event("legacy")
    connection.execute("""INSERT INTO outbox (
        event_id, payload, fingerprint, stream_device, stream_source, stream_sequence,
        state, attempts, next_attempt_at, created_at, updated_at
    ) VALUES (?, ?, 'stale', 'device-1', 'source-1', 1, 'pending', 0, 1, 1, 1)""",
                       ("legacy", json.dumps(payload)))
    connection.commit()
    connection.close()

    outbox = EdgeOutbox(path)
    schema = outbox.connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'outbox'"
    ).fetchone()[0]
    row = outbox.connection.execute(
        "SELECT payload, fingerprint, stream_sequence, payload_bytes FROM outbox"
    ).fetchone()
    assert "CHECK(state IN ('pending', 'inflight', 'delivered', 'rejected'))" in schema
    assert json.loads(row["payload"]) == canonical_event(payload)
    assert row["fingerprint"] == fingerprint(payload)
    assert row["stream_sequence"] == 1
    assert row["payload_bytes"] > 0
def test_near_canonical_rebuild_preserves_existing_stream_fifo_sequences(tmp_path):
    path = tmp_path / "near-canonical.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE outbox (
        event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
        stream_device TEXT NOT NULL, stream_source TEXT NOT NULL, stream_sequence INTEGER NOT NULL,
        payload_bytes INTEGER NOT NULL, state TEXT NOT NULL CHECK(state = 'pending'),
        attempts INTEGER NOT NULL, next_attempt_at REAL NOT NULL, lease_expires_at REAL,
        lease_token INTEGER NOT NULL, last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""")
    for identifier, sequence, created_at in (("later-sequence", 2, 100), ("first-sequence", 1, 101)):
        payload = event(identifier)
        connection.execute("""INSERT INTO outbox VALUES (
            ?, ?, 'stale', 'device-1', 'source-1', ?, 1, 'pending', 0, ?, NULL, 0, NULL, ?, ?
        )""", (identifier, json.dumps(payload), sequence, created_at, created_at, created_at))
    connection.commit()
    connection.close()

    outbox = EdgeOutbox(path)
    rows = outbox.connection.execute(
        "SELECT event_id, stream_sequence FROM outbox ORDER BY event_id"
    ).fetchall()
    assert [(row["event_id"], row["stream_sequence"]) for row in rows] == [
        ("first-sequence", 1), ("later-sequence", 2)
    ]
    first = outbox.claim(now=101)
    assert first and first.event_id == "first-sequence"
    outbox.delivered(first.event_id, first.claim_token, now=101)
    second = outbox.claim(now=101)
    assert second and second.event_id == "later-sequence"



def test_legacy_rebuild_rejects_unknown_state_without_swapping_tables(tmp_path):
    path = tmp_path / "unknown-state.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE outbox (
        event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending', 'unknown')), attempts INTEGER NOT NULL,
        next_attempt_at REAL NOT NULL, last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
    )""")
    payload = event("legacy")
    connection.execute(
        "INSERT INTO outbox VALUES (?, ?, 'stale', 'unknown', 0, 1, NULL, 1, 1)",
        ("legacy", json.dumps(payload)),
    )
    connection.commit()
    connection.close()

    with pytest.raises(OutboxMigrationError):
        EdgeOutbox(path)
    original = sqlite3.connect(path)
    assert original.execute("SELECT state FROM outbox").fetchone()[0] == "unknown"
    original.close()
