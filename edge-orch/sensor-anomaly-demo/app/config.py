from __future__ import annotations

import os

from pydantic import BaseModel, Field


DEFAULT_LOCAL_DATA_BASE_URL = (
    "http://device-serial-jetson.edgex-edge.svc.cluster.local:59910"
)


class Settings(BaseModel):
    local_data_base_url: str = Field(
        default=DEFAULT_LOCAL_DATA_BASE_URL,
        min_length=1,
    )
    poll_interval_seconds: float = Field(default=0.5, gt=0)
    input_stale_seconds: float = Field(default=10.0, gt=0)
    http_timeout_seconds: float = Field(default=2.0, gt=0)
    warmup_samples: int = Field(default=30, ge=1)
    anomaly_threshold: float = Field(default=4.0, gt=0)
    stddev_floor: float = Field(default=1.0, gt=0)
    anomaly_streak: int = Field(default=2, ge=1)
    clear_streak: int = Field(default=3, ge=1)
    ewma_alpha: float = Field(default=0.05, gt=0, le=1)
    recent_result_limit: int = Field(default=1_000, ge=1, le=1_000)
    pending_ttl_seconds: float = Field(default=10.0, gt=0)
    max_pending_frames: int = Field(default=1_000, ge=1, le=10_000)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            local_data_base_url=os.getenv(
                "LOCAL_DATA_BASE_URL",
                DEFAULT_LOCAL_DATA_BASE_URL,
            ),
            poll_interval_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "0.5")),
            input_stale_seconds=float(os.getenv("INPUT_STALE_SECONDS", "10")),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "2")),
            warmup_samples=int(os.getenv("WARMUP_SAMPLES", "30")),
            anomaly_threshold=float(os.getenv("ANOMALY_THRESHOLD", "4")),
            stddev_floor=float(os.getenv("STDDEV_FLOOR", "1")),
            anomaly_streak=int(os.getenv("ANOMALY_STREAK", "2")),
            clear_streak=int(os.getenv("CLEAR_STREAK", "3")),
            ewma_alpha=float(os.getenv("EWMA_ALPHA", "0.05")),
            recent_result_limit=int(os.getenv("RECENT_RESULT_LIMIT", "1000")),
            pending_ttl_seconds=float(os.getenv("PENDING_TTL_SECONDS", "10")),
            max_pending_frames=int(os.getenv("MAX_PENDING_FRAMES", "1000")),
        )
