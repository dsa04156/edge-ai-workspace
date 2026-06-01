from __future__ import annotations

from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException


def _load_k8s_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def get_kubeedge_devices(namespace: str | None = None) -> dict[str, Any]:
    try:
        _load_k8s_config()
        api = client.CustomObjectsApi()
        if namespace:
            devices = api.list_namespaced_custom_object(
                group="devices.kubeedge.io",
                version="v1alpha2",
                namespace=namespace,
                plural="devices",
            )
        else:
            devices = api.list_cluster_custom_object(
                group="devices.kubeedge.io",
                version="v1alpha2",
                plural="devices",
            )
        return {"devices": devices.get("items", [])}
    except (ApiException, config.ConfigException) as exc:
        return {"error": str(exc)}


def get_device_twin(device_name: str, namespace: str) -> dict[str, Any]:
    try:
        _load_k8s_config()
        api = client.CustomObjectsApi()
        device = api.get_namespaced_custom_object(
            group="devices.kubeedge.io",
            version="v1alpha2",
            namespace=namespace,
            plural="devices",
            name=device_name,
        )
        return {
            "device": device_name,
            "namespace": namespace,
            "twin": device.get("status", {}).get("twins", []),
            "status": device.get("status", {}),
        }
    except (ApiException, config.ConfigException) as exc:
        return {"error": str(exc)}
