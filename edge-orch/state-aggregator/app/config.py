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


def load_instance_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {}
    return json.loads(content)
