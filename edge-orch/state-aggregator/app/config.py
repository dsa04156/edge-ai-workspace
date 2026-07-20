from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
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


def load_instance_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    return json.loads(content)
