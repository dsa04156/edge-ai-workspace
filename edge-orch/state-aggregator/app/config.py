from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic import ConfigDict, model_validator


def _env_bool(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean token")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    virtual_device_projection_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "VIRTUAL_DEVICE_PROJECTION_ENABLED", "false"
        )
    )
    virtual_device_bindings_path: Path | None = Field(
        default_factory=lambda: (
            Path(value)
            if (value := os.getenv("VIRTUAL_DEVICE_BINDINGS_PATH"))
            else None
        )
    )
    virtual_device_observer_interval_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("VIRTUAL_DEVICE_OBSERVER_INTERVAL_SECONDS", "30")
        ),
        gt=0,
    )
    virtual_device_observer_timeout_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("VIRTUAL_DEVICE_OBSERVER_TIMEOUT_SECONDS", "10")
        ),
        gt=0,
    )
    virtual_device_observer_concurrency: int = Field(
        default_factory=lambda: int(
            os.getenv("VIRTUAL_DEVICE_OBSERVER_CONCURRENCY", "4")
        ),
        ge=1,
        le=32,
    )
    virtual_device_event_query_page_size: int = Field(
        default_factory=lambda: int(
            os.getenv("VIRTUAL_DEVICE_EVENT_QUERY_PAGE_SIZE", "100")
        ),
        ge=1,
        le=100,
    )
    virtual_device_event_query_max_pages: int = Field(
        default_factory=lambda: int(
            os.getenv("VIRTUAL_DEVICE_EVENT_QUERY_MAX_PAGES", "10")
        ),
        ge=1,
        le=10,
    )
    virtual_device_event_query_max_events_per_device: int = Field(
        default_factory=lambda: int(
            os.getenv("VIRTUAL_DEVICE_EVENT_QUERY_MAX_EVENTS_PER_DEVICE", "1000")
        ),
        ge=1,
        le=1000,
    )
    virtual_device_event_query_max_prior_probe_events_per_device: int = Field(
        default_factory=lambda: int(
            os.getenv(
                "VIRTUAL_DEVICE_EVENT_QUERY_MAX_PRIOR_PROBE_EVENTS_PER_DEVICE",
                "200",
            )
        ),
        ge=1,
        le=200,
    )
    prometheus_url: str = Field(
        default_factory=lambda: os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    )
    poll_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
    )
    instance_map_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "INSTANCE_MAP_PATH",
                str(Path(__file__).resolve().parent / "config" / "instance_map.json"),
            )
        )
    )
    data_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("DATA_DIR", str(Path(__file__).resolve().parent / "data"))
        )
    )
    influxdb_url: str = Field(
        default_factory=lambda: os.getenv(
            "INFLUXDB_URL",
            "http://influxdb:8086",
        )
    )
    influxdb_org: str = Field(default_factory=lambda: os.getenv("INFLUXDB_ORG", "edgeai"))
    influxdb_bucket: str = Field(default_factory=lambda: os.getenv("INFLUXDB_BUCKET", "device_telemetry"))
    influxdb_token: str | None = Field(default_factory=lambda: os.getenv("INFLUXDB_TOKEN"))
    edgex_core_metadata_url: str = Field(
        default_factory=lambda: os.getenv(
            "EDGEX_CORE_METADATA_URL",
            "http://edgex-core-metadata.edgex-system.svc.cluster.local:59881",
        )
    )
    edgex_core_data_url: str = Field(
        default_factory=lambda: os.getenv(
            "EDGEX_CORE_DATA_URL",
            "http://edgex-core-data.edgex-system.svc.cluster.local:59880",
        )
    )
    edgex_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("EDGEX_TIMEOUT_SECONDS", "10"))
    )
    edgex_event_fresh_seconds: int = Field(
        default_factory=lambda: int(os.getenv("EDGEX_EVENT_FRESH_SECONDS", "90"))
    )
    edgex_event_query_concurrency: int = Field(
        default_factory=lambda: int(os.getenv("EDGEX_EVENT_QUERY_CONCURRENCY", "1")),
        ge=1,
        le=8,
    )
    edgex_device_snapshot_ttl_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("EDGEX_DEVICE_SNAPSHOT_TTL_SECONDS", "10")
        ),
        gt=0,
        le=60,
    )
    edgex_device_error_backoff_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("EDGEX_DEVICE_ERROR_BACKOFF_SECONDS", "30")
        ),
        gt=0,
        le=300,
    )
    resource_profile_recording_mode: str = Field(
        default_factory=lambda: os.getenv("RESOURCE_PROFILE_RECORDING_MODE", "disabled").lower()
    )
    resource_profile_window: str = Field(
        default_factory=lambda: os.getenv("RESOURCE_PROFILE_WINDOW", "10m")
    )
    resource_profile_record_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("RESOURCE_PROFILE_RECORD_INTERVAL_SECONDS", "600"))
    )
    qwen_base_url: str = Field(
        default_factory=lambda: os.getenv("QWEN_BASE_URL", "http://192.168.0.5:8080/v1")
    )
    qwen_model: str = Field(
        default_factory=lambda: os.getenv("QWEN_MODEL", "qwen3.6-35b")
    )
    qwen_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("QWEN_TIMEOUT_SECONDS", "90"))
    )
    @model_validator(mode="after")
    def require_bindings_path_when_projection_enabled(self) -> Settings:
        if self.virtual_device_projection_enabled and self.virtual_device_bindings_path is None:
            raise ValueError(
                "virtual_device_bindings_path is required when projection is enabled"
            )
        return self



def load_instance_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    return json.loads(content)
