from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ServiceDemoStatus = Literal[
    "starting",
    "warming_up",
    "normal",
    "anomaly",
    "degraded",
]


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class UpstreamModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class UpstreamAxisValues(UpstreamModel):
    x: int
    y: int
    z: int


class UpstreamSource(UpstreamModel):
    physical_source: str
    device_service: str
    devices: list[str]


class UpstreamLatest(UpstreamModel):
    origin: int = Field(gt=0)
    observed_at: datetime
    values: UpstreamAxisValues
    magnitude: float
    score: float = Field(ge=0)
    anomaly: bool


class UpstreamDetectorModel(UpstreamModel):
    algorithm: Literal["online-gaussian-baseline-v1"]
    sample_count: int = Field(ge=0)
    warmup_samples: int = Field(ge=1)
    threshold: float = Field(gt=0)
    baseline_mean: float
    baseline_stddev: float = Field(ge=0)
    stddev_floor: float = Field(gt=0)


class UpstreamCounters(UpstreamModel):
    frames_processed: int = Field(ge=0)
    duplicates_ignored: int = Field(ge=0)
    incomplete_frames_dropped: int = Field(ge=0)
    input_errors: int = Field(ge=0)


class UpstreamServiceStatus(UpstreamModel):
    api_version: Literal["v1"]
    service: Literal["sensor-anomaly-demo"]
    mode: Literal["live"]
    status: ServiceDemoStatus
    input_state: Literal["waiting", "fresh", "stale", "error"]
    model_state: Literal["warming_up", "ready"]
    source: UpstreamSource
    latest: UpstreamLatest | None = None
    model: UpstreamDetectorModel
    counters: UpstreamCounters
    last_error: str | None = None


class ServiceDemoBinding(BaseModel):
    physical_source: str = "arduino-001"
    device_service: str = "device-serial-jetson"
    devices: list[str] = Field(default_factory=list)
    consumer: str = "sensor-anomaly-demo"
    node: str = "etri-dev0001-jetorn"


class ServiceDemoAxisValues(BaseModel):
    x: int
    y: int
    z: int


class ServiceDemoLatest(BaseModel):
    origin: int
    observed_at: datetime
    values: ServiceDemoAxisValues
    magnitude: float
    score: float
    anomaly: bool


class ServiceDemoModel(BaseModel):
    algorithm: str
    sample_count: int
    warmup_samples: int
    threshold: float
    baseline_mean: float
    baseline_stddev: float
    stddev_floor: float


class ServiceDemoCounters(BaseModel):
    frames_processed: int = 0
    duplicates_ignored: int = 0
    incomplete_frames_dropped: int = 0
    input_errors: int = 0


class ServiceDemoState(BaseModel):
    generated_at: datetime
    mode: Literal["live", "unavailable"]
    status: ServiceDemoStatus
    input_state: str
    model_state: str
    binding: ServiceDemoBinding
    latest: ServiceDemoLatest | None = None
    model: ServiceDemoModel | None = None
    counters: ServiceDemoCounters = Field(default_factory=ServiceDemoCounters)
    last_error: str | None = None
    observation_error: str | None = None
