from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from .resource_pool import (
    KubernetesNodeResourceSnapshot,
    build_kubernetes_resource_snapshots,
    pod_spec_limits,
    pod_spec_requests,
)
from .runtime_recommendation import RuntimeWorkloadSnapshot

logger = logging.getLogger(__name__)


class KubeResourceReadError(RuntimeError):
    pass


class KubeDeploymentError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


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
        self.apps = client.AppsV1Api()

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

    async def get_scheduling_resource_snapshots(
        self,
    ) -> list[KubernetesNodeResourceSnapshot]:
        """Read allocatable capacity and requests reserved by non-terminal Pods."""
        if not self.enabled:
            raise KubeResourceReadError("Kubernetes client is unavailable")
        try:
            nodes = self.v1.list_node().items
            pods = self.v1.list_pod_for_all_namespaces().items
        except Exception as exc:
            logger.exception("Failed to read Kubernetes scheduling resources")
            raise KubeResourceReadError(
                "Failed to read Kubernetes scheduling resources"
            ) from exc
        return build_kubernetes_resource_snapshots(
            nodes,
            pods,
            self._determine_node_type,
        )

    async def deployment_exists(self, namespace: str, name: str) -> bool:
        if not self.enabled:
            raise KubeDeploymentError(
                "kubernetes_client_unavailable",
                "Kubernetes client is unavailable",
            )
        try:
            await asyncio.to_thread(
                self.apps.read_namespaced_deployment,
                name=name,
                namespace=namespace,
            )
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            reason = (
                "deployment_read_forbidden"
                if exc.status == 403
                else "deployment_state_unavailable"
            )
            raise KubeDeploymentError(reason, _api_error_message(exc)) from exc
        except Exception as exc:
            raise KubeDeploymentError(
                "deployment_state_unavailable",
                f"Failed to read Deployment: {type(exc).__name__}",
            ) from exc

    async def create_deployment(self, namespace: str, body: dict[str, Any]) -> Any:
        if not self.enabled:
            raise KubeDeploymentError(
                "kubernetes_client_unavailable",
                "Kubernetes client is unavailable",
            )
        try:
            return await asyncio.to_thread(
                self.apps.create_namespaced_deployment,
                namespace=namespace,
                body=body,
            )
        except ApiException as exc:
            reason = {
                403: "deployment_create_forbidden",
                409: "deployment_already_exists",
                422: "deployment_manifest_rejected",
            }.get(exc.status, "deployment_create_failed")
            raise KubeDeploymentError(reason, _api_error_message(exc)) from exc
        except Exception as exc:
            raise KubeDeploymentError(
                "deployment_create_failed",
                f"Failed to create Deployment: {type(exc).__name__}",
            ) from exc

    async def read_deployment(self, namespace: str, name: str) -> Any:
        try:
            return await asyncio.to_thread(
                self.apps.read_namespaced_deployment,
                name=name,
                namespace=namespace,
            )
        except ApiException as exc:
            raise KubeDeploymentError(
                "deployment_state_unavailable",
                _api_error_message(exc),
            ) from exc
        except Exception as exc:
            raise KubeDeploymentError(
                "deployment_state_unavailable",
                f"Failed to observe Deployment: {type(exc).__name__}",
            ) from exc

    async def list_deployment_pods(self, namespace: str, name: str) -> list[Any]:
        try:
            result = await asyncio.to_thread(
                self.v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"edge-ai.io/deployment={name}",
            )
            return list(result.items)
        except ApiException as exc:
            raise KubeDeploymentError(
                "pod_state_unavailable",
                _api_error_message(exc),
            ) from exc
        except Exception as exc:
            raise KubeDeploymentError(
                "pod_state_unavailable",
                f"Failed to observe Pods: {type(exc).__name__}",
            ) from exc

    async def get_running_service_pods(self) -> list[dict[str, Any]]:
        """Return running pod resource declarations for service requirement profiling."""
        if not self.enabled:
            return []
        try:
            pods = self.v1.list_pod_for_all_namespaces(field_selector="status.phase=Running")
        except Exception:
            logger.exception("Failed to list running pods for service resource profiling")
            return []

        results: list[dict[str, Any]] = []
        for pod in pods.items:
            metadata = pod.metadata
            spec = pod.spec
            status = pod.status
            if metadata is None or spec is None or status is None:
                continue
            labels = metadata.labels or {}
            results.append(
                {
                    "namespace": metadata.namespace,
                    "name": metadata.name,
                    "workload": self._workload_name(pod),
                    "node": spec.node_name,
                    "phase": status.phase,
                    "ready": self._pod_ready(pod),
                    "labels": labels,
                    "containers": [
                        {
                            "name": container.name,
                            "requests": dict((container.resources.requests or {}) if container.resources else {}),
                            "limits": dict((container.resources.limits or {}) if container.resources else {}),
                        }
                        for container in spec.containers or []
                    ],
                }
            )
        return results

    async def get_runtime_workload(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        selector: dict[str, str],
    ) -> RuntimeWorkloadSnapshot:
        """Read one catalog-owned workload and all Pods selected by its labels."""
        if not self.enabled:
            return RuntimeWorkloadSnapshot(
                namespace=namespace,
                kind=kind,
                name=name,
                observed=False,
                exists=False,
                reason_codes=("kubernetes_client_unavailable",),
            )
        try:
            if kind == "Deployment":
                workload = await asyncio.to_thread(
                    self.apps.read_namespaced_deployment,
                    name=name,
                    namespace=namespace,
                )
            elif kind == "StatefulSet":
                workload = await asyncio.to_thread(
                    self.apps.read_namespaced_stateful_set,
                    name=name,
                    namespace=namespace,
                )
            else:
                return RuntimeWorkloadSnapshot(
                    namespace=namespace,
                    kind=kind,
                    name=name,
                    observed=False,
                    exists=False,
                    reason_codes=("workload_kind_unsupported",),
                )
            label_selector = ",".join(
                f"{key}={value}" for key, value in sorted(selector.items())
            )
            pods = await asyncio.to_thread(
                self.v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=label_selector,
            )
        except ApiException as exc:
            if exc.status == 404:
                return RuntimeWorkloadSnapshot(
                    namespace=namespace,
                    kind=kind,
                    name=name,
                    observed=True,
                    exists=False,
                    reason_codes=("runtime_workload_not_found",),
                )
            logger.exception("Failed to read runtime workload %s/%s", namespace, name)
            return RuntimeWorkloadSnapshot(
                namespace=namespace,
                kind=kind,
                name=name,
                observed=False,
                exists=False,
                reason_codes=(
                    "runtime_workload_read_forbidden"
                    if exc.status == 403
                    else "runtime_workload_observation_unavailable",
                ),
            )
        except Exception:
            logger.exception("Failed to read runtime workload %s/%s", namespace, name)
            return RuntimeWorkloadSnapshot(
                namespace=namespace,
                kind=kind,
                name=name,
                observed=False,
                exists=False,
                reason_codes=("runtime_workload_observation_unavailable",),
            )

        status = getattr(workload, "status", None)
        spec = getattr(workload, "spec", None)
        template = getattr(spec, "template", None)
        pod_spec = getattr(template, "spec", None)
        desired = int(getattr(spec, "replicas", None) or 0)
        ready = int(getattr(status, "ready_replicas", None) or 0)
        current_nodes = sorted(
            {
                pod.spec.node_name
                for pod in pods.items
                if getattr(pod, "spec", None) is not None and pod.spec.node_name
            }
        )
        restart_count = sum(
            int(getattr(container_status, "restart_count", None) or 0)
            for pod in pods.items
            for container_status in (
                getattr(getattr(pod, "status", None), "container_statuses", None) or []
            )
        )
        pod_failure = bool(
            _workload_progress_failed(status)
            or any(_runtime_pod_failed(pod) for pod in pods.items)
        )
        return RuntimeWorkloadSnapshot(
            namespace=namespace,
            kind=kind,
            name=name,
            observed=True,
            exists=True,
            desired_replicas=desired,
            ready_replicas=ready,
            current_nodes=tuple(current_nodes),
            pod_restart_count=restart_count,
            pod_failure=pod_failure,
            reason_codes=tuple(_runtime_workload_reasons(pods.items, desired, ready)),
            placement_profile=_runtime_placement_profile(
                namespace,
                name,
                pod_spec,
                desired,
                ready,
            ),
        )

    @staticmethod
    def _pod_ready(pod: client.V1Pod) -> bool:
        status = pod.status
        for condition in (status.conditions if status is not None else []) or []:
            if condition.type == "Ready":
                return condition.status == "True"
        return False

    def _workload_name(self, pod: client.V1Pod) -> str:
        metadata = pod.metadata
        labels = metadata.labels or {} if metadata is not None else {}
        for key in ("app.kubernetes.io/name", "app", "k8s-app"):
            if labels.get(key):
                return labels[key]
        owner_refs = metadata.owner_references or [] if metadata is not None else []
        for owner in owner_refs:
            if owner.name:
                return owner.name
        return metadata.name if metadata is not None and metadata.name else "unknown"

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


def _api_error_message(exc: ApiException) -> str:
    detail = exc.reason or f"Kubernetes API status {exc.status}"
    return str(detail)[:500]


def _runtime_pod_failed(pod: Any) -> bool:
    status = getattr(pod, "status", None)
    if getattr(status, "phase", None) == "Failed":
        return True
    failure_reasons = {
        "CrashLoopBackOff",
        "CreateContainerConfigError",
        "CreateContainerError",
        "ErrImagePull",
        "ImagePullBackOff",
        "RunContainerError",
    }
    for item in getattr(status, "container_statuses", None) or []:
        waiting = getattr(getattr(item, "state", None), "waiting", None)
        terminated = getattr(getattr(item, "state", None), "terminated", None)
        if getattr(waiting, "reason", None) in failure_reasons:
            return True
        if terminated is not None and int(getattr(terminated, "exit_code", 0) or 0) != 0:
            return True
    return False


def _workload_progress_failed(status: Any) -> bool:
    for condition in getattr(status, "conditions", None) or []:
        if (
            getattr(condition, "type", None) == "Progressing"
            and getattr(condition, "status", None) == "False"
            and getattr(condition, "reason", None) == "ProgressDeadlineExceeded"
        ):
            return True
    return False


def _runtime_workload_reasons(
    pods: list[Any],
    desired: int,
    ready: int,
) -> list[str]:
    reasons = []
    if ready < desired:
        reasons.append("workload_ready_replicas_insufficient")
    if any(_runtime_pod_failed(pod) for pod in pods):
        reasons.append("pod_runtime_failure")
    if not pods:
        reasons.append("runtime_pods_not_found")
    return reasons


def _runtime_placement_profile(
    namespace: str,
    name: str,
    pod_spec: Any,
    desired: int,
    ready: int,
) -> dict[str, Any] | None:
    if pod_spec is None:
        return None
    containers = [
        *(getattr(pod_spec, "containers", None) or []),
        *(getattr(pod_spec, "init_containers", None) or []),
    ]
    missing_cpu = sum(
        1
        for container in containers
        if "cpu"
        not in dict(
            getattr(getattr(container, "resources", None), "requests", None) or {}
        )
    )
    missing_memory = sum(
        1
        for container in containers
        if "memory"
        not in dict(
            getattr(getattr(container, "resources", None), "requests", None) or {}
        )
    )
    requests = pod_spec_requests(pod_spec)
    limits = pod_spec_limits(pod_spec)
    container_count = len(containers)
    coverage = (
        ((container_count - missing_cpu) + (container_count - missing_memory))
        / (container_count * 2)
        if container_count
        else 0
    )
    gpu_units = max(limits.accelerator_units.values(), default=0.0)
    return {
        "namespace": namespace,
        "service": name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pod_count": 1,
        "ready_pod_count": min(1, ready),
        "observed_desired_replicas": desired,
        "request_coverage_ratio": round(coverage, 6),
        "resource_requirements": {
            "requests": {
                "cpu_cores": requests.cpu_cores,
                "memory_mib": round(requests.memory_bytes / 1024 / 1024, 6),
            },
            "limits": {
                "cpu_cores": limits.cpu_cores,
                "memory_mib": round(limits.memory_bytes / 1024 / 1024, 6),
                "gpu_units": gpu_units,
            },
            "missing": {
                "cpu_request_containers": missing_cpu,
                "memory_request_containers": missing_memory,
            },
        },
    }
