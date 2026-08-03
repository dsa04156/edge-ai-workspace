from __future__ import annotations

import pytest

from tools.verify_sensor_service_demo import (
    Observation,
    ObservationError,
    ScenarioTracker,
    observation_from_payloads,
)


def observation(
    *,
    operating: str = "UP",
    freshness: str = "fresh",
    device_status: str = "available",
    mode: str = "live",
    status: str = "normal",
    input_state: str = "fresh",
    anomaly: bool | None = False,
    origin: int | None = 100,
    frames: int | None = 10,
    error: str | None = None,
) -> Observation:
    return Observation(
        observed_at="2026-08-03T00:00:00+00:00",
        device_operating_state=operating,
        device_freshness=freshness,
        device_status=device_status,
        demo_mode=mode,
        demo_status=status,
        demo_input_state=input_state,
        anomaly=anomaly,
        score=0.5,
        origin=origin,
        frames_processed=frames,
        observation_error=error,
    )


def test_anomaly_scenario_requires_normal_anomaly_and_newer_normal() -> None:
    tracker = ScenarioTracker("anomaly")

    tracker.consume(observation(origin=100, frames=10))
    tracker.consume(
        observation(status="anomaly", anomaly=True, origin=101, frames=11)
    )
    tracker.consume(observation(origin=102, frames=12))

    assert tracker.complete is True
    assert [item.phase for item in tracker.transitions] == [
        "WAITING_ANOMALY",
        "WAITING_CLEAR",
        "PASSED",
    ]


def test_anomaly_scenario_rejects_stale_trigger_and_reports_timeout_reason() -> None:
    tracker = ScenarioTracker("anomaly")

    tracker.consume(observation(origin=100, frames=10))
    tracker.consume(
        observation(status="anomaly", anomaly=True, origin=100, frames=11)
    )

    assert tracker.complete is False
    assert tracker.phase == "WAITING_ANOMALY"
    assert tracker.failure_reason() == "anomaly_not_observed"


def test_disconnect_scenario_requires_degradation_then_fresh_progress() -> None:
    tracker = ScenarioTracker("disconnect")

    tracker.consume(observation(origin=100, frames=10))
    tracker.consume(
        observation(
            operating="DOWN",
            freshness="stale",
            device_status="unavailable",
            status="degraded",
            input_state="stale",
            origin=100,
            frames=10,
        )
    )
    tracker.consume(observation(origin=110, frames=20))

    assert tracker.complete is True
    assert [item.phase for item in tracker.transitions] == [
        "WAITING_DISCONNECT",
        "WAITING_RECOVERY",
        "PASSED",
    ]


def test_disconnect_scenario_does_not_accept_recovery_without_new_data() -> None:
    tracker = ScenarioTracker("disconnect")
    tracker.consume(observation(origin=100, frames=10))
    tracker.consume(
        observation(
            operating="DOWN",
            freshness="stale",
            device_status="unavailable",
            origin=100,
            frames=10,
        )
    )

    tracker.consume(observation(origin=100, frames=10))

    assert tracker.complete is False
    assert tracker.phase == "WAITING_RECOVERY"
    assert tracker.failure_reason() == "fresh_recovery_not_observed"


def test_observation_from_payloads_preserves_authoritative_states() -> None:
    result = observation_from_payloads(
        {
            "mode": "live",
            "status": "normal",
            "input_state": "fresh",
            "observation_error": None,
            "latest": {"anomaly": False, "score": 1.25, "origin": 123},
            "counters": {"frames_processed": 42},
        },
        [
            {
                "name": "virtual-acceleration-x-001",
                "operating_state": "UP",
                "telemetry_freshness": "fresh",
                "overall_status": "available",
            }
        ],
        "virtual-acceleration-x-001",
    )

    assert result.device_healthy is True
    assert result.demo_healthy is True
    assert result.origin == 123
    assert result.frames_processed == 42
    assert result.score == 1.25


def test_observation_from_payloads_rejects_missing_device_and_bad_origin() -> None:
    with pytest.raises(ObservationError, match="was not found"):
        observation_from_payloads({}, [], "missing")

    with pytest.raises(ObservationError, match="latest.origin"):
        observation_from_payloads(
            {"latest": {"origin": "123"}},
            [{"name": "sensor"}],
            "sensor",
        )
