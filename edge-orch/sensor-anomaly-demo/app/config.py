from __future__ import annotations

import os
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

DEFAULT_LOCAL_DATA_BASE_URL = (
    "http://device-serial-jetson.edgex-edge.svc.cluster.local:59910"
)


class Settings(BaseModel):
    service_role: Literal["edge-worker", "inference-server"] = "edge-worker"
    inference_warmup_source_enabled: bool = False
    remote_inference_mode: Literal["disabled", "approved"] = "disabled"
    remote_inference_url: str | None = None
    remote_inference_approval_id: str | None = None
    remote_inference_timeout_seconds: float = Field(default=1.0, gt=0)
    remote_inference_max_attempts: int = Field(default=2, ge=1, le=5)
    remote_inference_failure_threshold: int = Field(default=3, ge=1, le=20)
    remote_inference_rollback_cooldown_seconds: int = Field(default=900, ge=1)
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
    context_max_skew_seconds: float = Field(default=2.0, gt=0)
    vibration_window_samples: int = Field(default=20, ge=2, le=1_000)
    temperature_window_samples: int = Field(default=10, ge=2, le=1_000)
    vibration_weight: float = Field(default=0.7, ge=0)
    temperature_weight: float = Field(default=0.3, ge=0)
    model_backend: Literal["online-baseline"] = "online-baseline"
    model_version: str = Field(default="baseline-1.0.0", min_length=1, max_length=64)
    service_device_id: str = Field(default="arduino-001", min_length=1, max_length=128)
    service_asset_id: str = Field(default="arduino-001", min_length=1, max_length=128)
    service_node_id: str = Field(
        default="etri-dev0001-jetorn",
        min_length=1,
        max_length=128,
    )
    result_db_path: str = Field(
        default="/tmp/sensor-anomaly-demo/results.db",
        min_length=1,
    )
    result_retention_rows: int = Field(default=100_000, ge=1, le=10_000_000)

    @model_validator(mode="after")
    def validate_multi_sensor_settings(self) -> Self:
        if self.vibration_weight + self.temperature_weight <= 0:
            raise ValueError("at least one score weight must be positive")
        if self.context_max_skew_seconds > self.pending_ttl_seconds:
            raise ValueError(
                "context_max_skew_seconds must not exceed pending_ttl_seconds"
            )
        if self.remote_inference_mode == "approved":
            if not self.remote_inference_url:
                raise ValueError("remote_inference_url is required in approved mode")
            if not self.remote_inference_approval_id:
                raise ValueError(
                    "remote_inference_approval_id is required in approved mode"
                )
        return self

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            service_role=os.getenv("SERVICE_ROLE", "edge-worker"),
            inference_warmup_source_enabled=os.getenv(
                "INFERENCE_WARMUP_SOURCE_ENABLED", "false"
            ).lower()
            in {"1", "true", "yes"},
            remote_inference_mode=os.getenv("REMOTE_INFERENCE_MODE", "disabled"),
            remote_inference_url=os.getenv("REMOTE_INFERENCE_URL") or None,
            remote_inference_approval_id=os.getenv("REMOTE_INFERENCE_APPROVAL_ID")
            or None,
            remote_inference_timeout_seconds=float(
                os.getenv("REMOTE_INFERENCE_TIMEOUT_SECONDS", "1")
            ),
            remote_inference_max_attempts=int(
                os.getenv("REMOTE_INFERENCE_MAX_ATTEMPTS", "2")
            ),
            remote_inference_failure_threshold=int(
                os.getenv("REMOTE_INFERENCE_FAILURE_THRESHOLD", "3")
            ),
            remote_inference_rollback_cooldown_seconds=int(
                os.getenv("REMOTE_INFERENCE_ROLLBACK_COOLDOWN_SECONDS", "900")
            ),
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
            context_max_skew_seconds=float(os.getenv("CONTEXT_MAX_SKEW_SECONDS", "2")),
            vibration_window_samples=int(os.getenv("VIBRATION_WINDOW_SAMPLES", "20")),
            temperature_window_samples=int(
                os.getenv("TEMPERATURE_WINDOW_SAMPLES", "10")
            ),
            vibration_weight=float(os.getenv("VIBRATION_WEIGHT", "0.7")),
            temperature_weight=float(os.getenv("TEMPERATURE_WEIGHT", "0.3")),
            model_backend=os.getenv("MODEL_BACKEND", "online-baseline"),
            model_version=os.getenv("MODEL_VERSION", "baseline-1.0.0"),
            service_device_id=os.getenv("SERVICE_DEVICE_ID", "arduino-001"),
            service_asset_id=os.getenv("SERVICE_ASSET_ID", "arduino-001"),
            service_node_id=os.getenv(
                "SERVICE_NODE_ID",
                "etri-dev0001-jetorn",
            ),
            result_db_path=os.getenv(
                "RESULT_DB_PATH",
                "/tmp/sensor-anomaly-demo/results.db",
            ),
            result_retention_rows=int(os.getenv("RESULT_RETENTION_ROWS", "100000")),
        )
