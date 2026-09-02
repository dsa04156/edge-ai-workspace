from app.performance import PerformanceTracker


def test_performance_tracker_reports_latency_backlog_and_throughput() -> None:
    tracker = PerformanceTracker(window_seconds=300, minimum_samples=3)

    tracker.observe(processing_latency_ms=100, processed_frames=2, backlog=0, observed_at=0)
    tracker.observe(processing_latency_ms=300, processed_frames=2, backlog=1, observed_at=1)
    tracker.observe(processing_latency_ms=200, processed_frames=2, backlog=2, observed_at=2)

    metrics = tracker.snapshot(observed_at=2)

    assert metrics.metrics_valid is True
    assert metrics.processing_latency_p95_ms == 300
    assert metrics.backlog == 2
    assert metrics.throughput_per_second == 3.0
    assert metrics.sample_count == 3


def test_performance_tracker_marks_empty_and_stale_windows_invalid() -> None:
    tracker = PerformanceTracker(window_seconds=300, minimum_samples=3, stale_seconds=30)

    assert tracker.snapshot(observed_at=0).metrics_valid is False
    tracker.observe(processing_latency_ms=10, processed_frames=1, backlog=0, observed_at=0)
    tracker.observe(processing_latency_ms=20, processed_frames=1, backlog=0, observed_at=1)
    tracker.observe(processing_latency_ms=30, processed_frames=1, backlog=0, observed_at=2)

    assert tracker.snapshot(observed_at=33).metrics_valid is False
