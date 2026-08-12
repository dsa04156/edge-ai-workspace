from datetime import datetime, timezone

import pytest

from app.discovery_models import (
    CandidateRegistryDocument,
    DiscoveryPlan,
    RegistrationRecord,
    StoredCandidate,
)
from app.discovery_store import DiscoveryStoreError, SQLiteDiscoveryStore


def registry() -> CandidateRegistryDocument:
    now = datetime.now(timezone.utc)
    return CandidateRegistryDocument(
        candidates=[
            StoredCandidate(
                candidate_id="candidate-" + "b" * 64,
                identity_hash="b" * 64,
                source="node-scan",
                node_name="edge-1",
                protocol="serial",
                transport="usb-serial",
                display_name="Simulator",
                hardware_id="sim-001",
                first_seen=now,
                last_seen=now,
                updated_at=now,
            )
        ]
    )


def test_sqlite_store_recovers_candidate_plan_and_saga_after_restart(tmp_path):
    path = tmp_path / "discovery.db"
    first = SQLiteDiscoveryStore(path)
    first.save_registry(registry())
    now = datetime.now(timezone.utc)
    first.put_plan(DiscoveryPlan(node_id="edge-1", updated_at=now))
    first.put_registration(
        RegistrationRecord(
            candidate_id="candidate-" + "b" * 64,
            status="SERVICE_READY",
            step="SERVICE_READY",
            started_at=now,
            updated_at=now,
        )
    )
    first.close()

    second = SQLiteDiscoveryStore(path)

    assert second.load_registry()["candidates"][0]["hardwareId"] == "sim-001"
    assert second.get_plan("edge-1").node_id == "edge-1"
    assert (
        second.get_registration("candidate-" + "b" * 64).step
        == "SERVICE_READY"
    )


def test_sqlite_idempotency_rejects_reused_request_with_new_payload(tmp_path):
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    store.put_idempotent_response("approve:x", "a" * 64, "b" * 64, {"ok": True})

    assert store.get_idempotent_response(
        "approve:x", "a" * 64, "b" * 64
    ) == {"ok": True}
    with pytest.raises(DiscoveryStoreError, match="another payload"):
        store.get_idempotent_response(
            "approve:x",
            "a" * 64,
            "c" * 64,
        )


def test_legacy_configmap_registry_is_imported_once(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    legacy = {
        "version": 1,
        "nodes": [],
        "candidates": [
            {
                "candidateId": "candidate-" + "e" * 24,
                "identityHash": "e" * 64,
                "source": "node-scan",
                "nodeName": "edge-1",
                "protocol": "serial",
                "transport": "usb-serial",
                "displayName": "Legacy Arduino",
                "decision": "pending",
                "firstSeen": now,
                "lastSeen": now,
                "updatedAt": now,
            }
        ],
    }

    assert store.import_legacy_registry(legacy) is True
    assert store.import_legacy_registry({"version": 1}) is False
    imported = CandidateRegistryDocument.model_validate(store.load_registry())

    assert imported.version == 2
    assert imported.candidates[0].state == "DETECTED"
    assert imported.candidates[0].candidate_id == (
        "candidate-" + "e" * 24
    )


def test_empty_legacy_registry_is_still_marked_as_imported(tmp_path):
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")

    assert store.import_legacy_registry(
        {"version": 1, "nodes": [], "candidates": []}
    ) is True
    assert store.import_legacy_registry(
        registry().model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
    ) is False
    assert store.load_registry()["candidates"] == []
