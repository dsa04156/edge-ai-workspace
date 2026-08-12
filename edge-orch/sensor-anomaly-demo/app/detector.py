from __future__ import annotations

import math
from dataclasses import dataclass

from .models import (
    AccelerationFrame,
    DetectionStatus,
    InferenceResult,
    ModelSnapshot,
)


ALGORITHM = "online-gaussian-baseline-v1"


@dataclass(frozen=True)
class DetectorConfig:
    warmup_samples: int = 30
    threshold: float = 4.0
    stddev_floor: float = 1.0
    anomaly_streak: int = 2
    clear_streak: int = 3
    ewma_alpha: float = 0.05


class OnlineGaussianDetector:
    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()
        self._count = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._variance = 0.0
        self._above_threshold = 0
        self._below_threshold = 0
        self._anomaly = False

    def process(self, frame: AccelerationFrame) -> InferenceResult:
        magnitude = math.sqrt(frame.x**2 + frame.y**2 + frame.z**2)
        if self._count < self.config.warmup_samples:
            self._count += 1
            delta = magnitude - self._mean
            self._mean += delta / self._count
            self._m2 += delta * (magnitude - self._mean)
            if self._count == self.config.warmup_samples:
                self._variance = self._m2 / max(1, self._count - 1)
                status: DetectionStatus = "normal"
            else:
                status = "warming_up"
            return self._result(frame, magnitude, score=0.0, status=status)

        stddev = max(math.sqrt(max(self._variance, 0.0)), self.config.stddev_floor)
        score = abs(magnitude - self._mean) / stddev
        if score >= self.config.threshold:
            self._above_threshold += 1
            self._below_threshold = 0
            if self._above_threshold >= self.config.anomaly_streak:
                self._anomaly = True
        else:
            self._above_threshold = 0
            self._below_threshold += 1
            if self._anomaly and self._below_threshold >= self.config.clear_streak:
                self._anomaly = False
            alpha = self.config.ewma_alpha
            delta = magnitude - self._mean
            self._mean += alpha * delta
            self._variance = (1.0 - alpha) * (
                self._variance + alpha * delta * delta
            )
            self._count += 1

        status: DetectionStatus = "anomaly" if self._anomaly else "normal"
        return self._result(frame, magnitude, score=score, status=status)

    def snapshot(self) -> ModelSnapshot:
        return ModelSnapshot(
            algorithm=ALGORITHM,
            sample_count=self._count,
            warmup_samples=self.config.warmup_samples,
            threshold=self.config.threshold,
            baseline_mean=round(self._mean, 6),
            baseline_stddev=round(math.sqrt(max(self._variance, 0.0)), 6),
            stddev_floor=self.config.stddev_floor,
        )

    @staticmethod
    def _result(
        frame: AccelerationFrame,
        magnitude: float,
        score: float,
        status: DetectionStatus,
    ) -> InferenceResult:
        return InferenceResult(
            origin=frame.origin,
            x=frame.x,
            y=frame.y,
            z=frame.z,
            magnitude=round(magnitude, 6),
            score=round(score, 6),
            anomaly=status == "anomaly",
            status=status,
        )
