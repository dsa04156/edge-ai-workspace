from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parents[1]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    namespace: str = Field(
        default_factory=lambda: os.getenv(
            "ADAPTER_CONTROLLER_NAMESPACE",
            "edgex-edge",
        ),
        pattern=r"^edgex-edge$",
    )
    catalog_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "ADAPTER_RUNTIME_CATALOG_PATH",
                str(APP_DIR / "config" / "runtime_templates.json"),
            )
        )
    )
    device_catalog_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "DEVICE_BINDING_CATALOG_PATH",
                str(APP_DIR / "config" / "device_bindings.json"),
            )
        )
    )
    discovery_plans_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "DISCOVERY_PLANS_PATH",
                str(APP_DIR / "config" / "discovery_plans.json"),
            )
        )
    )
    discovery_database_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                "DISCOVERY_DATABASE_PATH",
                "/var/lib/adapter-controller/discovery.db",
            )
        )
    )
    core_metadata_url: str = Field(
        default_factory=lambda: os.getenv(
            "EDGEX_CORE_METADATA_URL",
            "http://edgex-core-metadata.edgex-system.svc.cluster.local:59881",
        )
    )
    core_data_url: str = Field(
        default_factory=lambda: os.getenv(
            "EDGEX_CORE_DATA_URL",
            "http://edgex-core-data.edgex-system.svc.cluster.local:59880",
        )
    )
    edgex_timeout_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("EDGEX_TIMEOUT_SECONDS", "5")
        ),
        gt=0,
        le=60,
    )
    internal_hmac_key: str | None = Field(
        default_factory=lambda: os.getenv(
            "ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY"
        )
        or None
    )
    mutation_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "ADAPTER_RUNTIME_MUTATION_ENABLED",
            False,
        )
    )
    device_discovery_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "ADAPTER_DEVICE_DISCOVERY_ENABLED",
            False,
        )
    )
    discovery_stale_after_seconds: int = Field(
        default_factory=lambda: int(
            os.getenv("ADAPTER_DISCOVERY_STALE_AFTER_SECONDS", "90")
        ),
        ge=10,
        le=3600,
    )
    discovery_candidate_limit: int = Field(
        default_factory=lambda: int(
            os.getenv("ADAPTER_DISCOVERY_CANDIDATE_LIMIT", "2000")
        ),
        ge=1,
        le=10000,
    )
    signature_max_age_seconds: int = Field(
        default_factory=lambda: int(
            os.getenv("ADAPTER_CONTROLLER_SIGNATURE_MAX_AGE_SECONDS", "60")
        ),
        ge=5,
        le=300,
    )
    reconcile_interval_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("ADAPTER_CONTROLLER_RECONCILE_INTERVAL_SECONDS", "10")
        ),
        ge=1,
        le=300,
    )
    registration_event_timeout_seconds: int = Field(
        default_factory=lambda: int(
            os.getenv("ADAPTER_REGISTRATION_EVENT_TIMEOUT_SECONDS", "60")
        ),
        ge=5,
        le=3600,
    )
    auth_mode: str = Field(
        default_factory=lambda: os.getenv(
            "ADAPTER_AUTH_MODE",
            "external",
        ),
        pattern=r"^(development-mock|external)$",
    )
    auth_endpoint: str | None = Field(
        default_factory=lambda: os.getenv("ADAPTER_AUTH_ENDPOINT") or None
    )
    auth_token: str | None = Field(
        default_factory=lambda: os.getenv("ADAPTER_AUTH_TOKEN") or None
    )
    auth_timeout_seconds: float = Field(
        default_factory=lambda: float(
            os.getenv("ADAPTER_AUTH_TIMEOUT_SECONDS", "5")
        ),
        gt=0,
        le=30,
    )
