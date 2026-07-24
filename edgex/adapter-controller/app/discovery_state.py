from __future__ import annotations

from datetime import datetime, timezone

from .discovery_models import CandidateTransition, DiscoveryState, StoredCandidate


class InvalidDiscoveryTransition(ValueError):
    """A candidate state transition is not part of the approved state machine."""


ALLOWED_TRANSITIONS: dict[DiscoveryState, frozenset[DiscoveryState]] = {
    "DETECTED": frozenset({"IDENTIFIED", "BLOCKED", "STALE"}),
    "IDENTIFIED": frozenset({"PENDING_APPROVAL", "BLOCKED", "STALE"}),
    "PENDING_APPROVAL": frozenset(
        {"APPROVED", "REJECTED", "BLOCKED", "STALE"}
    ),
    "APPROVED": frozenset({"SERVICE_READY", "BLOCKED", "FAILED", "STALE"}),
    "SERVICE_READY": frozenset({"METADATA_REGISTERED", "FAILED", "STALE"}),
    "METADATA_REGISTERED": frozenset(
        {"EVENT_CONFIRMED", "FAILED", "STALE"}
    ),
    "EVENT_CONFIRMED": frozenset({"STALE", "FAILED"}),
    "BLOCKED": frozenset({"PENDING_APPROVAL", "REJECTED", "STALE"}),
    "REJECTED": frozenset({"PENDING_APPROVAL", "STALE"}),
    "STALE": frozenset(
        {
            "DETECTED",
            "IDENTIFIED",
            "PENDING_APPROVAL",
            "APPROVED",
            "SERVICE_READY",
            "METADATA_REGISTERED",
            "EVENT_CONFIRMED",
            "BLOCKED",
            "REJECTED",
            "FAILED",
        }
    ),
    "FAILED": frozenset({"APPROVED", "REJECTED", "STALE"}),
}


def transition_candidate(
    candidate: StoredCandidate,
    to_state: DiscoveryState,
    *,
    reason: str,
    actor: str,
    error_code: str | None = None,
    occurred_at: datetime | None = None,
) -> CandidateTransition:
    current = candidate.state
    if current == to_state:
        raise InvalidDiscoveryTransition(
            f"candidate is already in state {to_state}"
        )
    if to_state not in ALLOWED_TRANSITIONS[current]:
        raise InvalidDiscoveryTransition(
            f"transition {current} -> {to_state} is not allowed"
        )
    timestamp = occurred_at or datetime.now(timezone.utc)
    transition = CandidateTransition(
        from_state=current,
        to_state=to_state,
        reason=reason,
        actor=actor,
        occurred_at=timestamp,
        error_code=error_code,
    )
    if to_state == "STALE":
        candidate.resume_state = current
    elif current == "STALE":
        candidate.resume_state = None
    candidate.state = to_state
    candidate.updated_at = timestamp
    candidate.transitions.append(transition)
    return transition


def initial_transition(
    candidate: StoredCandidate,
    *,
    reason: str,
    actor: str,
) -> CandidateTransition:
    transition = CandidateTransition(
        from_state=None,
        to_state=candidate.state,
        reason=reason,
        actor=actor,
        occurred_at=candidate.first_seen,
    )
    candidate.transitions.append(transition)
    return transition


def restore_state(candidate: StoredCandidate) -> DiscoveryState:
    return candidate.resume_state or "DETECTED"
