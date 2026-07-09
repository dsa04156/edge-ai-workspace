from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from .augmentation_crds import AugmentationResourceCrdState, DeviceAugmentationCrdState
from .runtime_augmentation import RuntimeAugmentationState, build_runtime_augmentation_state
from .virtual_resources import JsonMap


@dataclass(frozen=True, slots=True)
class RuntimeAugmentationQuery:
    refresh: bool = False
    namespace: str = "default"
    mode: str = "observed"


class ResourceProfileSource(Protocol):
    async def get_resource_profile_state(self, refresh: bool = False) -> JsonMap: ...


class AugmentationCrdSource(Protocol):
    async def get_augmentation_resources(self) -> AugmentationResourceCrdState: ...

    async def get_device_augmentations(self, namespace: str = "default") -> DeviceAugmentationCrdState: ...


async def runtime_resource_augmentation_state(
    service: ResourceProfileSource,
    crds: AugmentationCrdSource,
    query: RuntimeAugmentationQuery,
) -> RuntimeAugmentationState:
    if query.mode == "demo":
        return build_runtime_augmentation_state()
    try:
        resource_state = await service.get_resource_profile_state(refresh=query.refresh)
    except httpx.HTTPError:
        resource_state = {}
    resource_crds = await crds.get_augmentation_resources()
    device_crds = await crds.get_device_augmentations(namespace=query.namespace)
    return build_runtime_augmentation_state(
        service_resource_profiles=_resource_profile_items(resource_state),
        augmentation_resources=resource_crds.resources,
        device_augmentations=device_crds.device_augmentations,
    )


def _resource_profile_items(resource_state: JsonMap) -> list[JsonMap]:
    profiles = resource_state.get("service_resource_profiles")
    if not isinstance(profiles, list):
        return []
    return [item for item in profiles if isinstance(item, dict)]
