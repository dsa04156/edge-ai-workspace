import asyncio

import pytest

from app.config import Settings
from app.local_data import (
    ACCELERATION_SOURCES,
    LocalDataSource,
    LocalDataUnavailable,
)
from app.models import AxisSample, InferenceRoutingStatus
from app.remote_inference import RoutedInference
from app.runtime import AnomalyRuntime
from app.storage import ResultStore


class FakeLocalDataClient:
    def __init__(self, rows: dict[str, list[AxisSample]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int | None, int]] = []
        self.closed = False

    async def fetch(
        self,
        source: LocalDataSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]:
        self.calls.append((source.key, from_origin, to_origin))
        return [
            row
            for row in self.rows[source.key]
            if (from_origin is None or row.origin >= from_origin)
            and row.origin <= to_origin
        ]

    async def close(self) -> None:
        self.closed = True


class ToggleFailureClient(FakeLocalDataClient):
    def __init__(self, rows: dict[str, list[AxisSample]]) -> None:
        super().__init__(rows)
        self.fail = False

    async def fetch(
        self,
        source: LocalDataSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]:
        if self.fail:
            raise LocalDataUnavailable(f"{source.key} unavailable")
        return await super().fetch(source, from_origin, to_origin)


class FakeApprovedRouter:
    def __init__(self) -> None:
        self.closed = False

    async def infer(self, frame, temperature, *, local, now=None):
        return RoutedInference(_remote_decision(frame.origin, temperature.value), "server1")

    def status(self, *, now=None) -> InferenceRoutingStatus:
        return InferenceRoutingStatus(
            configured_mode="approved",
            state="remote",
            effective_target="server1",
            approval_id="approval-001",
        )

    async def close(self) -> None:
        self.closed = True


def _remote_decision(origin: int, temperature: float):
    from app.model_adapter import ModelDecision
    from app.models import TemperatureFeatures, VibrationFeatures

    return ModelDecision(
        status="normal",
        score=0.5,
        vibration_score=0.4,
        temperature_score=0.7,
        vibration_features=VibrationFeatures(
            origin=origin,
            rms=1.0,
            peak=2.0,
            kurtosis=3.0,
            sample_count=20,
        ),
        temperature_features=TemperatureFeatures(
            origin=origin,
            raw=temperature,
            mean=temperature,
            stddev=0.0,
            delta=0.0,
            sample_count=10,
        ),
    )


def test_runtime_processes_joined_frame_once_and_advances_source_cursors() -> None:
    origin = 1_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [AxisSample(origin - 10_000_000, "Int32", 300)],
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1),
        client=client,
        sources=ACCELERATION_SOURCES,
    )

    asyncio.run(runtime.poll_once(now_ns=origin + 100))
    first = runtime.status(now_ns=origin + 100)
    asyncio.run(runtime.poll_once(now_ns=origin + 200))
    second = runtime.status(now_ns=origin + 200)

    assert first.mode == "live"
    assert first.latest is not None
    assert first.latest.origin == origin
    assert int(first.latest.observed_at.timestamp() * 1_000_000_000) == origin
    assert first.latest.values.model_dump() == {"x": 3, "y": 4, "z": 0}
    assert first.latest.magnitude == 5.0
    assert first.latest.component_scores is not None
    assert first.latest.temperature_features is not None
    assert first.latest.temperature_features.raw == 300
    assert first.latest.temperature_features.alignment_lag_ms == 10.0
    assert first.counters.frames_processed == 1
    assert second.counters.frames_processed == 1
    assert [call[1] for call in client.calls[4:7]] == [origin + 1] * 3
    assert client.calls[7][1] == origin - 9_999_999


def test_runtime_uses_explicitly_approved_remote_inference_result() -> None:
    origin = 1_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [AxisSample(origin - 10, "Int32", 300)],
        }
    )
    router = FakeApprovedRouter()
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1),
        client=client,
        sources=ACCELERATION_SOURCES,
        inference_router=router,
    )

    asyncio.run(runtime.poll_once(now_ns=origin + 100))
    state = runtime.status(now_ns=origin + 100)
    asyncio.run(runtime.stop())

    assert state.latest is not None
    assert state.latest.score == 0.5
    assert state.latest.inference_target == "server1"
    assert state.latest.augmentation_approval_id == "approval-001"
    assert state.inference_routing.effective_target == "server1"
    assert router.closed is True


def test_runtime_recovers_pending_acceleration_when_temperature_arrives_late() -> None:
    origin = 2_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [],
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1),
        client=client,
        sources=ACCELERATION_SOURCES,
    )

    asyncio.run(runtime.poll_once(now_ns=origin + 100))
    waiting = runtime.status(now_ns=origin + 100)

    assert waiting.latest is None
    assert waiting.input_state == "waiting"
    assert waiting.counters.frames_processed == 0

    client.rows["temperature"] = [AxisSample(origin - 10_000_000, "Int32", 301)]
    asyncio.run(runtime.poll_once(now_ns=origin + 200))
    recovered = runtime.status(now_ns=origin + 200)

    assert recovered.mode == "live"
    assert recovered.input_state == "fresh"
    assert recovered.latest is not None
    assert recovered.latest.origin == origin
    assert recovered.latest.temperature_features is not None
    assert recovered.latest.temperature_features.raw == 301
    assert recovered.latest.temperature_features.alignment_lag_ms == 10.0
    assert recovered.counters.frames_processed == 1
    assert recovered.counters.unaligned_frames_dropped == 0


def test_runtime_marks_stale_input_degraded_without_discarding_latest() -> None:
    origin = 1_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [AxisSample(origin - 10, "Int32", 300)],
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1, input_stale_seconds=1.0),
        client=client,
        sources=ACCELERATION_SOURCES,
    )
    asyncio.run(runtime.poll_once(now_ns=origin + 100))

    state = runtime.status(now_ns=origin + 1_000_000_001)

    assert state.status == "degraded"
    assert state.input_state == "stale"
    assert state.latest is not None
    assert state.latest.origin == origin


def test_runtime_isolates_repeated_input_errors_and_recovers() -> None:
    origin = 1_000_000_000
    next_origin = origin + 1_000
    client = ToggleFailureClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [AxisSample(origin - 10, "Int32", 300)],
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1),
        client=client,
        sources=ACCELERATION_SOURCES,
    )
    asyncio.run(runtime.poll_once(now_ns=origin + 100))

    client.fail = True
    for offset in range(3):
        asyncio.run(runtime.poll_once(now_ns=origin + 200 + offset))
    failed = runtime.status(now_ns=origin + 203)

    assert failed.status == "degraded"
    assert failed.input_state == "error"
    assert failed.latest is not None and failed.latest.origin == origin
    assert failed.counters.input_errors == 12
    assert failed.last_error == "LocalDataUnavailable: x unavailable"

    client.fail = False
    client.rows = {
        "x": [AxisSample(next_origin, "Int32", 4)],
        "y": [AxisSample(next_origin, "Int32", 3)],
        "z": [AxisSample(next_origin, "Int32", 0)],
        "temperature": [AxisSample(next_origin - 10, "Int32", 301)],
    }
    asyncio.run(runtime.poll_once(now_ns=next_origin + 100))
    recovered = runtime.status(now_ns=next_origin + 100)

    assert recovered.status == "normal"
    assert recovered.input_state == "fresh"
    assert recovered.latest is not None and recovered.latest.origin == next_origin
    assert recovered.last_error is None


def test_runtime_keeps_bounded_recent_results_in_origin_order() -> None:
    origins = [1_000_000_000, 1_000_000_001, 1_000_000_002]
    client = FakeLocalDataClient(
        {
            axis: [
                AxisSample(origin, "Int32", index + 1)
                for index, origin in enumerate(origins)
            ]
            for axis in ("x", "y", "z")
        }
        | {
            "temperature": [
                AxisSample(origin - 10, "Int32", 300 + index)
                for index, origin in enumerate(origins)
            ]
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1, recent_result_limit=2),
        client=client,
        sources=ACCELERATION_SOURCES,
    )
    asyncio.run(runtime.poll_once(now_ns=origins[-1] + 100))

    assert [result.origin for result in runtime.results(2)] == origins[-2:]
    with pytest.raises(ValueError, match="limit"):
        runtime.results(0)


def test_runtime_start_and_stop_manage_polling_worker_and_client() -> None:
    client = FakeLocalDataClient({"x": [], "y": [], "z": [], "temperature": []})
    runtime = AnomalyRuntime(
        settings=Settings(poll_interval_seconds=0.01),
        client=client,
        sources=ACCELERATION_SOURCES,
    )

    async def run() -> None:
        await runtime.start()
        await asyncio.sleep(0.025)
        assert runtime.worker_started is True
        await runtime.stop()

    asyncio.run(run())

    assert runtime.worker_started is False
    assert client.closed is True
    assert len(client.calls) >= 4


def test_runtime_fuses_vibration_and_temperature_scores_with_configured_weights() -> (
    None
):
    first_origin = 10_000_000_000
    second_origin = first_origin + 1_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(first_origin, "Int32", 3)],
            "y": [AxisSample(first_origin, "Int32", 4)],
            "z": [AxisSample(first_origin, "Int32", 0)],
            "temperature": [AxisSample(first_origin - 10, "Int32", 100)],
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(
            warmup_samples=1,
            anomaly_streak=1,
            vibration_window_samples=2,
            temperature_window_samples=2,
            vibration_weight=0.7,
            temperature_weight=0.3,
        ),
        client=client,
        sources=ACCELERATION_SOURCES,
    )
    asyncio.run(runtime.poll_once(now_ns=first_origin + 100))
    client.rows = {
        "x": [AxisSample(second_origin, "Int32", 300)],
        "y": [AxisSample(second_origin, "Int32", 400)],
        "z": [AxisSample(second_origin, "Int32", 0)],
        "temperature": [AxisSample(second_origin - 10, "Int32", 500)],
    }

    asyncio.run(runtime.poll_once(now_ns=second_origin + 100))
    state = runtime.status(now_ns=second_origin + 100)

    assert state.latest is not None
    assert state.latest.component_scores is not None
    expected = (
        state.latest.component_scores.vibration * 0.7
        + state.latest.component_scores.temperature * 0.3
    )
    assert state.latest.score == pytest.approx(expected)
    assert state.latest.weights is not None
    assert state.latest.weights.model_dump() == {
        "vibration": 0.7,
        "temperature": 0.3,
    }
    assert state.latest.vibration_features is not None
    assert state.latest.vibration_features.sample_count == 2
    assert state.latest.temperature_features is not None
    assert state.latest.temperature_features.sample_count == 2
    assert state.model.algorithm == "weighted-multi-sensor-feature-score-v1"
    assert set(state.model.components) == {"vibration", "temperature"}


def test_runtime_does_not_calculate_when_temperature_is_outside_alignment_window() -> (
    None
):
    origin = 10_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [AxisSample(origin - 3_000_000_000, "Int32", 300)],
        }
    )
    runtime = AnomalyRuntime(
        settings=Settings(
            warmup_samples=1,
            context_max_skew_seconds=1,
            pending_ttl_seconds=2,
        ),
        client=client,
        sources=ACCELERATION_SOURCES,
    )

    asyncio.run(runtime.poll_once(now_ns=origin + 100))
    assert runtime.status(now_ns=origin + 100).latest is None
    asyncio.run(runtime.poll_once(now_ns=origin + 2_000_000_101))
    state = runtime.status(now_ns=origin + 2_000_000_101)

    assert state.latest is None
    assert state.counters.unaligned_frames_dropped == 1
    assert state.last_error == "1 acceleration frame(s) lacked temperature context"


def test_runtime_does_not_publish_a_result_before_sqlite_commit(monkeypatch) -> None:
    origin = 12_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
            "temperature": [AxisSample(origin - 10, "Int32", 300)],
        }
    )
    store = ResultStore(":memory:", retention_rows=10)

    def fail_commit(*_, **__) -> None:
        raise RuntimeError("sqlite unavailable")

    monkeypatch.setattr(store, "record_result", fail_commit)
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1),
        client=client,
        sources=ACCELERATION_SOURCES,
        result_store=store,
    )

    with pytest.raises(RuntimeError, match="sqlite unavailable"):
        asyncio.run(runtime.poll_once(now_ns=origin + 100))

    state = runtime.status(now_ns=origin + 100)
    assert state.latest is None
    assert state.counters.frames_processed == 0
    asyncio.run(runtime.stop())
