from app.joiner import FrameJoiner
from app.models import AccelerationFrame, AxisSample


def sample(origin: int, value: int) -> AxisSample:
    return AxisSample(origin=origin, value_type="Int32", value=value)


def test_joiner_emits_only_complete_same_origin_frames_once() -> None:
    joiner = FrameJoiner(pending_ttl_ns=10_000, max_pending=3)

    assert joiner.ingest("x", [sample(100, 1)], now_ns=100) == []
    assert joiner.ingest("y", [sample(100, 2)], now_ns=100) == []
    assert joiner.ingest("z", [sample(100, 3)], now_ns=100) == [
        AccelerationFrame(origin=100, x=1, y=2, z=3)
    ]
    assert joiner.ingest("z", [sample(100, 3)], now_ns=101) == []
    assert joiner.counters.duplicates_ignored == 1


def test_joiner_evicts_expired_and_capacity_bounded_pending_frames() -> None:
    joiner = FrameJoiner(pending_ttl_ns=10, max_pending=2)

    joiner.ingest(
        "x",
        [sample(1, 1), sample(2, 2), sample(3, 3)],
        now_ns=3,
    )
    assert joiner.pending_origins == [2, 3]

    joiner.ingest("y", [], now_ns=20)
    assert joiner.pending_origins == []
    assert joiner.counters.incomplete_frames_dropped == 3


def test_joiner_returns_completed_frames_in_origin_order() -> None:
    joiner = FrameJoiner(pending_ttl_ns=10_000, max_pending=3)
    joiner.ingest("x", [sample(100, 1), sample(200, 2)], now_ns=200)
    joiner.ingest("y", [sample(100, 3), sample(200, 4)], now_ns=200)

    frames = joiner.ingest(
        "z",
        [sample(200, 5), sample(100, 6)],
        now_ns=200,
    )

    assert [frame.origin for frame in frames] == [100, 200]
