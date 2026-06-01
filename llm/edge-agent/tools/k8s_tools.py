from __future__ import annotations

from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException


def _load_k8s_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _object_meta(meta: Any) -> dict[str, Any]:
    return {
        "name": meta.name,
        "namespace": meta.namespace,
        "labels": meta.labels or {},
        "creation_timestamp": meta.creation_timestamp.isoformat()
        if meta.creation_timestamp
        else None,
    }


def get_k8s_nodes() -> dict[str, Any]:
    try:
        _load_k8s_config()
        nodes = client.CoreV1Api().list_node().items
        return {
            "nodes": [
                {
                    **_object_meta(node.metadata),
                    "ready": any(
                        condition.type == "Ready" and condition.status == "True"
                        for condition in (node.status.conditions or [])
                    ),
                    "roles": [
                        key.replace("node-role.kubernetes.io/", "")
                        for key in (node.metadata.labels or {})
                        if key.startswith("node-role.kubernetes.io/")
                    ],
                    "capacity": node.status.capacity or {},
                    "allocatable": node.status.allocatable or {},
                    "node_info": node.status.node_info.to_dict()
                    if node.status.node_info
                    else {},
                }
                for node in nodes
            ]
        }
    except (ApiException, config.ConfigException) as exc:
        return {"error": str(exc)}


def get_k8s_pods(
    namespace: str | None = None, label_selector: str | None = None
) -> dict[str, Any]:
    try:
        _load_k8s_config()
        api = client.CoreV1Api()
        if namespace:
            pods = api.list_namespaced_pod(
                namespace=namespace, label_selector=label_selector
            ).items
        else:
            pods = api.list_pod_for_all_namespaces(label_selector=label_selector).items
        return {
            "pods": [
                {
                    **_object_meta(pod.metadata),
                    "phase": pod.status.phase,
                    "node_name": pod.spec.node_name,
                    "pod_ip": pod.status.pod_ip,
                    "host_ip": pod.status.host_ip,
                    "containers": [
                        {
                            "name": status.name,
                            "ready": status.ready,
                            "restart_count": status.restart_count,
                            "state": status.state.to_dict() if status.state else {},
                        }
                        for status in (pod.status.container_statuses or [])
                    ],
                }
                for pod in pods
            ]
        }
    except (ApiException, config.ConfigException) as exc:
        return {"error": str(exc)}


def get_k8s_events(namespace: str | None = None) -> dict[str, Any]:
    try:
        _load_k8s_config()
        api = client.CoreV1Api()
        if namespace:
            events = api.list_namespaced_event(namespace=namespace).items
        else:
            events = api.list_event_for_all_namespaces().items
        return {
            "events": [
                {
                    **_object_meta(event.metadata),
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "involved_object": {
                        "kind": event.involved_object.kind,
                        "name": event.involved_object.name,
                        "namespace": event.involved_object.namespace,
                    },
                    "last_timestamp": event.last_timestamp.isoformat()
                    if event.last_timestamp
                    else None,
                }
                for event in events[-100:]
            ]
        }
    except (ApiException, config.ConfigException) as exc:
        return {"error": str(exc)}


def get_gpu_status(node_name: str | None = None) -> dict[str, Any]:
    """Return GPU capacity/allocatable information from Kubernetes node status."""

    node_data = get_k8s_nodes()
    if "error" in node_data:
        return node_data
    gpu_keys = (
        "nvidia.com/gpu",
        "amd.com/gpu",
        "intel.com/gpu",
        "kubeedge.io/gpu",
    )
    nodes = []
    for node in node_data.get("nodes", []):
        if node_name and node["name"] != node_name:
            continue
        capacity = node.get("capacity", {})
        allocatable = node.get("allocatable", {})
        nodes.append(
            {
                "name": node["name"],
                "ready": node["ready"],
                "gpu_capacity": {
                    key: capacity.get(key) for key in gpu_keys if key in capacity
                },
                "gpu_allocatable": {
                    key: allocatable.get(key) for key in gpu_keys if key in allocatable
                },
                "labels": node.get("labels", {}),
            }
        )
    return {"nodes": nodes}
