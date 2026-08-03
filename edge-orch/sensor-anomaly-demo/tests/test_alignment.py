from app.alignment import TemporalAligner
from app.models import AccelerationFrame, AxisSample


def frame(origin: int) -> AccelerationFrame:
    return AccelerationFrame(origin=origin, x=1, y=2, z=3)


def temperature(origin: int, value: int = 300) -> AxisSample:
    return AxisSample(origin=origin, value_type="Int32", value=value)


def test_aligner_uses_nearest_context_with_earlier_sample_as_tie_breaker() -> None:
    aligner = TemporalAligner(
        max_skew_ns=10,
        pending_ttl_ns=100,
        max_pending=10,
    )

    aligned = aligner.ingest(
        [frame(100)],
        [temperature(95), temperature(105)],
        now_ns=110,
    )

    assert len(aligned) == 1
    assert aligned[0].temperature.origin == 95


def test_aligner_holds_then_drops_frame_without_bounded_context() -> None:
    aligner = TemporalAligner(
        max_skew_ns=10,
        pending_ttl_ns=20,
        max_pending=2,
    )

    assert aligner.ingest([frame(100)], [temperature(50)], now_ns=100) == []
    assert aligner.pending_origins == [100]
    assert aligner.ingest([], [], now_ns=121) == []
    assert aligner.pending_origins == []
    assert aligner.counters.unaligned_frames_dropped == 1


def test_aligner_reuses_low_rate_context_for_multiple_frames() -> None:
    aligner = TemporalAligner(
        max_skew_ns=10,
        pending_ttl_ns=100,
        max_pending=10,
    )

    aligned = aligner.ingest(
        [frame(100), frame(104)],
        [temperature(99)],
        now_ns=105,
    )

    assert [row.acceleration.origin for row in aligned] == [100, 104]
    assert [row.temperature.origin for row in aligned] == [99, 99]


def test_aligner_matches_recent_cache_before_wall_clock_context_eviction() -> None:
    aligner = TemporalAligner(
        max_skew_ns=10,
        pending_ttl_ns=20,
        max_pending=10,
    )

    aligned = aligner.ingest(
        [frame(100)],
        [temperature(99)],
        now_ns=1_000,
    )

    assert len(aligned) == 1
    assert aligned[0].temperature.origin == 99
    assert aligner.counters.unaligned_frames_dropped == 0
