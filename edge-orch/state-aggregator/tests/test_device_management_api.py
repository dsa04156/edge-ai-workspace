from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.device_management import (
    IdempotencyConflict,
    ManagementApplyError,
    ManagementValidationError,
    OperationNotFound,
)
from app.device_management_api import create_device_management_router
from app.device_management_models import (
    AdapterStatusView,
    ManagementOperation,
    ValidationIssue,
    ValidationResult,
)


def request_payload():
    return {
        "adapterId": "serial-jetson",
        "device": {
            "name": "virtual-temperature-002",
            "description": "managed source",
            "protocolProperties": {
                "Port": "/dev/arduino-001",
                "BaudRate": 115200,
                "DeviceID": "arduino-002",
                "ResourceName": "temperature_raw",
            },
        },
        "profile": {"mode": "existing", "name": "etri-arduino-temperature"},
    }


def operation(status="waiting_for_event"):
    now = datetime.now(timezone.utc)
    return ManagementOperation(
        request_id="request-01",
        payload_hash="a" * 64,
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


class RecordingService:
    def __init__(self):
        self.calls = []
        self.create_error = None
        self.patch_error = None
        self.operation_error = None

    async def list_adapters(self):
        self.calls.append(("list_adapters",))
        return [
            AdapterStatusView(
                adapter_id="serial-jetson",
                display_name="Jetson Arduino Serial",
                service_name="device-serial-jetson",
                protocol_name="serial",
                node_name="etri-dev0001-jetorn",
                status="installed",
            )
        ]

    async def validate(self, request, *, actor):
        self.calls.append(("validate", request.device.name, actor))
        return ValidationResult(
            valid=True,
            plan={"mutations": ["create_device"]},
        )

    async def create_device(self, request, *, idempotency_key, actor):
        self.calls.append(("create", request.device.name, idempotency_key, actor))
        if self.create_error:
            raise self.create_error
        return operation()

    async def patch_device(self, name, patch, *, idempotency_key, actor):
        self.calls.append(("patch", name, patch.description, idempotency_key, actor))
        if self.patch_error:
            raise self.patch_error
        result = operation("verified")
        result.action = "patch"
        return result

    async def get_operation(self, request_id):
        self.calls.append(("get_operation", request_id))
        if self.operation_error:
            raise self.operation_error
        result = operation("verified")
        result.request_id = request_id
        return result


def settings(*, enabled=False, token=None, hmac_key=None):
    return Settings(
        device_management_enabled=enabled,
        device_management_admin_token=token,
        device_management_hmac_key=hmac_key,
    )


def client_for(service, *, enabled=False, token=None, hmac_key=None):
    app = FastAPI()
    app.include_router(
        create_device_management_router(
            settings(enabled=enabled, token=token, hmac_key=hmac_key), service
        )
    )
    return TestClient(app)


def admin_headers(**extra):
    return {
        "Authorization": "Bearer admin-token",
        "Idempotency-Key": "request-key",
        **extra,
    }


def test_read_only_catalog_and_validation_work_while_mutation_is_disabled():
    service = RecordingService()
    with client_for(service) as client:
        adapters = client.get("/management/adapters")
        validation = client.post("/management/devices/validate", json=request_payload())

    assert adapters.status_code == 200
    assert adapters.json()[0]["adapterId"] == "serial-jetson"
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert ("validate", "virtual-temperature-002", "viewer") in service.calls


def test_mutation_is_hidden_when_feature_flag_is_disabled():
    service = RecordingService()
    with client_for(service) as client:
        response = client.post(
            "/management/devices", json=request_payload(), headers=admin_headers()
        )

    assert response.status_code == 404
    assert not any(call[0] == "create" for call in service.calls)


def test_enabled_router_fails_fast_without_both_secrets():
    service = RecordingService()

    with pytest.raises(ValueError, match="admin token"):
        client_for(service, enabled=True, hmac_key="hmac")
    with pytest.raises(ValueError, match="HMAC"):
        client_for(service, enabled=True, token="admin-token")


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Idempotency-Key": "request-key"}, 401),
        (
            {
                "Authorization": "Bearer wrong-token",
                "Idempotency-Key": "request-key",
            },
            401,
        ),
        ({"Authorization": "Bearer admin-token"}, 400),
        (
            {
                "Authorization": "Basic admin-token",
                "Idempotency-Key": "request-key",
            },
            401,
        ),
    ],
)
def test_create_requires_bearer_admin_and_idempotency_key(headers, status):
    service = RecordingService()
    with client_for(
        service, enabled=True, token="admin-token", hmac_key="hmac"
    ) as client:
        response = client.post(
            "/management/devices", json=request_payload(), headers=headers
        )

    assert response.status_code == status
    assert not any(call[0] == "create" for call in service.calls)


def test_admin_create_returns_operation_without_internal_payload_hash():
    service = RecordingService()
    with client_for(
        service, enabled=True, token="admin-token", hmac_key="hmac"
    ) as client:
        response = client.post(
            "/management/devices", json=request_payload(), headers=admin_headers()
        )

    assert response.status_code == 201
    assert response.json()["requestId"] == "request-01"
    assert response.json()["status"] == "waiting_for_event"
    assert "payloadHash" not in response.json()
    assert service.calls[-1] == (
        "create",
        "virtual-temperature-002",
        "request-key",
        "dashboard-admin",
    )


def test_domain_validation_and_idempotency_conflict_are_mapped():
    invalid = ValidationResult(
        valid=False,
        issues=[ValidationIssue(code="device_exists", message="duplicate")],
    )
    cases = [
        (ManagementValidationError(invalid), 422),
        (IdempotencyConflict("different payload"), 409),
    ]
    for error, expected in cases:
        service = RecordingService()
        service.create_error = error
        with client_for(
            service, enabled=True, token="admin-token", hmac_key="hmac"
        ) as client:
            response = client.post(
                "/management/devices", json=request_payload(), headers=admin_headers()
            )
        assert response.status_code == expected


def test_apply_failure_returns_gateway_error_with_safe_operation_identity():
    service = RecordingService()
    service.create_error = ManagementApplyError(
        operation("failed"), RuntimeError("metadata unavailable")
    )
    with client_for(
        service, enabled=True, token="admin-token", hmac_key="hmac"
    ) as client:
        response = client.post(
            "/management/devices", json=request_payload(), headers=admin_headers()
        )

    assert response.status_code == 502
    assert response.json()["detail"]["requestId"] == "request-01"
    assert response.json()["detail"]["status"] == "failed"
    assert "payloadHash" not in response.text


def test_patch_uses_path_identity_and_allowlisted_body():
    service = RecordingService()
    with client_for(
        service, enabled=True, token="admin-token", hmac_key="hmac"
    ) as client:
        response = client.patch(
            "/management/devices/device-01",
            json={"description": "updated"},
            headers=admin_headers(),
        )

    assert response.status_code == 200
    assert response.json()["action"] == "patch"
    assert service.calls[-1] == (
        "patch",
        "device-01",
        "updated",
        "request-key",
        "dashboard-admin",
    )


def test_operation_poll_and_unknown_operation_mapping():
    service = RecordingService()
    with client_for(service) as client:
        found = client.get("/management/operations/request-77")
        service.operation_error = OperationNotFound("missing")
        missing = client.get("/management/operations/missing")

    assert found.status_code == 200
    assert found.json()["requestId"] == "request-77"
    assert missing.status_code == 404


def test_delete_route_does_not_exist():
    with client_for(RecordingService()) as client:
        response = client.delete("/management/devices/device-01")

    assert response.status_code in {404, 405}


def test_repository_app_registers_default_disabled_mutation_route():
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/management/devices", json=request_payload(), headers=admin_headers()
        )

    assert response.status_code == 404
