from __future__ import annotations

import math
from collections import deque

from .models import (
    AccelerationFrame,
    AxisSample,
    TemperatureFeatures,
    VibrationFeatures,
)


class SlidingFeatureExtractor:
    """Build bounded statistical features from raw sensor windows."""

    def __init__(
        self,
        vibration_window_samples: int,
        temperature_window_samples: int,
    ) -> None:
        if vibration_window_samples < 2:
            raise ValueError("vibration_window_samples must be at least 2")
        if temperature_window_samples < 2:
            raise ValueError("temperature_window_samples must be at least 2")
        self._vibration: deque[tuple[int, float]] = deque(
            maxlen=vibration_window_samples
        )
        self._temperature: deque[AxisSample] = deque(
            maxlen=temperature_window_samples
        )

    def add_vibration(self, frame: AccelerationFrame) -> VibrationFeatures:
        magnitude = math.sqrt(frame.x**2 + frame.y**2 + frame.z**2)
        self._vibration.append((frame.origin, magnitude))
        values = [value for _, value in self._vibration]
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        if len(values) < 4 or variance <= 1e-12:
            kurtosis = 0.0
        else:
            fourth_moment = (
                math.fsum((value - mean) ** 4 for value in values) / len(values)
            )
            kurtosis = fourth_moment / (variance**2)
        return VibrationFeatures(
            origin=frame.origin,
            rms=round(
                math.sqrt(math.fsum(value**2 for value in values) / len(values)),
                6,
            ),
            peak=round(max(values), 6),
            kurtosis=round(kurtosis, 6),
            sample_count=len(values),
        )

    def add_temperature(self, sample: AxisSample) -> TemperatureFeatures:
        self._temperature.append(sample)
        values = [float(item.value) for item in self._temperature]
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
        return TemperatureFeatures(
            origin=sample.origin,
            raw=sample.value,
            mean=round(mean, 6),
            stddev=round(math.sqrt(max(variance, 0.0)), 6),
            delta=round(values[-1] - values[0], 6),
            sample_count=len(values),
        )
