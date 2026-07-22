from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AxisName = Literal["x", "y", "z"]
DetectionStatus = Literal["warming_up", "normal", "anomaly"]
RuntimeStatus = Literal["starting", "warming_up", "normal", "anomaly", "degraded"]
InputState = Literal["waiting", "fresh", "stale", "error"]
RuntimeModelState = Literal["warming_up", "ready"]


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


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class AxisValues(ApiModel):
    x: int
    y: int
    z: int


class SourceIdentity(ApiModel):
    physical_source: str = "arduino-001"
    device_service: str = "device-serial-jetson"
    devices: list[str] = Field(default_factory=list)


class LatestObservation(ApiModel):
    origin: int
    observed_at: datetime
    values: AxisValues
    magnitude: float
    score: float
    anomaly: bool


class ModelObservation(ApiModel):
    algorithm: str
    sample_count: int
    warmup_samples: int
    threshold: float
    baseline_mean: float
    baseline_stddev: float
    stddev_floor: float


class RuntimeCounters(ApiModel):
    frames_processed: int = 0
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0
    input_errors: int = 0


class ServiceStatus(ApiModel):
    api_version: Literal["v1"] = "v1"
    service: Literal["sensor-anomaly-demo"] = "sensor-anomaly-demo"
    mode: Literal["live"] = "live"
    status: RuntimeStatus
    input_state: InputState
    model_state: RuntimeModelState
    source: SourceIdentity
    latest: LatestObservation | None = None
    model: ModelObservation
    counters: RuntimeCounters
    last_error: str | None = None


class ResultEnvelope(ApiModel):
    api_version: Literal["v1"] = "v1"
    count: int
    results: list[LatestObservation]
