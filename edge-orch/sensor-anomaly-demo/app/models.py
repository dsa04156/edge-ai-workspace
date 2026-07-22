from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AxisName = Literal["x", "y", "z"]
DetectionStatus = Literal["warming_up", "normal", "anomaly"]


@dataclass(frozen=True)
class AxisSample:
    origin: int
    value_type: str
    value: int


@dataclass(frozen=True)
class AccelerationFrame:
    origin: int
    x: int
    y: int
    z: int


@dataclass
class JoinCounters:
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0


@dataclass(frozen=True)
class InferenceResult:
    origin: int
    x: int
    y: int
    z: int
    magnitude: float
    score: float
    anomaly: bool
    status: DetectionStatus


@dataclass(frozen=True)
class ModelSnapshot:
    algorithm: str
    sample_count: int
    warmup_samples: int
    threshold: float
    baseline_mean: float
    baseline_stddev: float
    stddev_floor: float
