from datetime import datetime, timedelta, timezone

from app.models import AxisValues, LatestObservation
from app.storage import ResultStore


def observation(origin: int, *, anomaly: bool, score: float) -> LatestObservation:
    return LatestObservation(
        origin=origin,
        observed_at=datetime(2026, 8, 3, tzinfo=timezone.utc)
        + timedelta(seconds=origin),
        values=AxisValues(x=1, y=2, z=3),
        magnitude=3.741657,
        score=score,
        anomaly=anomaly,
        model_version="baseline-test-v1",
    )


def test_store_persists_results_and_alert_open_clear_idempotently(tmp_path) -> None:
    path = tmp_path / "results.db"
    store = ResultStore(str(path), retention_rows=10)

    assert (
        store.record_result(observation(1, anomaly=False, score=0.1), asset_id="pump-1")
        is None
    )
    opened = store.record_result(
        observation(2, anomaly=True, score=5.0), asset_id="pump-1"
    )
    duplicate = store.record_result(
        observation(2, anomaly=True, score=5.0), asset_id="pump-1"
    )
    cleared = store.record_result(
        observation(3, anomaly=False, score=0.2), asset_id="pump-1"
    )

    assert opened is not None and opened.transition == "opened"
    assert cleared is not None and cleared.transition == "cleared"
    assert cleared.alert_id == opened.alert_id
    assert duplicate is None
    assert [row.origin for row in store.results(10)] == [1, 2, 3]
    assert [row.transition for row in store.alerts(10)] == ["cleared", "opened"]
    assert store.status().result_count == 3
    assert store.status().alert_event_count == 2
    assert store.status().open_alert_count == 0
    store.close()

    reopened = ResultStore(str(path), retention_rows=10)
    assert [row.origin for row in reopened.results(10)] == [1, 2, 3]
    assert reopened.status().durable is True
    reopened.close()


def test_store_retention_and_filters_are_bounded() -> None:
    store = ResultStore(":memory:", retention_rows=2)
    for origin, anomaly in ((1, False), (2, True), (3, False)):
        store.record_result(
            observation(origin, anomaly=anomaly, score=float(origin)),
            asset_id="pump-1",
        )

    assert [row.origin for row in store.results(10)] == [2, 3]
    assert [row.origin for row in store.results(10, anomaly=True)] == [2]
    assert [row.origin for row in store.results(10, from_origin=3)] == [3]
    assert store.status().retention_rows == 2
    assert store.status().durable is False
    store.close()


def test_open_alert_state_survives_restart_and_closes_once(tmp_path) -> None:
    path = tmp_path / "results.db"
    first = ResultStore(str(path), retention_rows=10)
    opened = first.record_result(
        observation(1, anomaly=True, score=6.0),
        asset_id="pump-1",
    )
    assert opened is not None
    first.close()

    second = ResultStore(str(path), retention_rows=10)
    assert second.status().open_alert_count == 1
    cleared = second.record_result(
        observation(2, anomaly=False, score=0.1),
        asset_id="pump-1",
    )
    assert cleared is not None and cleared.alert_id == opened.alert_id
    assert second.status().open_alert_count == 0
    second.close()
