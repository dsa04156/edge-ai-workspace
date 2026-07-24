from datetime import datetime, timezone

import httpx

from app.auth import AllowAllMockProvider, ExternalSecurityApprovalClient
from app.discovery_models import StoredCandidate


def candidate() -> StoredCandidate:
    now = datetime.now(timezone.utc)
    return StoredCandidate(
        candidate_id="candidate-" + "d" * 64,
        identity_hash="d" * 64,
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


def test_development_mock_approves_explicitly():
    decision = AllowAllMockProvider().approve(
        candidate(),
        actor="tester",
        reason="integration test",
    )

    assert decision.approved is True
    assert decision.state == "approved"


def test_external_provider_fails_closed_on_denial_and_unavailable():
    denied = ExternalSecurityApprovalClient(
        "https://auth.example/approve",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"approved": False, "reason": "unknown hardware"},
            )
        ),
    ).approve(candidate(), actor="operator", reason="review")
    unavailable = ExternalSecurityApprovalClient(
        "https://auth.example/approve",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503)
        ),
    ).approve(candidate(), actor="operator", reason="review")

    assert denied.approved is False
    assert denied.state == "denied"
    assert unavailable.approved is False
    assert unavailable.state == "unavailable"
