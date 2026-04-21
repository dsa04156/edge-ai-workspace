from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    placement_engine_url: str = Field(
        default_factory=lambda: os.getenv("PLACEMENT_ENGINE_URL", "http://placement-engine:8001")
    )
    state_aggregator_event_url: str = Field(
        default_factory=lambda: os.getenv(
            "STATE_AGGREGATOR_URL", "http://state-aggregator:8000/workflow-event"
        )
    )
    namespace: str = Field(default_factory=lambda: os.getenv("EXECUTOR_NAMESPACE", "default"))
    data_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("EXECUTOR_DATA_DIR", "/app/data"))
    )
    state_db_path: Path = Field(
        default_factory=lambda: Path(os.getenv("STATE_DB_PATH", "/app/data/workflow_state.db"))
    )
    job_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("JOB_TIMEOUT_SECONDS", "300"))
    )
    poll_interval_seconds: float = Field(
        default_factory=lambda: float(os.getenv("JOB_POLL_INTERVAL_SECONDS", "1"))
    )
