from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import RuntimeTemplate
from .renderer import render_runtime_workload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeReconciler:
    def __init__(
        self,
        kube: Any,
        edgex_probe: Any,
        *,
        namespace: str,
    ) -> None:
        if namespace != "edgex-edge":
            raise ValueError("runtime reconciliation is limited to edgex-edge")
        self.kube = kube
        self.edgex_probe = edgex_probe
        self.namespace = namespace

    def reconcile(
        self,
        runtime: dict[str, Any],
        template: RuntimeTemplate,
    ) -> dict[str, Any]:
        metadata = runtime.get("metadata") or {}
        spec = runtime.get("spec") or {}
        name = str(metadata.get("name") or "")
        generation = int(metadata.get("generation") or 1)
        consumers = int((runtime.get("status") or {}).get("consumers") or 0)
        try:
            if spec.get("desiredState") == "Retired":
                status = self._retire(
                    runtime,
                    consumers=consumers,
                    generation=generation,
                )
            else:
                status = self._ensure_running(
                    runtime,
                    template,
                    consumers=consumers,
                    generation=generation,
                )
        except Exception as exc:
            status = self._status(
                phase="FAILED",
                generation=generation,
                consumers=consumers,
                service_observed=False,
                error_code="reconcile_failed",
                error_message=f"{exc.__class__.__name__}: {exc}",
                name=name,
            )
        current_status = runtime.get("status") or {}
        if (
            current_status.get("phase") == status.get("phase")
            and current_status.get("lastTransitionTime")
        ):
            status["lastTransitionTime"] = current_status[
                "lastTransitionTime"
            ]
        if current_status != status:
            self.kube.patch_runtime_status(self.namespace, name, status)
        return status

    def _ensure_running(
        self,
        runtime: dict[str, Any],
        template: RuntimeTemplate,
        *,
        consumers: int,
        generation: int,
    ) -> dict[str, Any]:
        name = runtime["metadata"]["name"]
        resources = render_runtime_workload(
            runtime,
            template,
            namespace=self.namespace,
        )
        for resource in resources:
            self.kube.apply_resource(resource)
        ready = self.kube.is_deployment_ready(self.namespace, name)
        if not ready:
            phase = (
                "RESTARTING"
                if str((runtime.get("spec") or {}).get("restartNonce") or "")
                else "DEPLOYING"
            )
            return self._status(
                phase=phase,
                generation=generation,
                consumers=consumers,
                service_observed=False,
                name=name,
            )
        service_name = str((runtime["spec"].get("edgeX") or {})["serviceName"])
        service_observed = bool(self.edgex_probe.service_ready(service_name))
        return self._status(
            phase="SERVICE_READY" if service_observed else "WORKLOAD_READY",
            generation=generation,
            consumers=consumers,
            service_observed=service_observed,
            name=name,
        )

    def _retire(
        self,
        runtime: dict[str, Any],
        *,
        consumers: int,
        generation: int,
    ) -> dict[str, Any]:
        name = str(runtime["metadata"]["name"])
        uid = str(runtime["metadata"]["uid"])
        service_name = str(
            ((runtime.get("spec") or {}).get("edgeX") or {}).get(
                "serviceName"
            )
            or ""
        )
        consumers = max(
            consumers,
            self.edgex_probe.consumer_count(service_name),
        )
        if consumers:
            return self._status(
                phase="FAILED",
                generation=generation,
                consumers=consumers,
                service_observed=False,
                error_code="runtime_has_consumers",
                error_message="EdgeX Device consumers must be zero before retirement",
                name=name,
            )
        for kind in ("Deployment", "Service", "ConfigMap", "NetworkPolicy"):
            self.kube.delete_owned_resource(
                namespace=self.namespace,
                kind=kind,
                name=name,
                owner_uid=uid,
            )
        return self._status(
            phase="RETIRED",
            generation=generation,
            consumers=0,
            service_observed=False,
            name=name,
        )

    @staticmethod
    def _status(
        *,
        phase: str,
        generation: int,
        consumers: int,
        service_observed: bool,
        name: str,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any]:
        ready = phase == "SERVICE_READY"
        status: dict[str, Any] = {
            "phase": phase,
            "observedGeneration": generation,
            "managementMode": "controller",
            "workloadRef": {"kind": "Deployment", "name": name},
            "serviceRef": {"name": name},
            "edgeXServiceObserved": service_observed,
            "consumers": consumers,
            "conditions": [
                {
                    "type": "Ready",
                    "status": "True" if ready else "False",
                    "reason": phase,
                }
            ],
            "lastTransitionTime": _now(),
            "lastError": {
                "code": error_code,
                "message": error_message,
            },
        }
        return status
