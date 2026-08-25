from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .kube import KubeClient, KubeDeploymentError
from .models import (
    DeploymentCreateRequest,
    DeploymentCreateResult,
    DeploymentPodObservation,
    PlacementSelectionResult,
)


class DeploymentController:
    def __init__(self, settings: Settings, kube: KubeClient) -> None:
        self.settings = settings
        self.kube = kube

    async def deploy(
        self,
        request: DeploymentCreateRequest,
        placement: PlacementSelectionResult,
        operation_id: str,
    ) -> DeploymentCreateResult:
        rejected = self._validate_request(request, placement, operation_id)
        if rejected is not None:
            return rejected

        assert placement.selected_node is not None
        assert placement.requirements is not None
        namespace = self.settings.deployment_target_namespace
        try:
            if await self.kube.deployment_exists(namespace, request.deployment_name):
                return self._result(
                    request,
                    placement,
                    operation_id,
                    status="failed",
                    created=False,
                    reason_codes=["deployment_already_exists"],
                    message="A Deployment with this name already exists; v1 never updates it.",
                )
            manifest = build_deployment_manifest(
                namespace,
                request,
                placement,
                operation_id,
                self.settings.deployment_ready_timeout_seconds,
            )
            await self.kube.create_deployment(namespace, manifest)
        except KubeDeploymentError as exc:
            return self._result(
                request,
                placement,
                operation_id,
                status="failed",
                created=False,
                reason_codes=[exc.reason_code],
                message=str(exc),
            )

        return await self._wait_until_ready(request, placement, operation_id)

    def _validate_request(
        self,
        request: DeploymentCreateRequest,
        placement: PlacementSelectionResult,
        operation_id: str,
    ) -> DeploymentCreateResult | None:
        if placement.status != "selected" or placement.selected_node is None:
            return self._result(
                request,
                placement,
                operation_id,
                status="rejected",
                created=False,
                reason_codes=["placement_not_selected", *placement.reason_codes],
                message="Placement did not produce an eligible node.",
            )
        if placement.service_profile.pod_count != 1:
            return self._result(
                request,
                placement,
                operation_id,
                status="rejected",
                created=False,
                reason_codes=["service_profile_replica_count_unsupported"],
                message="Deployment v1 requires a service profile derived from exactly one Pod.",
            )
        if not any(
            request.image.startswith(prefix)
            for prefix in self.settings.deployment_allowed_image_prefixes
        ):
            return self._result(
                request,
                placement,
                operation_id,
                status="rejected",
                created=False,
                reason_codes=["image_not_allowed"],
                message="Image is outside the configured immutable-image allowlist.",
            )
        return None

    async def _wait_until_ready(
        self,
        request: DeploymentCreateRequest,
        placement: PlacementSelectionResult,
        operation_id: str,
    ) -> DeploymentCreateResult:
        namespace = self.settings.deployment_target_namespace
        deadline = time.monotonic() + self.settings.deployment_ready_timeout_seconds
        last_pods: list[DeploymentPodObservation] = []
        while True:
            try:
                deployment = await self.kube.read_deployment(
                    namespace,
                    request.deployment_name,
                )
                pods = await self.kube.list_deployment_pods(
                    namespace,
                    request.deployment_name,
                )
            except KubeDeploymentError as exc:
                return self._result(
                    request,
                    placement,
                    operation_id,
                    status="failed",
                    created=True,
                    reason_codes=[exc.reason_code],
                    message=str(exc),
                    pods=last_pods,
                )

            last_pods = [_pod_observation(pod) for pod in pods]
            deployment_failure = _deployment_failure(deployment)
            pod_failure = next(
                (pod for pod in last_pods if pod.reason_code is not None),
                None,
            )
            if deployment_failure is not None:
                code, message = deployment_failure
                return self._result(
                    request,
                    placement,
                    operation_id,
                    status="failed",
                    created=True,
                    reason_codes=[code],
                    message=message,
                    pods=last_pods,
                )
            if pod_failure is not None:
                return self._result(
                    request,
                    placement,
                    operation_id,
                    status="failed",
                    created=True,
                    reason_codes=[pod_failure.reason_code or "pod_failed"],
                    message=pod_failure.message or pod_failure.reason or "Pod failed.",
                    pods=last_pods,
                )
            if _deployment_ready(deployment) and any(pod.ready for pod in last_pods):
                return self._result(
                    request,
                    placement,
                    operation_id,
                    status="ready",
                    created=True,
                    reason_codes=["deployment_created", "pod_ready"],
                    message="Deployment was created and at least one Pod is Ready.",
                    pods=last_pods,
                    pod_ready=True,
                )
            if time.monotonic() >= deadline:
                return self._result(
                    request,
                    placement,
                    operation_id,
                    status="failed",
                    created=True,
                    reason_codes=["pod_ready_timeout"],
                    message="Deployment was created but no Pod became Ready before timeout.",
                    pods=last_pods,
                )
            await asyncio.sleep(self.settings.deployment_poll_interval_seconds)

    def _result(
        self,
        request: DeploymentCreateRequest,
        placement: PlacementSelectionResult,
        operation_id: str,
        *,
        status: str,
        created: bool,
        reason_codes: list[str],
        message: str,
        pods: list[DeploymentPodObservation] | None = None,
        pod_ready: bool = False,
    ) -> DeploymentCreateResult:
        return DeploymentCreateResult(
            operation_id=operation_id,
            namespace=self.settings.deployment_target_namespace,
            deployment_name=request.deployment_name,
            image=request.image,
            status=status,
            created=created,
            selected_node=placement.selected_node,
            pod_ready=pod_ready,
            reason_codes=_unique(reason_codes),
            message=message[:500],
            placement=placement,
            pods=pods or [],
            observed_at=datetime.now(timezone.utc),
        )


def build_deployment_manifest(
    namespace: str,
    request: DeploymentCreateRequest,
    placement: PlacementSelectionResult,
    operation_id: str,
    ready_timeout_seconds: float,
) -> dict[str, Any]:
    assert placement.selected_node is not None
    assert placement.requirements is not None
    requirements = placement.requirements
    labels = {
        "app.kubernetes.io/name": request.deployment_name,
        "app.kubernetes.io/managed-by": "state-aggregator",
        "edge-ai.io/deployment": request.deployment_name,
    }
    resource_requests = {
        "cpu": _quantity(requirements.cpu_cores),
        "memory": str(requirements.memory_bytes),
        **{
            name: _quantity(amount)
            for name, amount in requirements.accelerator_units.items()
        },
    }
    container: dict[str, Any] = {
        "name": request.deployment_name,
        "image": request.image,
        "imagePullPolicy": "IfNotPresent",
        "resources": {
            "requests": resource_requests,
            "limits": {
                name: _quantity(amount)
                for name, amount in requirements.accelerator_units.items()
            },
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    if request.container_port is not None:
        container["ports"] = [
            {
                "name": "http",
                "containerPort": request.container_port,
                "protocol": "TCP",
            }
        ]
    if request.readiness_path is not None and request.container_port is not None:
        container["readinessProbe"] = {
            "httpGet": {
                "path": request.readiness_path,
                "port": request.container_port,
            },
            "periodSeconds": 2,
            "failureThreshold": max(3, math.ceil(ready_timeout_seconds / 2)),
        }
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": request.deployment_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {
                "edge-ai.io/operation-id": operation_id,
                "edge-ai.io/service-profile": (
                    f"{request.placement.namespace}/{request.placement.service}"
                ),
                "edge-ai.io/selected-score": str(placement.selected_score or 0),
            },
        },
        "spec": {
            "replicas": 1,
            "revisionHistoryLimit": 1,
            "progressDeadlineSeconds": max(60, math.ceil(ready_timeout_seconds)),
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"edge-ai.io/deployment": request.deployment_name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "nodeSelector": {
                        "kubernetes.io/hostname": placement.selected_node,
                    },
                    "affinity": {
                        "nodeAffinity": {
                            "requiredDuringSchedulingIgnoredDuringExecution": {
                                "nodeSelectorTerms": [
                                    {
                                        "matchExpressions": [
                                            {
                                                "key": "kubernetes.io/hostname",
                                                "operator": "In",
                                                "values": [placement.selected_node],
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                    "terminationGracePeriodSeconds": 15,
                    "containers": [container],
                },
            },
        },
    }


def _deployment_ready(deployment: Any) -> bool:
    status = getattr(deployment, "status", None)
    return bool(
        (getattr(status, "ready_replicas", None) or 0) >= 1
        and (getattr(status, "available_replicas", None) or 0) >= 1
    )


def _deployment_failure(deployment: Any) -> tuple[str, str] | None:
    status = getattr(deployment, "status", None)
    for condition in getattr(status, "conditions", None) or []:
        if (
            getattr(condition, "type", None) == "Progressing"
            and getattr(condition, "status", None) == "False"
            and getattr(condition, "reason", None) == "ProgressDeadlineExceeded"
        ):
            return (
                "deployment_progress_deadline_exceeded",
                (getattr(condition, "message", None) or "Deployment progress deadline exceeded.")[:500],
            )
    return None


def _pod_observation(pod: Any) -> DeploymentPodObservation:
    metadata = getattr(pod, "metadata", None)
    spec = getattr(pod, "spec", None)
    status = getattr(pod, "status", None)
    ready = any(
        getattr(condition, "type", None) == "Ready"
        and getattr(condition, "status", None) == "True"
        for condition in getattr(status, "conditions", None) or []
    )
    reason_code, reason, message = _pod_failure(status)
    return DeploymentPodObservation(
        name=getattr(metadata, "name", None) or "unknown",
        phase=getattr(status, "phase", None),
        node=getattr(spec, "node_name", None),
        ready=ready,
        reason_code=reason_code,
        reason=reason,
        message=message,
    )


def _pod_failure(status: Any) -> tuple[str | None, str | None, str | None]:
    for condition in getattr(status, "conditions", None) or []:
        if (
            getattr(condition, "type", None) == "PodScheduled"
            and getattr(condition, "status", None) == "False"
            and getattr(condition, "reason", None) == "Unschedulable"
        ):
            return (
                "pod_unschedulable",
                "Unschedulable",
                _text(getattr(condition, "message", None)),
            )
    for container_status in getattr(status, "container_statuses", None) or []:
        state = getattr(container_status, "state", None)
        waiting = getattr(state, "waiting", None)
        if waiting is not None:
            reason = getattr(waiting, "reason", None)
            if reason in {"ErrImagePull", "ImagePullBackOff", "InvalidImageName"}:
                return "image_pull_failed", reason, _text(getattr(waiting, "message", None))
            if reason in {
                "CrashLoopBackOff",
                "CreateContainerError",
                "RunContainerError",
                "CreateContainerConfigError",
            }:
                return "container_start_failed", reason, _text(getattr(waiting, "message", None))
        terminated = getattr(state, "terminated", None)
        if terminated is not None and (getattr(terminated, "exit_code", None) or 0) != 0:
            return (
                "container_terminated",
                getattr(terminated, "reason", None),
                _text(getattr(terminated, "message", None)),
            )
    if getattr(status, "phase", None) == "Failed":
        return (
            "pod_failed",
            getattr(status, "reason", None),
            _text(getattr(status, "message", None)),
        )
    return None, None, None


def _quantity(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _text(value: Any) -> str | None:
    return str(value)[:500] if value not in (None, "") else None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
