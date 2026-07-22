from app.detector import DetectorConfig, OnlineGaussianDetector
from app.models import AccelerationFrame


def frame(origin: int, x: int, y: int = 0, z: int = 0) -> AccelerationFrame:
    return AccelerationFrame(origin=origin, x=x, y=y, z=z)


def test_detector_uses_vector_magnitude_and_finishes_warmup() -> None:
    detector = OnlineGaussianDetector(
        DetectorConfig(warmup_samples=2, stddev_floor=2.0)
    )

    first = detector.process(frame(1, 3, 4))
    ready = detector.process(frame(2, 3, 4))

    assert first.status == "warming_up"
    assert ready.status == "normal"
    assert ready.magnitude == 5.0
    assert ready.score == 0.0
    assert detector.snapshot().sample_count == 2


def test_detector_requires_streaks_to_enter_and_clear_anomaly() -> None:
    detector = OnlineGaussianDetector(
        DetectorConfig(
            warmup_samples=3,
            threshold=4.0,
            stddev_floor=1.0,
            anomaly_streak=2,
            clear_streak=3,
        )
    )
    for origin in range(1, 4):
        detector.process(frame(origin, 10))

    assert detector.process(frame(4, 30)).status == "normal"
    assert detector.process(frame(5, 30)).status == "anomaly"
    assert [detector.process(frame(origin, 10)).status for origin in range(6, 9)] == [
        "anomaly",
        "anomaly",
        "normal",
    ]


def test_detector_updates_baseline_only_with_below_threshold_samples() -> None:
    detector = OnlineGaussianDetector(
        DetectorConfig(
            warmup_samples=2,
            threshold=4.0,
            stddev_floor=1.0,
            anomaly_streak=1,
            ewma_alpha=0.5,
        )
    )
    detector.process(frame(1, 10))
    detector.process(frame(2, 10))
    baseline = detector.snapshot()

    detector.process(frame(3, 30))
    after_anomaly = detector.snapshot()
    detector.process(frame(4, 12))
    after_normal = detector.snapshot()

    assert after_anomaly.baseline_mean == baseline.baseline_mean == 10.0
    assert after_anomaly.sample_count == 2
    assert after_normal.baseline_mean == 11.0
    assert after_normal.sample_count == 3
