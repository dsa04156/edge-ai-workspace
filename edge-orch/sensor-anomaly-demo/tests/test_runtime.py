import asyncio

import pytest

from app.config import Settings
from app.local_data import ACCELERATION_SOURCES, AxisSource, LocalDataUnavailable
from app.models import AxisSample
from app.runtime import AnomalyRuntime


class FakeLocalDataClient:
    def __init__(self, rows: dict[str, list[AxisSample]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int | None, int]] = []
        self.closed = False

    async def fetch(
        self,
        source: AxisSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]:
        self.calls.append((source.axis, from_origin, to_origin))
        return [
            row
            for row in self.rows[source.axis]
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
        source: AxisSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]:
        if self.fail:
            raise LocalDataUnavailable(f"{source.axis} unavailable")
        return await super().fetch(source, from_origin, to_origin)


def test_runtime_processes_joined_frame_once_and_advances_source_cursors() -> None:
    origin = 1_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
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
    assert first.latest.values.model_dump() == {"x": 3, "y": 4, "z": 0}
    assert first.latest.magnitude == 5.0
    assert first.counters.frames_processed == 1
    assert second.counters.frames_processed == 1
    assert [call[1] for call in client.calls[3:]] == [origin + 1] * 3


def test_runtime_marks_stale_input_degraded_without_discarding_latest() -> None:
    origin = 1_000_000_000
    client = FakeLocalDataClient(
        {
            "x": [AxisSample(origin, "Int32", 3)],
            "y": [AxisSample(origin, "Int32", 4)],
            "z": [AxisSample(origin, "Int32", 0)],
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
    assert failed.counters.input_errors == 9
    assert failed.last_error == "LocalDataUnavailable: x unavailable"

    client.fail = False
    client.rows = {
        "x": [AxisSample(next_origin, "Int32", 4)],
        "y": [AxisSample(next_origin, "Int32", 3)],
        "z": [AxisSample(next_origin, "Int32", 0)],
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
            axis: [AxisSample(origin, "Int32", index + 1) for index, origin in enumerate(origins)]
            for axis in ("x", "y", "z")
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
    client = FakeLocalDataClient({"x": [], "y": [], "z": []})
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
    assert len(client.calls) >= 3
