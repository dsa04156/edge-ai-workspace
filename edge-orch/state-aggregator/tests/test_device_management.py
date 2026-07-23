import asyncio
import copy
import json
import logging
from functools import wraps
from pathlib import Path

import pytest

from app.adapter_catalog import AdapterCatalog
from app.device_management import (
    DEVICE_PAYLOAD_HASH_TAG,
    DEVICE_REQUEST_ID_TAG,
    DeviceManagementService,
    IdempotencyConflict,
    ManagementApplyError,
    ManagementValidationError,
    OperationNotFound,
)
from app.device_management_edgex import EdgeXManagementBackendError
from app.device_management_models import (
    DeviceOnboardingRequest,
    DevicePatchRequest,
)


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "config" / "adapter_catalog.json"
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def serial_protocol(device_id="arduino-002", resource_name="temperature_raw"):
    return {
        "Port": "/dev/arduino-001",
        "BaudRate": 115200,
        "DeviceID": device_id,
        "ResourceName": resource_name,
    }


def onboarding_request(
    *,
    device_name="virtual-temperature-002",
    device_id="arduino-002",
    profile_mode="existing",
    profile_name="etri-arduino-temperature",
):
    profile = {"mode": profile_mode, "name": profile_name}
    if profile_mode == "create":
        profile.update(
            {
                "description": "Read-only managed temperature",
                "manufacturer": "Arduino",
                "model": "Uno virtual temperature source",
                "labels": ["arduino", "serial", "virtual-device"],
            }
        )
    return DeviceOnboardingRequest.model_validate(
        {
            "adapterId": "serial-jetson",
            "device": {
                "name": device_name,
                "description": "managed temperature source",
                "labels": ["arduino", "serial"],
                "tags": {"physicalDeviceId": device_id, "line": "A"},
                "protocolProperties": serial_protocol(device_id),
                "adminState": "UNLOCKED",
            },
            "profile": profile,
        }
    )


def temperature_profile(name="etri-arduino-temperature"):
    return {
        "apiVersion": "v2",
        "name": name,
        "description": "Read-only temperature",
        "manufacturer": "Arduino",
        "model": "Uno virtual temperature source",
        "labels": ["arduino", "serial"],
        "deviceResources": [
            {
                "name": "temperature_raw",
                "description": "Raw temperature sensor value",
                "isHidden": False,
                "properties": {"valueType": "Int32", "readWrite": "R", "units": "raw"},
            }
        ],
        "deviceCommands": [
            {
                "name": "temperature",
                "readWrite": "R",
                "isHidden": False,
                "resourceOperations": [{"deviceResource": "temperature_raw"}],
            }
        ],
    }


class FakeMetadata:
    def __init__(self):
        self.services = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "device-serial-jetson",
                "description": "Jetson serial adapter",
                "baseAddress": "http://device-serial-jetson.edgex-edge.svc.cluster.local:59910",
                "adminState": "UNLOCKED",
                "labels": ["serial"],
                "properties": {},
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "device-sensehat-raspi",
                "description": "Sense HAT adapter",
                "baseAddress": "http://device-sensehat-raspi.edgex-edge.svc.cluster.local:59911",
                "adminState": "UNLOCKED",
                "labels": ["i2c"],
                "properties": {},
            },
        ]
        self.profiles = {"etri-arduino-temperature": temperature_profile()}
        self.devices = {}
        self.calls = []
        self.fail_add_device = False
        self.corrupt_device_readback = False

    async def list_device_services(self):
        self.calls.append("list_services")
        return copy.deepcopy(self.services)

    async def list_devices(self):
        self.calls.append("list_devices")
        return copy.deepcopy(list(self.devices.values()))

    async def get_device(self, name):
        self.calls.append(f"get_device:{name}")
        value = copy.deepcopy(self.devices.get(name))
        if value is not None and self.corrupt_device_readback:
            value["serviceName"] = "wrong-service"
        return value

    async def get_profile(self, name):
        self.calls.append(f"get_profile:{name}")
        return copy.deepcopy(self.profiles.get(name))

    async def list_devices_by_profile(self, name):
        self.calls.append(f"list_by_profile:{name}")
        return [
            copy.deepcopy(device)
            for device in self.devices.values()
            if device.get("profileName") == name
        ]

    async def add_profile(self, profile):
        self.calls.append(f"add_profile:{profile['name']}")
        self.profiles[profile["name"]] = copy.deepcopy(profile)
        return "33333333-3333-3333-3333-333333333333"

    async def add_device(self, device):
        self.calls.append(f"add_device:{device['name']}")
        if self.fail_add_device:
            raise EdgeXManagementBackendError("device create failed")
        self.devices[device["name"]] = copy.deepcopy(device)
        return "44444444-4444-4444-4444-444444444444"

    async def patch_device(self, name, patch):
        self.calls.append(f"patch_device:{name}")
        self.devices[name].update(copy.deepcopy(patch))

    async def delete_profile(self, name):
        self.calls.append(f"delete_profile:{name}")
        self.profiles.pop(name, None)


class FakeEvents:
    def __init__(self):
        self.events = {}
        self.calls = []

    async def get_latest_event(self, device_name):
        self.calls.append(device_name)
        return copy.deepcopy(self.events.get(device_name, []))


@pytest.fixture
def catalog():
    return AdapterCatalog.load(CATALOG_PATH)


def service_for(catalog, metadata=None, events=None, *, limit=256):
    return DeviceManagementService(
        catalog,
        metadata or FakeMetadata(),
        events or FakeEvents(),
        hmac_key="management-hmac-key",
        operation_limit=limit,
    )


@async_test
async def test_adapter_runtime_status_comes_from_core_metadata(catalog):
    metadata = FakeMetadata()
    metadata.services[0]["adminState"] = "LOCKED"
    metadata.services = metadata.services[:1]

    adapters = await service_for(catalog, metadata).list_adapters()
    statuses = {item.adapter_id: item.status for item in adapters}

    assert statuses["serial-jetson"] == "unavailable"
    assert statuses["sensehat-raspi"] == "unavailable"
    assert statuses["modbus"] == "unsupported"


@async_test
async def test_validate_accepts_installed_service_and_matching_profile(catalog):
    result = await service_for(catalog).validate(onboarding_request(), actor="viewer")

    assert result.valid is True
    assert result.issues == []
    assert result.plan["device"]["serviceName"] == "device-serial-jetson"
    assert result.plan["device"]["profileName"] == "etri-arduino-temperature"
    assert result.plan["mutations"] == ["create_device"]


@async_test
async def test_validate_rejects_missing_service_duplicate_and_profile_mismatch(catalog):
    metadata = FakeMetadata()
    metadata.services = []
    metadata.devices["virtual-temperature-002"] = {"name": "virtual-temperature-002"}
    metadata.profiles["etri-arduino-temperature"]["deviceResources"][0]["properties"][
        "valueType"
    ] = "String"

    result = await service_for(catalog, metadata).validate(
        onboarding_request(), actor="viewer"
    )
    codes = {item.code for item in result.issues}

    assert result.valid is False
    assert {"adapter_unavailable", "device_exists", "profile_incompatible"} <= codes


@async_test
async def test_create_runs_profile_device_readback_saga_and_waits_for_event(catalog):
    metadata = FakeMetadata()
    events = FakeEvents()
    request = onboarding_request(
        profile_mode="create", profile_name="etri-managed-temperature"
    )

    operation = await service_for(catalog, metadata, events).create_device(
        request, idempotency_key="create-002", actor="dashboard-admin"
    )

    assert operation.status == "waiting_for_event"
    assert operation.metadata_applied is True
    assert operation.first_event_verified is False
    assert operation.created_profile is True
    device = metadata.devices["virtual-temperature-002"]
    assert device["serviceName"] == "device-serial-jetson"
    assert device["profileName"] == "etri-managed-temperature"
    assert device["protocols"] == {"serial": serial_protocol()}
    assert device["tags"]["nodeName"] == "etri-dev0001-jetorn"
    assert device["tags"][DEVICE_REQUEST_ID_TAG] == operation.request_id
    assert len(device["tags"][DEVICE_PAYLOAD_HASH_TAG]) == 64
    assert metadata.calls.index("add_profile:etri-managed-temperature") < metadata.calls.index(
        "add_device:virtual-temperature-002"
    )
    assert events.calls == ["virtual-temperature-002"]


@async_test
async def test_same_idempotency_request_reuses_result_and_changed_payload_conflicts(catalog):
    metadata = FakeMetadata()
    service = service_for(catalog, metadata)
    request = onboarding_request()

    first = await service.create_device(
        request, idempotency_key="retry-1", actor="dashboard-admin"
    )
    second = await service.create_device(
        request, idempotency_key="retry-1", actor="dashboard-admin"
    )

    assert second.request_id == first.request_id
    assert metadata.calls.count("add_device:virtual-temperature-002") == 1

    changed = onboarding_request(device_id="arduino-003")
    with pytest.raises(IdempotencyConflict):
        await service.create_device(
            changed, idempotency_key="retry-1", actor="dashboard-admin"
        )


@async_test
async def test_device_failure_compensates_only_profile_created_by_operation(catalog):
    metadata = FakeMetadata()
    metadata.fail_add_device = True
    request = onboarding_request(
        profile_mode="create", profile_name="etri-managed-temperature"
    )

    with pytest.raises(ManagementApplyError) as captured:
        await service_for(catalog, metadata).create_device(
            request, idempotency_key="fails", actor="dashboard-admin"
        )

    assert captured.value.operation.status == "failed"
    assert "etri-managed-temperature" not in metadata.profiles
    assert "delete_profile:etri-managed-temperature" in metadata.calls


@async_test
async def test_device_failure_never_deletes_existing_profile(catalog):
    metadata = FakeMetadata()
    metadata.fail_add_device = True

    with pytest.raises(ManagementApplyError):
        await service_for(catalog, metadata).create_device(
            onboarding_request(),
            idempotency_key="existing-profile-fails",
            actor="dashboard-admin",
        )

    assert "etri-arduino-temperature" in metadata.profiles
    assert "delete_profile:etri-arduino-temperature" not in metadata.calls


@async_test
async def test_operation_transitions_to_verified_when_first_event_arrives(catalog):
    events = FakeEvents()
    service = service_for(catalog, events=events)
    operation = await service.create_device(
        onboarding_request(), idempotency_key="event-later", actor="dashboard-admin"
    )
    events.events["virtual-temperature-002"] = [{"device_name": "virtual-temperature-002"}]

    refreshed = await service.get_operation(operation.request_id)

    assert refreshed.status == "verified"
    assert refreshed.first_event_verified is True


@async_test
async def test_operation_is_reconstructed_from_reserved_tags_after_restart(catalog):
    metadata = FakeMetadata()
    events = FakeEvents()
    first_service = service_for(catalog, metadata, events)
    created = await first_service.create_device(
        onboarding_request(), idempotency_key="restart-safe", actor="dashboard-admin"
    )
    events.events["virtual-temperature-002"] = [{"device_name": "virtual-temperature-002"}]

    restarted = service_for(catalog, metadata, events)
    recovered = await restarted.get_operation(created.request_id)

    assert recovered.request_id == created.request_id
    assert recovered.device_name == "virtual-temperature-002"
    assert recovered.status == "verified"


@async_test
async def test_unknown_operation_is_not_invented(catalog):
    with pytest.raises(OperationNotFound):
        await service_for(catalog).get_operation("missing-request")


@async_test
async def test_operation_memory_store_is_bounded(catalog):
    metadata = FakeMetadata()
    service = service_for(catalog, metadata, limit=1)
    await service.create_device(
        onboarding_request(), idempotency_key="one", actor="dashboard-admin"
    )
    await service.create_device(
        onboarding_request(device_name="virtual-temperature-003", device_id="arduino-003"),
        idempotency_key="two",
        actor="dashboard-admin",
    )

    assert len(service._operations) == 1


@async_test
async def test_patch_preserves_reserved_tags_and_changes_only_allowlist(catalog):
    metadata = FakeMetadata()
    service = service_for(catalog, metadata)
    created = await service.create_device(
        onboarding_request(), idempotency_key="create-before-patch", actor="dashboard-admin"
    )
    original_tags = copy.deepcopy(metadata.devices[created.device_name]["tags"])
    patch = DevicePatchRequest.model_validate(
        {
            "description": "updated description",
            "labels": ["line-b"],
            "tags": {"line": "B"},
            "protocolProperties": serial_protocol(device_id="arduino-003"),
            "adminState": "LOCKED",
        }
    )

    operation = await service.patch_device(
        created.device_name,
        patch,
        idempotency_key="patch-1",
        actor="dashboard-admin",
    )

    device = metadata.devices[created.device_name]
    assert operation.action == "patch"
    assert device["description"] == "updated description"
    assert device["labels"] == ["line-b"]
    assert device["adminState"] == "LOCKED"
    assert device["protocols"]["serial"]["DeviceID"] == "arduino-003"
    assert device["tags"][DEVICE_REQUEST_ID_TAG] == original_tags[DEVICE_REQUEST_ID_TAG]
    assert device["tags"][DEVICE_PAYLOAD_HASH_TAG] == original_tags[DEVICE_PAYLOAD_HASH_TAG]
    assert device["tags"]["line"] == "B"


@async_test
async def test_readback_mismatch_is_failed_not_success(catalog):
    metadata = FakeMetadata()
    metadata.corrupt_device_readback = True

    with pytest.raises(ManagementApplyError) as captured:
        await service_for(catalog, metadata).create_device(
            onboarding_request(), idempotency_key="bad-readback", actor="dashboard-admin"
        )

    assert captured.value.operation.status == "failed"
    assert "readback" in (captured.value.operation.error or "")


@async_test
async def test_apply_audit_is_structured_and_never_logs_raw_idempotency_key(
    catalog, caplog
):
    caplog.set_level(logging.INFO, logger="app.device_management.audit")

    await service_for(catalog).create_device(
        onboarding_request(),
        idempotency_key="raw-idempotency-secret",
        actor="dashboard-admin",
    )

    messages = [record.message for record in caplog.records]
    assert messages
    assert all("raw-idempotency-secret" not in message for message in messages)
    event = json.loads(messages[-1])
    assert event["actor"] == "dashboard-admin"
    assert event["action"] == "create"
    assert event["requestId"]
    assert event["idempotencyKeyHash"]
    assert event["status"] == "waiting_for_event"


@async_test
async def test_invalid_request_raises_validation_error_without_mutation(catalog):
    metadata = FakeMetadata()
    request = onboarding_request()
    request.device.protocol_properties["Port"] = "/dev/ttyUSB0"

    with pytest.raises(ManagementValidationError) as captured:
        await service_for(catalog, metadata).create_device(
            request, idempotency_key="invalid", actor="dashboard-admin"
        )

    assert captured.value.result.valid is False
    assert "constant_mismatch" in [item.code for item in captured.value.result.issues]
    assert not any(call.startswith("add_") for call in metadata.calls)
