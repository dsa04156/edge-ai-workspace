from __future__ import annotations

from typing import Any

from .adapter_runtime_models import (
    RuntimeActionRequest,
    RuntimeCreateRequest,
    RuntimeObservation,
    RuntimePlan,
    RuntimePlanRequest,
)


class AdapterRuntimeServiceError(RuntimeError):
    pass


class RuntimeNotFoundError(AdapterRuntimeServiceError):
    pass


class ExternalRuntimeMutationError(AdapterRuntimeServiceError):
    pass


class AdapterRuntimeManagementService:
    def __init__(self, controller: Any, metadata: Any) -> None:
        self.controller = controller
        self.metadata = metadata

    async def list_runtimes(self) -> list[RuntimeObservation]:
        controller_runtimes = await self.controller.list_runtimes()
        services = {
            str(item.get("name") or ""): item
            for item in await self.metadata.list_device_services()
        }
        consumers: dict[str, int] = {}
        for device in await self.metadata.list_devices():
            service_name = str(device.get("serviceName") or "")
            if service_name:
                consumers[service_name] = consumers.get(service_name, 0) + 1
        result: list[RuntimeObservation] = []
        for runtime in controller_runtimes:
            service = services.get(runtime.service_name)
            service_observed = (
                service is not None
                and service.get("adminState") == "UNLOCKED"
            )
            phase = runtime.phase
            if phase == "SERVICE_READY" and not service_observed:
                phase = "WORKLOAD_READY"
            result.append(
                runtime.model_copy(
                    update={
                        "consumers": consumers.get(runtime.service_name, 0),
                        "edge_x_service_observed": service_observed,
                        "phase": phase,
                    }
                )
            )
        return result

    async def plan_runtime(self, request: RuntimePlanRequest) -> RuntimePlan:
        return await self.controller.plan_runtime(request)

    async def apply_runtime(
        self,
        name: str,
        request: RuntimeCreateRequest,
    ) -> RuntimeObservation:
        return await self.controller.apply_runtime(name, request)

    async def restart_runtime(
        self,
        name: str,
        request: RuntimeActionRequest,
    ) -> RuntimeObservation:
        await self._require_mutable_runtime(name)
        return await self.controller.restart_runtime(name, request)

    async def retire_runtime(
        self,
        name: str,
        request: RuntimeActionRequest,
    ) -> RuntimeObservation:
        await self._require_mutable_runtime(name)
        return await self.controller.retire_runtime(name, request)

    async def _require_mutable_runtime(
        self,
        name: str,
    ) -> RuntimeObservation:
        runtime = next(
            (
                item
                for item in await self.list_runtimes()
                if item.runtime_name == name
            ),
            None,
        )
        if runtime is None:
            raise RuntimeNotFoundError(f"runtime {name!r} was not found")
        if runtime.management_mode != "controller" or not runtime.mutable:
            raise ExternalRuntimeMutationError(
                "external or retired runtime is read-only"
            )
        return runtime
