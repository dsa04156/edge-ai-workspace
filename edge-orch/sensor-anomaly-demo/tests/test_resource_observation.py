from app.resource_observation import ProcessResourceTracker


def test_process_resource_tracker_reports_current_rss_and_interval_cpu_cores() -> None:
    wall_times = iter([10.0, 12.0])
    cpu_times = iter([4.0, 4.5])
    rss_values = iter([64 * 1024 * 1024, 72 * 1024 * 1024])
    tracker = ProcessResourceTracker(
        wall_clock=lambda: next(wall_times),
        cpu_clock=lambda: next(cpu_times),
        rss_reader=lambda: next(rss_values),
    )

    first = tracker.snapshot()
    second = tracker.snapshot()

    assert first.cpu_cores is None
    assert first.memory_rss_mib == 64
    assert first.metrics_valid is False
    assert second.cpu_cores == 0.25
    assert second.memory_rss_mib == 72
    assert second.sample_interval_seconds == 2
    assert second.metrics_valid is True
    assert second.source == "process-self"
    assert second.scope == "main-process"


def test_process_resource_tracker_fails_closed_when_proc_rss_is_unavailable() -> None:
    tracker = ProcessResourceTracker(
        wall_clock=lambda: 10.0,
        cpu_clock=lambda: 4.0,
        rss_reader=lambda: None,
    )

    snapshot = tracker.snapshot()

    assert snapshot.memory_rss_mib is None
    assert snapshot.metrics_valid is False


def test_process_resource_tracker_reuses_last_valid_cpu_for_rapid_status_calls() -> None:
    wall_times = iter([10.0, 12.0, 12.1])
    cpu_times = iter([4.0, 4.5, 5.0])
    tracker = ProcessResourceTracker(
        wall_clock=lambda: next(wall_times),
        cpu_clock=lambda: next(cpu_times),
        rss_reader=lambda: 64 * 1024 * 1024,
        minimum_interval_seconds=1.0,
    )

    tracker.snapshot()
    stable = tracker.snapshot()
    rapid = tracker.snapshot()

    assert stable.cpu_cores == 0.25
    assert rapid.cpu_cores == 0.25
    assert rapid.sample_interval_seconds == 2
    assert rapid.metrics_valid is True
