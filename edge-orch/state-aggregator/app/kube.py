from __future__ import annotations

import logging
from typing import Any

from kubernetes import client, config

logger = logging.getLogger(__name__)


class KubeClient:
    def __init__(self) -> None:
        self.enabled = True
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except Exception:
                logger.warning("Failed to load kube config, kubernetes features will be disabled")
                self.enabled = False
        
        self.v1 = client.CoreV1Api()
        self.custom = client.CustomObjectsApi()

    async def get_node_map(self) -> dict[str, dict[str, str]]:
        """
        Returns a map of IP:Port -> {hostname, node_type}
        """
        node_map = {}
        try:
            nodes = self.v1.list_node()
            for node in nodes.items:
                hostname = node.metadata.name
                node_type = self._determine_node_type(node)
                
                # Find InternalIP
                ip = None
                for addr in node.status.addresses:
                    if addr.type == "InternalIP":
                        ip = addr.address
                        break
                
                if ip:
                    # Map both plain IP and common node-exporter port
                    key = f"{ip}:9100"
                    node_map[key] = {
                        "hostname": hostname,
                        "node_type": node_type
                    }
                    # Also map the IP itself just in case
                    node_map[ip] = {
                        "hostname": hostname,
                        "node_type": node_type
                    }
        except Exception:
            logger.exception("Failed to list nodes from Kubernetes API")
        
        return node_map

    async def get_devices(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            response = self.custom.list_cluster_custom_object(
                group="devices.kubeedge.io",
                version="v1beta1",
                plural="devices",
            )
        except Exception:
            logger.exception("Failed to list KubeEdge devices")
            return []
        items = response.get("items", [])
        return [item for item in items if isinstance(item, dict)]

    async def get_device_statuses(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            response = self.custom.list_cluster_custom_object(
                group="devices.kubeedge.io",
                version="v1beta1",
                plural="devicestatuses",
            )
        except Exception:
            logger.exception("Failed to list KubeEdge device statuses")
            return []
        items = response.get("items", [])
        return [item for item in items if isinstance(item, dict)]

    async def get_node_readiness(self) -> dict[str, bool]:
        if not self.enabled:
            return {}
        try:
            nodes = self.v1.list_node()
        except Exception:
            logger.exception("Failed to list node readiness")
            return {}

        readiness: dict[str, bool] = {}
        for node in nodes.items:
            name = node.metadata.name
            ready = False
            status = node.status
            for condition in (status.conditions if status is not None else []) or []:
                if condition.type == "Ready":
                    ready = condition.status == "True"
                    break
            if name:
                readiness[name] = ready
        return readiness

    async def get_running_mapper_nodes(self, namespace: str = "default") -> set[str]:
        if not self.enabled:
            return set()
        try:
            pods = self.v1.list_namespaced_pod(
                namespace=namespace,
                label_selector="app=mqttvirtual-mapper",
            )
        except Exception:
            logger.exception("Failed to list mapper pods")
            return set()

        nodes: set[str] = set()
        for pod in pods.items:
            status = pod.status
            if status is None or status.phase != "Running" or not pod.spec.node_name:
                continue
            if not self._pod_ready(pod):
                continue
            nodes.add(pod.spec.node_name)
        return nodes

    def _pod_ready(self, pod: client.V1Pod) -> bool:
        status = pod.status
        if status is None:
            return False
        for condition in status.conditions or []:
            if condition.type == "Ready":
                return condition.status == "True"
        return False

    def _determine_node_type(self, node: client.V1Node) -> str:
        labels = node.metadata.labels or {}
        
        if "node-role.kubernetes.io/control-plane" in labels:
            return "cloud_server"
        if labels.get("environment") == "cloud":
            return "cloud_server"
        
        # KubeEdge specific roles
        if "node-role.kubernetes.io/edge" in labels:
            # Simple heuristic for Jetson vs Raspi if not labeled
            if "jetorn" in node.metadata.name.lower():
                return "edge_ai_device"
            if "raspi" in node.metadata.name.lower():
                return "edge_light_device"
            return "edge_device"
            
        return "unknown"
