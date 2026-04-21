from __future__ import annotations

import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    state_aggregator_url: str = Field(
        default_factory=lambda: os.getenv(
            "STATE_AGGREGATOR_URL", "http://state-aggregator:8000"
        )
    )
