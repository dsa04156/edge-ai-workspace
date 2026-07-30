from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item.capitalize() for item in tail)


class DeviceSourceModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


DeviceSourceReadMode = Literal["local_latest", "local_window", "history"]
DeviceSourceKind = Literal["device_service_local_cache", "edgex_core_data"]


class DeviceSourceEndpoint(DeviceSourceModel):
    service_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9._~-]+$",
    )
    node_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9._~-]+$",
    )
    base_url: str = Field(min_length=1, max_length=2048)
    read_modes: list[Literal["local_latest", "local_window"]] = Field(
        default_factory=lambda: ["local_latest", "local_window"],
        min_length=1,
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_modes(self) -> "DeviceSourceEndpoint":
        if len(self.read_modes) != len(set(self.read_modes)):
            raise ValueError("readModes must not contain duplicates")
        return self


class DeviceSourceCatalogDocument(DeviceSourceModel):
    version: int = Field(default=1, ge=1)
    services: list[DeviceSourceEndpoint] = Field(default_factory=list)


class DeviceSourceBindingRequest(DeviceSourceModel):
    device_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9._~-]+$",
    )
    resource_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9._~-]+$",
    )
    read_mode: DeviceSourceReadMode = "local_window"
    window: str = Field(default="-10s", pattern=r"^-[1-9][0-9]*[smhdw]$")
    limit: int = Field(default=100, ge=1, le=1000)


class DeviceSourceBinding(DeviceSourceModel):
    device_name: str
    resource_name: str
    read_mode: DeviceSourceReadMode
    window: str
    limit: int
    profile_name: str
    device_service_name: str
    node_name: str | None = None
    admin_state: str
    operating_state: str


class DeviceSourceRetention(DeviceSourceModel):
    max_age: str
    max_samples: int = Field(gt=0)
    max_bytes: int | None = Field(default=None, gt=0)


class DeviceSourceSample(DeviceSourceModel):
    origin: int = Field(gt=0)
    timestamp: datetime
    resource_name: str
    value_type: str
    value: Any
    source_name: str | None = None
    event_id: str | None = None
    units: str | None = None


class DeviceSourceSampleResponse(DeviceSourceModel):
    sampled_at: datetime
    preview_only: Literal[True] = True
    source_kind: DeviceSourceKind
    durable: bool
    binding: DeviceSourceBinding
    retention: DeviceSourceRetention | None = None
    samples: list[DeviceSourceSample] = Field(default_factory=list)
