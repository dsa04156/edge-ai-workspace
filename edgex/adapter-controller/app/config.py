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
    core_metadata_url: str = Field(
        default_factory=lambda: os.getenv(
            "EDGEX_CORE_METADATA_URL",
            "http://edgex-core-metadata.edgex-system.svc.cluster.local:59881",
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
