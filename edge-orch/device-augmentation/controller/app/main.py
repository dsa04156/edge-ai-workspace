from __future__ import annotations

import os
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from .models import JsonMap, VirtualResourceState
from .status_builder import augmentation_resource_status, device_augmentation_status

GROUP = "augmentation.edge-ai.io"
VERSION = "v1alpha1"
RESOURCE_PLURAL = "augmentationresources"
BINDING_PLURAL = "deviceaugmentations"


@dataclass(frozen=True, slots=True)
class Settings:
    state_aggregator_url: str
    namespace: str
    poll_interval_seconds: int


def settings_from_env() -> Settings:
    return Settings(
        state_aggregator_url=os.getenv("STATE_AGGREGATOR_URL", "http://state-aggregator.default.svc.cluster.local:8000").rstrip("/"),
        namespace=os.getenv("AUGMENTATION_NAMESPACE", "default"),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "15")),
    )


def load_kube_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def fetch_virtual_resource_state(settings: Settings) -> VirtualResourceState:
    with httpx.Client(timeout=10.0) as http:
        response = http.get(f"{settings.state_aggregator_url}/state/virtual-resources", headers={"Accept": "application/json"})
        response.raise_for_status()
        return VirtualResourceState.model_validate(response.json())


def iter_items(response: JsonMap) -> Iterator[JsonMap]:
    items = response.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict):
            yield item


def resource_name(resource: JsonMap) -> str | None:
    metadata = resource.get("metadata")
    if not isinstance(metadata, dict):
        return None
    name = metadata.get("name")
    if not isinstance(name, str):
        return None
    return name


def declared_capabilities(resource: JsonMap) -> tuple[str, ...]:
    spec = resource.get("spec")
    if not isinstance(spec, dict):
        return ()
    capabilities = spec.get("capabilities")
    if not isinstance(capabilities, list):
        return ()
    return tuple(capability for capability in capabilities if isinstance(capability, str))


class DeviceAugmentationController:
    def __init__(self, custom_api: client.CustomObjectsApi, settings: Settings) -> None:
        self.custom_api = custom_api
        self.settings = settings

    def reconcile_once(self) -> None:
        state = fetch_virtual_resource_state(self.settings)
        resources = {resource.id: resource for resource in state.resources}
        resource_objects = self.custom_api.list_cluster_custom_object(
            group=GROUP,
            version=VERSION,
            plural=RESOURCE_PLURAL,
        )
        declared_resource_capabilities = {
            name: declared_capabilities(resource)
            for resource in iter_items(resource_objects)
            if (name := resource_name(resource)) is not None
        }
        for resource in state.resources:
            self.custom_api.patch_cluster_custom_object_status(
                group=GROUP,
                version=VERSION,
                plural=RESOURCE_PLURAL,
                name=resource.id,
                body=augmentation_resource_status(resource, state.generated_at),
            )
        bindings = self.custom_api.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=self.settings.namespace,
            plural=BINDING_PLURAL,
        )
        for binding in iter_items(bindings):
            name = resource_name(binding)
            if name is None:
                continue
            self.custom_api.patch_namespaced_custom_object_status(
                group=GROUP,
                version=VERSION,
                namespace=self.settings.namespace,
                plural=BINDING_PLURAL,
                name=name,
                body=device_augmentation_status(
                    binding,
                    resources,
                    declared_resource_capabilities,
                    state.generated_at,
                ),
            )

    def run_forever(self) -> None:
        while True:
            try:
                self.reconcile_once()
            except (httpx.HTTPError, ApiException) as exc:
                print(f"device augmentation reconcile failed: {exc}", flush=True)
            time.sleep(self.settings.poll_interval_seconds)


def main() -> None:
    load_kube_config()
    controller = DeviceAugmentationController(client.CustomObjectsApi(), settings_from_env())
    controller.run_forever()


if __name__ == "__main__":
    main()
