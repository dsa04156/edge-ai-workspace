from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.metrics import render_discovery_metrics


def test_metrics_report_state_attempt_failure_and_duration_totals():
    now = datetime.now(timezone.utc)
    inventory = SimpleNamespace(
        candidates=[
            SimpleNamespace(state="EVENT_CONFIRMED", presence="present"),
            SimpleNamespace(state="STALE", presence="stale"),
        ],
        nodes=[
            SimpleNamespace(scan_errors=["SERIAL_OPEN_FAILED"]),
        ],
    )
    registrations = [
        SimpleNamespace(
            attempt=2,
            status="EVENT_CONFIRMED",
            started_at=now,
            completed_at=now + timedelta(seconds=3),
        ),
        SimpleNamespace(
            attempt=1,
            status="FAILED",
            started_at=now,
            completed_at=None,
        ),
    ]

    metrics = render_discovery_metrics(inventory, registrations)

    assert "discovery_candidates_total 2" in metrics
    assert (
        'discovery_candidates_by_state{state="EVENT_CONFIRMED"} 1'
        in metrics
    )
    assert "registration_attempts_total 3" in metrics
    assert "registration_failures_total 2" in metrics
    assert "registration_duration_seconds_sum 3.000000" in metrics
    assert "discovery_plugin_errors_total 1" in metrics
    assert "stale_candidates_total 1" in metrics
