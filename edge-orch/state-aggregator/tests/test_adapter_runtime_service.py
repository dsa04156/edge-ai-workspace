import asyncio

import pytest

from app.adapter_runtime_models import RuntimeObservation, RuntimePlan
from app.adapter_runtime_service import (
    AdapterRuntimeManagementService,
    ExternalRuntimeMutationError,
)


class FakeControllerClient:
    def __init__(self, runtimes):
        self.runtimes = runtimes
        self.calls = []

    async def list_runtimes(self):
        self.calls.append(("list",))
        return self.runtimes

    async def plan_runtime(self, request):
        self.calls.append(("plan", request.adapter_id))
        return RuntimePlan(
            action="REUSE",
            allowed=True,
            adapter_id=request.adapter_id,
            template_id="serial-device-service-v1",
            runtime_name="device-serial-jetson",
            service_name="device-serial-jetson",
            target_node=request.target_node,
            hardware_binding_id=request.hardware_binding_id,
            management_mode="external",
            verification_state="hardware-verified",
            plan_hash="a" * 64,
        )

    async def restart_runtime(self, name, request):
        self.calls.append(("restart", name))
        return self.runtimes[0]

    async def retire_runtime(self, name, request):
        self.calls.append(("retire", name))
        return self.runtimes[0]


class FakeMetadata:
    def __init__(self, *, service_present=True):
        self.service_present = service_present

    async def list_device_services(self):
        if not self.service_present:
            return []
        return [
            {
                "name": "device-serial-jetson",
                "adminState": "UNLOCKED",
            },
            {
                "name": "device-sensehat-raspi",
                "adminState": "UNLOCKED",
            },
        ]

    async def list_devices(self):
        return [
            {
                "name": f"virtual-serial-{index}",
                "serviceName": "device-serial-jetson",
            }
            for index in range(6)
        ] + [
            {
                "name": f"virtual-sensehat-{index}",
                "serviceName": "device-sensehat-raspi",
            }
            for index in range(6)
        ]


def runtime(
    *,
    name="device-serial-jetson",
    service_name="device-serial-jetson",
    management_mode="external",
    phase="SERVICE_READY",
):
    return RuntimeObservation(
        runtime_name=name,
        adapter_id="serial-jetson",
        template_id="serial-device-service-v1",
        service_name=service_name,
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-arduino-serial-001",
        management_mode=management_mode,
        management_owner="argocd" if management_mode == "external" else "controller",
        verification_state="hardware-verified",
        phase=phase,
        consumers=999,
        mutable=management_mode == "controller",
    )


def test_inventory_recomputes_consumers_from_edgex_authority():
    controller = FakeControllerClient([runtime()])
    service = AdapterRuntimeManagementService(
        controller,
        FakeMetadata(),
    )

    runtimes = asyncio.run(service.list_runtimes())

    assert runtimes[0].consumers == 6
    assert runtimes[0].edge_x_service_observed is True
    assert runtimes[0].phase == "SERVICE_READY"


def test_inventory_downgrades_ready_phase_when_edgex_service_is_missing():
    controller = FakeControllerClient([runtime()])
    service = AdapterRuntimeManagementService(
        controller,
        FakeMetadata(service_present=False),
    )

    runtimes = asyncio.run(service.list_runtimes())

    assert runtimes[0].consumers == 6
    assert runtimes[0].edge_x_service_observed is False
    assert runtimes[0].phase == "WORKLOAD_READY"


def test_external_runtime_restart_and_retire_are_blocked_before_controller_call():
    controller = FakeControllerClient([runtime()])
    service = AdapterRuntimeManagementService(controller, FakeMetadata())

    with pytest.raises(ExternalRuntimeMutationError):
        asyncio.run(service.restart_runtime("device-serial-jetson", object()))
    with pytest.raises(ExternalRuntimeMutationError):
        asyncio.run(service.retire_runtime("device-serial-jetson", object()))

    assert not any(call[0] in {"restart", "retire"} for call in controller.calls)


def test_controller_runtime_mutation_is_forwarded():
    managed = runtime(
        name="adapter-serial-02",
        service_name="adapter-serial-02",
        management_mode="controller",
    )
    controller = FakeControllerClient([managed])
    service = AdapterRuntimeManagementService(controller, FakeMetadata())

    restarted = asyncio.run(
        service.restart_runtime("adapter-serial-02", object())
    )

    assert restarted.runtime_name == "adapter-serial-02"
    assert controller.calls[-1] == ("restart", "adapter-serial-02")
