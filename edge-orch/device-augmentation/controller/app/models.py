from __future__ import annotations

from datetime import datetime
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

JsonValue: TypeAlias = Any
JsonMap: TypeAlias = dict[str, JsonValue]


class VirtualResourceTwin(BaseModel):
    model_config = ConfigDict(frozen=True)

    availability: str = "unknown"
    node_ready: bool = False
    pod_ready: bool = False
    endpoint_ready: bool = False
    current_load: str = "unknown"
    binding_state: str = "unknown"
    status_reason: str = "-"


class VirtualResourceProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    node: str
    resource_type: str
    capabilities: tuple[str, ...] = Field(default_factory=tuple)
    desired_instances: int = 0
    observed_instances: int = 0
    free_instances: int = 0
    allocated_instances: int = 0
    status: str = "unknown"
    twin: VirtualResourceTwin


class VirtualResourceState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: str
    scope: str
    observation_error: str | None = None
    resources: tuple[VirtualResourceProfile, ...] = Field(default_factory=tuple)
