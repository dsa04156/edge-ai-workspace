from datetime import datetime, timezone

import pytest

from app.discovery_models import StoredCandidate
from app.discovery_state import (
    InvalidDiscoveryTransition,
    initial_transition,
    transition_candidate,
)


def candidate() -> StoredCandidate:
    now = datetime.now(timezone.utc)
    return StoredCandidate(
        candidate_id="candidate-" + "a" * 64,
        identity_hash="a" * 64,
        source="node-scan",
        node_name="edge-1",
        protocol="serial",
        transport="usb-serial",
        display_name="Arduino",
        hardware_id="arduino-001",
        first_seen=now,
        last_seen=now,
        updated_at=now,
    )


def test_state_machine_accepts_only_explicit_path():
    item = candidate()
    initial_transition(item, reason="observed", actor="agent")
    transition_candidate(
        item,
        "IDENTIFIED",
        reason="exact match",
        actor="controller",
    )
    transition_candidate(
        item,
        "PENDING_APPROVAL",
        reason="operator review required",
        actor="controller",
    )
    transition_candidate(
        item,
        "APPROVED",
        reason="approved",
        actor="operator",
    )
    transition_candidate(
        item,
        "SERVICE_READY",
        reason="runtime ready",
        actor="saga",
    )
    transition_candidate(
        item,
        "METADATA_REGISTERED",
        reason="readback verified",
        actor="saga",
    )
    transition_candidate(
        item,
        "EVENT_CONFIRMED",
        reason="first event",
        actor="saga",
    )

    assert item.state == "EVENT_CONFIRMED"
    assert [entry.to_state for entry in item.transitions] == [
        "DETECTED",
        "IDENTIFIED",
        "PENDING_APPROVAL",
        "APPROVED",
        "SERVICE_READY",
        "METADATA_REGISTERED",
        "EVENT_CONFIRMED",
    ]


def test_state_machine_rejects_arbitrary_jump():
    item = candidate()
    with pytest.raises(InvalidDiscoveryTransition, match="not allowed"):
        transition_candidate(
            item,
            "EVENT_CONFIRMED",
            reason="invalid jump",
            actor="test",
        )
