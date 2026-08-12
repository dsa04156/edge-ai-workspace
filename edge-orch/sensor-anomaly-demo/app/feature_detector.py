from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import (
    DetectionStatus,
    FeatureInferenceResult,
    FeatureModelSnapshot,
)


@dataclass(frozen=True)
class FeatureDetectorConfig:
    algorithm: str
    feature_names: tuple[str, ...]
    warmup_samples: int = 30
    threshold: float = 4.0
    stddev_floor: float = 1.0
    stddev_floor_overrides: dict[str, float] = field(default_factory=dict)
    anomaly_streak: int = 2
    clear_streak: int = 3
    ewma_alpha: float = 0.05


class OnlineFeatureDetector:
    """Online per-feature Gaussian baseline with a maximum z-score."""

    def __init__(self, config: FeatureDetectorConfig) -> None:
        if not config.feature_names:
            raise ValueError("feature_names must not be empty")
        if len(config.feature_names) != len(set(config.feature_names)):
            raise ValueError("feature_names must be unique")
        if config.stddev_floor <= 0:
            raise ValueError("stddev_floor must be positive")
        self.config = config
        self._count = 0
        self._means = {name: 0.0 for name in config.feature_names}
        self._m2 = {name: 0.0 for name in config.feature_names}
        self._variances = {name: 0.0 for name in config.feature_names}
        self._above_threshold = 0
        self._below_threshold = 0
        self._anomaly = False

    def process(
        self,
        origin: int,
        features: dict[str, float],
    ) -> FeatureInferenceResult:
        self._validate_features(features)
        if self._count < self.config.warmup_samples:
            self._count += 1
            for name in self.config.feature_names:
                value = features[name]
                delta = value - self._means[name]
                self._means[name] += delta / self._count
                self._m2[name] += delta * (value - self._means[name])
                if self._count == self.config.warmup_samples:
                    self._variances[name] = self._m2[name] / max(1, self._count - 1)
            status: DetectionStatus = (
                "normal"
                if self._count == self.config.warmup_samples
                else "warming_up"
            )
            return self._result(origin, 0.0, status)

        score = max(
            abs(features[name] - self._means[name]) / self._stddev(name)
            for name in self.config.feature_names
        )
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
            for name in self.config.feature_names:
                delta = features[name] - self._means[name]
                self._means[name] += alpha * delta
                self._variances[name] = (1.0 - alpha) * (
                    self._variances[name] + alpha * delta * delta
                )
            self._count += 1

        status: DetectionStatus = "anomaly" if self._anomaly else "normal"
        return self._result(origin, score, status)

    def snapshot(self) -> FeatureModelSnapshot:
        return FeatureModelSnapshot(
            algorithm=self.config.algorithm,
            sample_count=self._count,
            warmup_samples=self.config.warmup_samples,
            threshold=self.config.threshold,
            feature_means={
                name: round(self._means[name], 6)
                for name in self.config.feature_names
            },
            feature_stddevs={
                name: round(math.sqrt(max(self._variances[name], 0.0)), 6)
                for name in self.config.feature_names
            },
            stddev_floors={
                name: self._floor(name) for name in self.config.feature_names
            },
        )

    def _validate_features(self, features: dict[str, float]) -> None:
        if set(features) != set(self.config.feature_names):
            raise ValueError("feature vector does not match detector contract")
        if any(not math.isfinite(features[name]) for name in self.config.feature_names):
            raise ValueError("feature values must be finite")

    def _floor(self, name: str) -> float:
        return self.config.stddev_floor_overrides.get(name, self.config.stddev_floor)

    def _stddev(self, name: str) -> float:
        return max(
            math.sqrt(max(self._variances[name], 0.0)),
            self._floor(name),
        )

    @staticmethod
    def _result(
        origin: int,
        score: float,
        status: DetectionStatus,
    ) -> FeatureInferenceResult:
        return FeatureInferenceResult(
            origin=origin,
            score=round(score, 6),
            anomaly=status == "anomaly",
            status=status,
        )


class ScoreLatch:
    """Apply streak-based anomaly state to the fused component score."""

    def __init__(self, threshold: float, anomaly_streak: int, clear_streak: int) -> None:
        self.threshold = threshold
        self.anomaly_streak = anomaly_streak
        self.clear_streak = clear_streak
        self._above_threshold = 0
        self._below_threshold = 0
        self._anomaly = False

    def process(self, score: float, ready: bool) -> DetectionStatus:
        if not ready:
            self._above_threshold = 0
            self._below_threshold = 0
            return "warming_up"
        if score >= self.threshold:
            self._above_threshold += 1
            self._below_threshold = 0
            if self._above_threshold >= self.anomaly_streak:
                self._anomaly = True
        else:
            self._above_threshold = 0
            self._below_threshold += 1
            if self._anomaly and self._below_threshold >= self.clear_streak:
                self._anomaly = False
        return "anomaly" if self._anomaly else "normal"
