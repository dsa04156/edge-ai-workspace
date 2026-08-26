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


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


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
            os.getenv("SENSOR_ANOMALY_DEMO_TIMEOUT_SECONDS", "10")
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
    service_catalog_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "SERVICE_CATALOG_PATH",
                str(APP_CONFIG_DIR / "service_catalog.json"),
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
    deployment_controller_enabled: bool = Field(
        default_factory=lambda: _env_bool("DEPLOYMENT_CONTROLLER_ENABLED")
    )
    deployment_target_namespace: str = Field(
        default_factory=lambda: os.getenv(
            "DEPLOYMENT_TARGET_NAMESPACE",
            "edge-ai-workloads",
        ),
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    deployment_management_token: str | None = Field(
        default_factory=lambda: os.getenv("DEPLOYMENT_MANAGEMENT_TOKEN") or None
    )
    deployment_allowed_image_prefixes: tuple[str, ...] = Field(
        default_factory=lambda: _env_csv(
            "DEPLOYMENT_ALLOWED_IMAGE_PREFIXES",
            (
                "192.168.0.56:5000/state-aggregator@sha256:",
                "192.168.0.56:5000/sensor-anomaly-demo@sha256:",
            ),
        )
    )
    deployment_ready_timeout_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("DEPLOYMENT_READY_TIMEOUT_SECONDS", "90")
        ),
        gt=0,
        le=600,
    )
    deployment_poll_interval_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("DEPLOYMENT_POLL_INTERVAL_SECONDS", "2")
        ),
        ge=0.1,
        le=30,
    )
    runtime_recommendation_enabled: bool = Field(
        default_factory=lambda: _env_bool("RUNTIME_RECOMMENDATION_ENABLED", True)
    )
    runtime_recommendation_poll_interval_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("RUNTIME_RECOMMENDATION_POLL_INTERVAL_SECONDS", "15")
        ),
        ge=1,
        le=300,
    )
    runtime_recommendation_database_path: Path | None = Field(
        default_factory=lambda: (
            Path(os.environ["RUNTIME_RECOMMENDATION_DATABASE_PATH"])
            if os.getenv("RUNTIME_RECOMMENDATION_DATABASE_PATH")
            else None
        )
    )
    runtime_recommendation_history_limit: int = Field(
        default_factory=lambda: int(
            os.getenv("RUNTIME_RECOMMENDATION_HISTORY_LIMIT", "1000")
        ),
        ge=1,
        le=100000,
    )
    execution_controller_enabled: bool = Field(
        default_factory=lambda: _env_bool("EXECUTION_CONTROLLER_ENABLED")
    )
    execution_management_token: str | None = Field(
        default_factory=lambda: os.getenv("EXECUTION_MANAGEMENT_TOKEN") or None
    )
    runtime_execution_database_path: Path | None = Field(
        default_factory=lambda: (
            Path(os.environ["RUNTIME_EXECUTION_DATABASE_PATH"])
            if os.getenv("RUNTIME_EXECUTION_DATABASE_PATH")
            else None
        )
    )
    runtime_execution_history_limit: int = Field(
        default_factory=lambda: int(
            os.getenv("RUNTIME_EXECUTION_HISTORY_LIMIT", "1000")
        ),
        ge=1,
        le=100000,
    )
    candidate_template_catalog_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "CANDIDATE_TEMPLATE_CATALOG_PATH",
                str(APP_CONFIG_DIR / "candidate_workload_templates.json"),
            )
        )
    )
    candidate_validation_contract_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "CANDIDATE_VALIDATION_CONTRACT_PATH",
                str(APP_CONFIG_DIR / "candidate_validation_contracts.json"),
            )
        )
    )
    traffic_routing_contract_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "TRAFFIC_ROUTING_CONTRACT_PATH",
                str(APP_CONFIG_DIR / "traffic_routing_contracts.json"),
            )
        )
    )
    execution_ownership_contract_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "EXECUTION_OWNERSHIP_CONTRACT_PATH",
                str(APP_CONFIG_DIR / "execution_ownership_contracts.json"),
            )
        )
    )


def load_instance_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    return json.loads(content)
