#!/usr/bin/env python3
"""Patch KubeEdge DeviceStatus CRs from cloud-side mapper liveness.

This is a cloud-side bridge for clusters where mapper DMI ReportDeviceStatus
reaches edgecore but is not persisted back into DeviceStatus.status by the
current KubeEdge sync path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException

GROUP = "devices.kubeedge.io"
VERSION = "v1beta1"
NAMESPACE = "default"
STATUS_FIELDS = (
    "health",
    "severity",
    "online",
    "mapperLastSeen",
    "statusLastSeen",
    "statusSource",
    "last_error_code",
    "last_error_message",
)


def load_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def object_key(item: dict[str, Any]) -> tuple[str, str]:
    meta = item.get("metadata") or {}
    return meta.get("namespace", NAMESPACE), meta.get("name", "")


def mapper_nodes(v1: client.CoreV1Api) -> set[str]:
    pods = v1.list_namespaced_pod(NAMESPACE, label_selector="app=mqttvirtual-mapper").items
    nodes: set[str] = set()
    for pod in pods:
        if pod.status and pod.status.phase == "Running" and pod.spec and pod.spec.node_name:
            nodes.add(pod.spec.node_name)
    return nodes


def status_values(device: dict[str, Any], running_nodes: set[str], now: str) -> dict[str, str]:
    spec = device.get("spec") or {}
    node_name = spec.get("nodeName")
    online = bool(node_name and node_name in running_nodes)
    return {
        "health": "online" if online else "offline",
        "severity": "normal" if online else "critical",
        "online": "true" if online else "false",
        "mapperLastSeen": now,
        "statusLastSeen": now,
        "statusSource": "mapper-framework/bridge",
        "last_error_code": "" if online else "mapper_not_running",
        "last_error_message": "" if online else f"mqttvirtual mapper pod is not running on node {node_name or 'unknown'}",
    }


def twin(name: str, value: str, now: str) -> dict[str, Any]:
    return {
        "propertyName": name,
        "reported": {
            "value": value,
            "metadata": {"timestamp": now, "type": "string"},
        },
        "observedDesired": {"value": "", "metadata": {}},
    }


def ensure_status_object(api: client.CustomObjectsApi, device: dict[str, Any]) -> None:
    namespace, name = object_key(device)
    try:
        api.get_namespaced_custom_object(GROUP, VERSION, namespace, "devicestatuses", name)
        return
    except ApiException as exc:
        if exc.status != 404:
            raise
    meta = device.get("metadata") or {}
    body = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "DeviceStatus",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "ownerReferences": [
                {
                    "apiVersion": f"{GROUP}/{VERSION}",
                    "kind": "Device",
                    "name": name,
                    "uid": meta.get("uid"),
                    "controller": True,
                    "blockOwnerDeletion": True,
                }
            ] if meta.get("uid") else [],
        },
        "spec": {},
    }
    api.create_namespaced_custom_object(GROUP, VERSION, namespace, "devicestatuses", body)


def patch_device_status(api: client.CustomObjectsApi, device: dict[str, Any], running_nodes: set[str], now: str) -> None:
    namespace, name = object_key(device)
    if not name:
        return
    ensure_status_object(api, device)
    values = status_values(device, running_nodes, now)
    body = {
        "status": {
            "state": "online" if values["online"] == "true" else "offline",
            "lastOnlineTime": now,
            "twins": [twin(field, values[field], now) for field in STATUS_FIELDS],
        }
    }
    api.patch_namespaced_custom_object(GROUP, VERSION, namespace, "devicestatuses", name, body)
    print(f"patched {namespace}/{name} online={values['online']} source={values['statusSource']}")


def main() -> int:
    load_config()
    api = client.CustomObjectsApi()
    v1 = client.CoreV1Api()
    running_nodes = mapper_nodes(v1)
    now = utc_now()
    devices = api.list_cluster_custom_object(GROUP, VERSION, "devices").get("items", [])
    count = 0
    for device in devices:
        spec = device.get("spec") or {}
        protocol = (spec.get("protocol") or {}).get("protocolName")
        namespace, name = object_key(device)
        if namespace != NAMESPACE or protocol != "mqttvirtual":
            continue
        patch_device_status(api, device, running_nodes, now)
        count += 1
    print(f"patched_device_status_count={count} mapper_nodes={sorted(running_nodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
