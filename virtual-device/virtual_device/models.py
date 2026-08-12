from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import DeviceProfile


@dataclass(frozen=True)
class DataPoint:
    value: Any
    unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"value": self.value}
        if self.unit is not None:
            result["unit"] = self.unit
        return result


@dataclass(frozen=True)
class Quality:
    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"valid": self.valid}
        if self.errors:
            result["errors"] = list(self.errors)
        return result


@dataclass(frozen=True)
class NormalizedSample:
    source_timestamp: Any
    collected_at: int
    data: dict[str, DataPoint]
    quality: Quality

    def fingerprint_data(self) -> dict[str, dict[str, Any]]:
        return {name: point.to_dict() for name, point in sorted(self.data.items())}


@dataclass(frozen=True)
class TelemetryEnvelope:
    schema_version: str
    virtual_device_id: str
    physical_device_id: str
    node_id: str
    capability: str
    source_timestamp: Any
    collected_at: int
    sequence: int
    data: dict[str, DataPoint]
    quality: Quality

    @classmethod
    def from_sample(
        cls,
        profile: DeviceProfile,
        sample: NormalizedSample,
        *,
        sequence: int,
    ) -> TelemetryEnvelope:
        return cls(
            schema_version="v1alpha1",
            virtual_device_id=profile.virtual_device_id,
            physical_device_id=profile.physical_device_id,
            node_id=profile.node_id,
            capability=profile.capability,
            source_timestamp=sample.source_timestamp,
            collected_at=sample.collected_at,
            sequence=sequence,
            data=sample.data,
            quality=sample.quality,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "virtualDeviceId": self.virtual_device_id,
            "physicalDeviceId": self.physical_device_id,
            "nodeId": self.node_id,
            "capability": self.capability,
            "sourceTimestamp": self.source_timestamp,
            "collectedAt": self.collected_at,
            "sequence": self.sequence,
            "data": {name: point.to_dict() for name, point in self.data.items()},
            "quality": self.quality.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
