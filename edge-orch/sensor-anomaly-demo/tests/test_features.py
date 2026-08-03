import pytest

from app.features import SlidingFeatureExtractor
from app.models import AccelerationFrame, AxisSample


def test_feature_extractor_builds_bounded_vibration_and_temperature_windows() -> None:
    extractor = SlidingFeatureExtractor(
        vibration_window_samples=2,
        temperature_window_samples=2,
    )

    first = extractor.add_vibration(AccelerationFrame(origin=1, x=3, y=4, z=0))
    second = extractor.add_vibration(AccelerationFrame(origin=2, x=0, y=0, z=12))
    third = extractor.add_vibration(AccelerationFrame(origin=3, x=0, y=0, z=16))
    extractor.add_temperature(AxisSample(1, "Int32", 10))
    extractor.add_temperature(AxisSample(2, "Int32", 14))
    temperature = extractor.add_temperature(AxisSample(3, "Int32", 20))

    assert first.rms == 5.0
    assert second.rms == pytest.approx((84.5) ** 0.5)
    assert third.rms == pytest.approx((200.0) ** 0.5)
    assert third.peak == 16.0
    assert third.sample_count == 2
    assert temperature.raw == 20
    assert temperature.mean == 17.0
    assert temperature.stddev == 3.0
    assert temperature.delta == 6.0
    assert temperature.sample_count == 2


def test_constant_short_vibration_window_has_finite_zero_kurtosis() -> None:
    extractor = SlidingFeatureExtractor(4, 2)

    feature = extractor.add_vibration(
        AccelerationFrame(origin=1, x=1, y=0, z=0)
    )

    assert feature.kurtosis == 0.0
