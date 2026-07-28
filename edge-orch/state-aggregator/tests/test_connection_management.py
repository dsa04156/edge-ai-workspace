import asyncio
from datetime import datetime, timezone

import pytest

from app.adapter_runtime_models import (
    RuntimeActionRequest,
    RuntimeObservation,
    RuntimePlan,
)
from app.connection_management import (
    ConnectionIdempotencyConflict,
    ConnectionManagementService,
    ConnectionValidationError,
)
from app.connection_management_models import ConnectionOnboardingRequest
from app.device_management import ManagementApplyError
from app.device_management_models import (
    ManagementOperation,
    ValidationResult,
)


def request_payload():
    return ConnectionOnboardingRequest.model_validate(
        {
            "adapterId": "serial-jetson",
            "runtime": {
                "mode": "auto",
                "targetNode": "etri-dev0001-jetorn",
                "hardwareBindingId": "jetson-arduino-serial-001",
            },
            "device": {
                "name": "virtual-temperature-002",
                "description": "dashboard connection",
                "protocolProperties": {
                    "Port": "/dev/arduino-001",
                    "BaudRate": 115200,
                    "DeviceID": "arduino-001",
                    "Parser": "arduino-multisensor-v1",
                    "ResourceName": "temperature_raw",
                },
            },
            "profile": {
                "mode": "existing",
                "name": "etri-arduino-temperature",
            },
        }
    )


def runtime_plan(action="REUSE"):
    return RuntimePlan(
        action=action,
        allowed=True,
        adapter_id="serial-jetson",
        template_id="serial-device-service-v1",
        runtime_name=(
            "device-serial-jetson"
            if action == "REUSE"
            else "adapter-serial-02"
        ),
        service_name=(
            "device-serial-jetson"
            if action == "REUSE"
            else "adapter-serial-02"
        ),
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-arduino-serial-001",
        management_mode="external" if action == "REUSE" else "controller",
        verification_state="hardware-verified",
        plan_hash="a" * 64,
    )


def runtime_observation(*, phase, managed=True):
    name = "adapter-serial-02" if managed else "device-serial-jetson"
    return RuntimeObservation(
        runtime_name=name,
        adapter_id="serial-jetson",
        template_id="serial-device-service-v1",
        service_name=name,
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-arduino-serial-001",
        management_mode="controller" if managed else "external",
        management_owner="controller" if managed else "argocd",
        verification_state="hardware-verified",
        phase=phase,
        consumers=0,
        mutable=managed,
        edge_x_service_observed=phase == "SERVICE_READY",
    )


def device_operation(status="verified", request_id="outer-request"):
    now = datetime.now(timezone.utc)
    return ManagementOperation(
        request_id=request_id,
        payload_hash="outer-payload",
        action="create",
        device_name="virtual-temperature-002",
        profile_name="etri-arduino-temperature",
        status=status,
        metadata_applied=status != "failed",
        first_event_verified=status == "verified",
        actor="dashboard-admin",
        started_at=now,
        updated_at=now,
    )


class FakeRuntimeService:
    def __init__(self, *, action="REUSE", apply_phase="SERVICE_READY"):
        self.action = action
        self.apply_phase = apply_phase
        self.current_phase = apply_phase
        self.calls = []

    async def plan_runtime(self, request):
        self.calls.append(("plan", request.mode))
        return runtime_plan(self.action)

    async def apply_runtime(self, name, request):
        self.calls.append(("apply", name, request.request_ref.request_id))
        return runtime_observation(phase=self.apply_phase)

    async def list_runtimes(self):
        self.calls.append(("list",))
        return [runtime_observation(phase=self.current_phase)]

    async def retire_runtime(self, name, request):
        self.calls.append(("retire", name, request.request_id))
        return runtime_observation(phase="RETIRED")


class FakeDeviceManagement:
    def __init__(self, *, status="verified", create_error=None):
        self.status = status
        self.create_error = create_error
        self.calls = []
        self.operations = {}

    async def validate(
        self,
        request,
        *,
        actor,
        service_name_override=None,
        node_name_override=None,
        allow_unregistered_service=False,
    ):
        self.calls.append(
            (
                "validate",
                service_name_override,
                node_name_override,
                allow_unregistered_service,
            )
        )
        return ValidationResult(
            valid=True,
            plan={"mutations": ["create_device"]},
        )

    async def create_device(
        self,
        request,
        *,
        idempotency_key,
        actor,
        service_name_override=None,
        node_name_override=None,
        request_id_override=None,
        payload_hash_override=None,
    ):
        self.calls.append(
            (
                "create",
                service_name_override,
                node_name_override,
                request_id_override,
            )
        )
        if self.create_error:
            raise self.create_error
        operation = device_operation(self.status, request_id_override)
        operation.payload_hash = payload_hash_override
        self.operations[operation.request_id] = operation
        return operation

    async def get_operation(self, request_id):
        self.calls.append(("get", request_id))
        return self.operations[request_id]


def service(runtime, device):
    return ConnectionManagementService(
        runtime,
        device,
        hmac_key="connection-hmac",
        operation_limit=32,
    )


def test_validation_combines_runtime_and_edgex_plan_without_mutation():
    runtime = FakeRuntimeService(action="REUSE")
    device = FakeDeviceManagement()

    result = asyncio.run(
        service(runtime, device).validate(request_payload(), actor="viewer")
    )

    assert result.valid is True
    assert result.runtime_plan.action == "REUSE"
    assert result.edge_x_plan["mutations"] == ["create_device"]
    assert not any(call[0] in {"apply", "create"} for call in runtime.calls + device.calls)


def test_reuse_connection_applies_metadata_and_first_event_in_one_operation():
    runtime = FakeRuntimeService(action="REUSE")
    device = FakeDeviceManagement(status="verified")
    manager = service(runtime, device)

    operation = asyncio.run(
        manager.create_connection(
            request_payload(),
            idempotency_key="connection-01",
            actor="dashboard-admin",
        )
    )

    assert operation.status == "ACTIVE"
    assert operation.runtime_action == "REUSE"
    assert operation.metadata_applied is True
    assert operation.first_event_verified is True
    assert not any(call[0] == "apply" for call in runtime.calls)
    assert device.calls[-1][0] == "create"
    assert device.calls[-1][1] == "device-serial-jetson"
    assert device.calls[-1][2] == "etri-dev0001-jetorn"


def test_connection_idempotency_replays_same_payload_and_rejects_different():
    manager = service(
        FakeRuntimeService(action="REUSE"),
        FakeDeviceManagement(status="waiting_for_event"),
    )
    first = asyncio.run(
        manager.create_connection(
            request_payload(),
            idempotency_key="connection-01",
            actor="dashboard-admin",
        )
    )
    replay = asyncio.run(
        manager.create_connection(
            request_payload(),
            idempotency_key="connection-01",
            actor="dashboard-admin",
        )
    )
    changed = request_payload().model_copy(deep=True)
    changed.device.description = "different payload"

    assert replay.request_id == first.request_id
    with pytest.raises(ConnectionIdempotencyConflict):
        asyncio.run(
            manager.create_connection(
                changed,
                idempotency_key="connection-01",
                actor="dashboard-admin",
            )
        )


def test_deploy_waits_for_service_ready_then_advances_on_poll():
    runtime = FakeRuntimeService(action="DEPLOY", apply_phase="DEPLOYING")
    device = FakeDeviceManagement(status="waiting_for_event")
    manager = service(runtime, device)

    created = asyncio.run(
        manager.create_connection(
            request_payload(),
            idempotency_key="connection-02",
            actor="dashboard-admin",
        )
    )

    assert created.status == "RUNTIME_REQUESTED"
    assert not any(call[0] == "create" for call in device.calls)

    runtime.current_phase = "SERVICE_READY"
    advanced = asyncio.run(manager.get_operation(created.request_id))

    assert advanced.status == "WAITING_EVENT"
    assert any(call[0] == "create" for call in device.calls)


def test_created_runtime_is_compensated_when_metadata_apply_fails():
    now = datetime.now(timezone.utc)
    failed_operation = ManagementOperation(
        request_id="failed",
        payload_hash="failed",
        action="create",
        device_name="virtual-temperature-002",
        profile_name="etri-arduino-temperature",
        status="failed",
        actor="dashboard-admin",
        started_at=now,
        updated_at=now,
        error="metadata unavailable",
    )
    runtime = FakeRuntimeService(action="DEPLOY", apply_phase="SERVICE_READY")
    device = FakeDeviceManagement(
        create_error=ManagementApplyError(
            failed_operation,
            RuntimeError("metadata unavailable"),
        )
    )
    manager = service(runtime, device)

    operation = asyncio.run(
        manager.create_connection(
            request_payload(),
            idempotency_key="connection-03",
            actor="dashboard-admin",
        )
    )

    assert operation.status == "COMPENSATED"
    assert operation.compensation_status == "runtime_retired"
    assert any(call[0] == "retire" for call in runtime.calls)
