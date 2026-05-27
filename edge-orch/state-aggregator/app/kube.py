from __future__ import annotations

import logging
from datetime import datetime, timezone
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
        node_metadata_by_name: dict[str, dict[str, str]] = {}
        try:
            nodes = self.v1.list_node()
            for node in nodes.items:
                hostname = node.metadata.name
                node_type = self._determine_node_type(node)
                node_metadata_by_name[hostname] = {
                    "hostname": hostname,
                    "node_type": node_type,
                }
                
                # Find InternalIP
                ip = None
                for addr in node.status.addresses:
                    if addr.type == "InternalIP":
                        ip = addr.address
                        break
                
                if ip:
                    # Map both plain IP and common node-exporter port
                    key = f"{ip}:9100"
                    node_map[key] = node_metadata_by_name[hostname]
                    # Also map the IP itself just in case
                    node_map[ip] = node_metadata_by_name[hostname]

            # DCGM exporter usually exposes metrics through Pod IPs, e.g.
            # 10.244.x.y:9400. Map those Pod IP instances back to the hosting
            # Kubernetes node so GPU metrics merge with the node-exporter CPU
            # metrics instead of appearing as separate edge-node rows.
            dcgm_pods = self.v1.list_namespaced_pod(
                namespace="kube-system",
                label_selector="app=dcgm-exporter",
            )
            for pod in dcgm_pods.items:
                node_name = pod.spec.node_name if pod.spec is not None else None
                pod_ip = pod.status.pod_ip if pod.status is not None else None
                if not node_name or not pod_ip or node_name not in node_metadata_by_name:
                    continue
                node_map[pod_ip] = node_metadata_by_name[node_name]
                node_map[f"{pod_ip}:9400"] = node_metadata_by_name[node_name]
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

    async def bridge_device_status_heartbeats(self, namespace: str = "default") -> int:
        """Refresh DeviceStatus summary twins from live control-plane state.

        This cloud-side bridge is a safety path for clusters where mapper DMI
        ReportDeviceStatus succeeds at the edge but the cloud DeviceStatus CR is
        not persisted. It writes only control/status summary fields; raw sensor
        telemetry stays out of DeviceStatus.
        """
        if not self.enabled:
            return 0

        devices = await self.get_devices()
        mapper_nodes = await self.get_running_mapper_nodes(namespace=namespace)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        patched = 0

        for item in devices:
            metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
            spec = item.get("spec", {}) if isinstance(item, dict) else {}
            name = metadata.get("name")
            item_namespace = metadata.get("namespace") or namespace
            node_name = spec.get("nodeName", "")
            if not name or item_namespace != namespace:
                continue

            mapper_running = node_name in mapper_nodes
            state = "online" if mapper_running else "offline"
            health = "online" if mapper_running else "offline"
            severity = "normal" if mapper_running else "critical"
            payload = {
                "status": {
                    "state": state,
                    "lastOnlineTime": now,
                    "twins": [
                        self._status_twin("health", health, now),
                        self._status_twin("severity", severity, now),
                        self._status_twin("online", "true" if mapper_running else "false", now),
                        self._status_twin("mapperLastSeen", now if mapper_running else "", now),
                        self._status_twin("statusLastSeen", now, now),
                        self._status_twin("statusSource", "mapper-framework/bridge", now),
                        self._status_twin("last_error_code", "" if mapper_running else "mapper_not_running", now),
                        self._status_twin(
                            "last_error_message",
                            "" if mapper_running else f"mqttvirtual mapper is not running on node {node_name}",
                            now,
                        ),
                    ],
                }
            }
            try:
                self.custom.patch_namespaced_custom_object(
                    group="devices.kubeedge.io",
                    version="v1beta1",
                    namespace=item_namespace,
                    plural="devicestatuses",
                    name=name,
                    body=payload,
                )
                patched += 1
            except Exception:
                logger.exception("Failed to bridge DeviceStatus heartbeat for %s/%s", item_namespace, name)
        return patched

    def _status_twin(self, name: str, value: str, timestamp: str) -> dict[str, Any]:
        return {
            "propertyName": name,
            "observedDesired": {"value": "", "metadata": {}},
            "reported": {
                "value": value,
                "metadata": {"type": "string", "timestamp": timestamp},
            },
        }

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
