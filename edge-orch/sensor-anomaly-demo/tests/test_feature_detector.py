import pytest

from app.feature_detector import (
    FeatureDetectorConfig,
    OnlineFeatureDetector,
    ScoreLatch,
)


def detector() -> OnlineFeatureDetector:
    return OnlineFeatureDetector(
        FeatureDetectorConfig(
            algorithm="test-features-v1",
            feature_names=("mean", "delta"),
            warmup_samples=2,
            threshold=4,
            stddev_floor=1,
            anomaly_streak=1,
            clear_streak=2,
            ewma_alpha=0.5,
        )
    )


def test_feature_detector_warms_up_scores_and_preserves_anomaly_baseline() -> None:
    model = detector()
    model.process(1, {"mean": 10.0, "delta": 0.0})
    ready = model.process(2, {"mean": 10.0, "delta": 0.0})
    baseline = model.snapshot()
    anomaly = model.process(3, {"mean": 20.0, "delta": 8.0})

    assert ready.status == "normal"
    assert anomaly.status == "anomaly"
    assert anomaly.score == 10.0
    assert model.snapshot().feature_means == baseline.feature_means


def test_feature_detector_rejects_wrong_or_non_finite_vectors() -> None:
    model = detector()

    with pytest.raises(ValueError, match="contract"):
        model.process(1, {"mean": 1.0})
    with pytest.raises(ValueError, match="finite"):
        model.process(1, {"mean": float("nan"), "delta": 0.0})


def test_fused_score_latch_applies_anomaly_and_clear_streaks() -> None:
    latch = ScoreLatch(threshold=4, anomaly_streak=2, clear_streak=2)

    assert latch.process(10, ready=False) == "warming_up"
    assert latch.process(5, ready=True) == "normal"
    assert latch.process(5, ready=True) == "anomaly"
    assert latch.process(1, ready=True) == "anomaly"
    assert latch.process(1, ready=True) == "normal"
