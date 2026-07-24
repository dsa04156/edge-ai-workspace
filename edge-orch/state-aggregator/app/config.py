from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


APP_CONFIG_DIR = Path(__file__).resolve().parent / "config"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    sensor_anomaly_demo_url: str = Field(
        default_factory=lambda: os.getenv(
            "SENSOR_ANOMALY_DEMO_URL",
            "http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080",
        )
    )
    sensor_anomaly_demo_timeout_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("SENSOR_ANOMALY_DEMO_TIMEOUT_SECONDS", "2")
        )
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
    device_management_enabled: bool = Field(
        default_factory=lambda: _env_bool("DEVICE_MANAGEMENT_ENABLED")
    )
    device_management_admin_token: str | None = Field(
        default_factory=lambda: os.getenv("DEVICE_MANAGEMENT_ADMIN_TOKEN") or None
    )
    device_management_hmac_key: str | None = Field(
        default_factory=lambda: os.getenv("DEVICE_MANAGEMENT_HMAC_KEY") or None
    )
    device_management_operation_limit: int = Field(
        default_factory=lambda: int(os.getenv("DEVICE_MANAGEMENT_OPERATION_LIMIT", "256")),
        ge=1,
        le=10000,
    )
    adapter_catalog_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "ADAPTER_CATALOG_PATH",
                str(APP_CONFIG_DIR / "adapter_catalog.json"),
            )
        )
    )
    adapter_runtime_management_enabled: bool = Field(
        default_factory=lambda: _env_bool("ADAPTER_RUNTIME_MANAGEMENT_ENABLED")
    )
    adapter_runtime_mutation_enabled: bool = Field(
        default_factory=lambda: _env_bool("ADAPTER_RUNTIME_MUTATION_ENABLED")
    )
    device_discovery_management_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "DEVICE_DISCOVERY_MANAGEMENT_ENABLED"
        )
    )
    device_discovery_tokenless_approval_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "DEVICE_DISCOVERY_TOKENLESS_APPROVAL_ENABLED"
        )
    )
    adapter_controller_url: str = Field(
        default_factory=lambda: os.getenv(
            "ADAPTER_CONTROLLER_URL",
            "http://edgex-adapter-controller.edgex-edge.svc.cluster.local:8080",
        )
    )
    adapter_controller_internal_hmac_key: str | None = Field(
        default_factory=lambda: os.getenv(
            "ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY"
        )
        or None
    )
    adapter_controller_timeout_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("ADAPTER_CONTROLLER_TIMEOUT_SECONDS", "5")
        ),
        gt=0,
        le=60,
    )


def load_instance_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    return json.loads(content)
