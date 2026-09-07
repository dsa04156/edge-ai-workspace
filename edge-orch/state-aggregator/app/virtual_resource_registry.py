"""Git-owned definitions; registration is independent from runtime existence.

The CR-shaped fields retain AugmentationResource / DeviceAugmentation roles.
No CRD or legacy controller is installed by this file registry.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID_LABEL = "edge-ai.io/virtual-device-id"


class Contract(BaseModel):
    model_config = ConfigDict(extra="allow")


class Metadata(Contract):
    name: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class WorkloadRef(Contract):
    kind: Literal["Deployment"] = "Deployment"
    name: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class RuntimeRef(Contract):
    namespace: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
    podSelector: dict[str, str] = Field(default_factory=dict)
    workloadRef: WorkloadRef | None = None
    port: int = Field(default=8080, ge=1, le=65535)


class ResourceSpec(Contract):
    displayName: str
    resourceType: str
    nodeSelector: dict[str, str] = Field(default_factory=dict)
    stageTypes: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    runtimeRef: RuntimeRef
    model: dict[str, str] = Field(default_factory=dict)


class AugmentationResource(Contract):
    apiVersion: str = "augmentation.edge-ai.io/v1alpha1"
    kind: Literal["AugmentationResource"] = "AugmentationResource"
    metadata: Metadata
    spec: ResourceSpec


class TargetDevice(Contract):
    kind: str
    name: str


class AugmentationSpec(Contract):
    targetDevice: TargetDevice
    bindings: dict[str, str]
    workloadPolicy: dict = Field(default_factory=dict)


class DeviceAugmentation(Contract):
    apiVersion: str = "augmentation.edge-ai.io/v1alpha1"
    kind: Literal["DeviceAugmentation"] = "DeviceAugmentation"
    metadata: Metadata
    spec: AugmentationSpec


class VirtualDeviceRegistry(Contract):
    schemaVersion: Literal[1] = 1
    resources: list[AugmentationResource]
    connections: list[DeviceAugmentation] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [resource.metadata.name for resource in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate logical device ID")
        for connection in self.connections:
            if any(value not in ids for value in connection.spec.bindings.values()):
                raise ValueError("connection references an unregistered device")
        return self

    @classmethod
    def load(cls, path: Path | None = None):
        path = path or Path(os.getenv("VIRTUAL_DEVICE_REGISTRY_PATH", str(
            Path(__file__).parent / "config/virtual_devices.json")))
        return cls.model_validate(json.loads(path.read_text()))
