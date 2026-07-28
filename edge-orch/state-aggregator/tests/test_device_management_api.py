from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.adapter_runtime_models import RuntimeObservation, RuntimePlan
from app.adapter_runtime_service import ExternalRuntimeMutationError
from app.connection_management import (
    ConnectionIdempotencyConflict,
    ConnectionOperationNotFound,
    ConnectionValidationError,
)
from app.connection_management_models import (
    ConnectionOperation,
    ConnectionValidationResult,
)
from app.device_management import (
    IdempotencyConflict,
    ManagementApplyError,
    ManagementValidationError,
    OperationNotFound,
)
from app.device_management_api import create_device_management_router
from app.device_discovery_models import (
    CandidateView,
    DiscoveryInventory,
    DiscoveryNodeView,
)
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
                "DeviceID": "arduino-001",
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
        actor="dashboard-operator",
        started_at=now,
        updated_at=now,
    )


class RecordingService:
    def __init__(self):
        self.calls = []
        self.create_error = None
        self.patch_error = None
        self.delete_error = None
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

    async def delete_device(self, name, *, idempotency_key, actor):
        self.calls.append(("delete", name, idempotency_key, actor))
        if self.delete_error:
            raise self.delete_error
        result = operation("verified")
        result.action = "delete"
        result.device_name = name
        return result

    async def get_operation(self, request_id):
        self.calls.append(("get_operation", request_id))
        if self.operation_error:
            raise self.operation_error
        result = operation("verified")
        result.request_id = request_id
        return result


class RecordingRuntimeService:
    def __init__(self):
        self.calls = []
        self.error = None

    async def list_runtimes(self):
        self.calls.append(("list_runtimes",))
        if self.error:
            raise self.error
        return [
            RuntimeObservation(
                runtime_name="device-serial-jetson",
                adapter_id="serial-jetson",
                template_id="serial-device-service-v1",
                service_name="device-serial-jetson",
                target_node="etri-dev0001-jetorn",
                hardware_binding_id="jetson-arduino-serial-001",
                management_mode="external",
                management_owner="argocd",
                verification_state="hardware-verified",
                phase="SERVICE_READY",
                consumers=6,
                mutable=False,
                edge_x_service_observed=True,
            )
        ]

    async def plan_runtime(self, request):
        self.calls.append(("plan_runtime", request.adapter_id, request.mode))
        if self.error:
            raise self.error
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
            plan_hash="f" * 64,
        )

    async def restart_runtime(self, name, request):
        self.calls.append(("restart_runtime", name, request.request_id))
        if self.error:
            raise self.error
        result = (await self.list_runtimes())[0].model_copy(
            update={
                "runtime_name": name,
                "service_name": name,
                "management_mode": "controller",
                "management_owner": "controller",
                "mutable": True,
            }
        )
        return result

    async def retire_runtime(self, name, request):
        self.calls.append(("retire_runtime", name, request.request_id))
        if self.error:
            raise self.error
        result = (await self.list_runtimes())[0].model_copy(
            update={
                "runtime_name": name,
                "service_name": name,
                "management_mode": "controller",
                "management_owner": "controller",
                "phase": "RETIRED",
                "mutable": False,
            }
        )
        return result


class RecordingConnectionService:
    def __init__(self):
        self.calls = []
        self.error = None

    async def validate(self, request, *, actor):
        self.calls.append(("validate_connection", request.device.name, actor))
        if self.error:
            raise self.error
        return ConnectionValidationResult(
            valid=True,
            runtime_plan=RuntimePlan(
                action="REUSE",
                allowed=True,
                adapter_id=request.adapter_id,
                template_id="serial-device-service-v1",
                runtime_name="device-serial-jetson",
                service_name="device-serial-jetson",
                target_node=request.runtime.target_node,
                hardware_binding_id=request.runtime.hardware_binding_id,
                management_mode="external",
                verification_state="hardware-verified",
                plan_hash="f" * 64,
            ),
            edge_x_plan={"mutations": ["create_device"]},
        )

    async def create_connection(self, request, *, idempotency_key, actor):
        self.calls.append(
            (
                "create_connection",
                request.device.name,
                idempotency_key,
                actor,
            )
        )
        if self.error:
            raise self.error
        now = datetime.now(timezone.utc)
        return ConnectionOperation(
            request_id="connection-request",
            payload_hash="hidden",
            status="WAITING_EVENT",
            adapter_id=request.adapter_id,
            runtime_action="REUSE",
            runtime_name="device-serial-jetson",
            service_name="device-serial-jetson",
            device_name=request.device.name,
            profile_name=request.profile.name,
            metadata_applied=True,
            actor=actor,
            started_at=now,
            updated_at=now,
        )

    async def get_operation(self, request_id):
        self.calls.append(("get_connection", request_id))
        if self.error:
            raise self.error
        result = await self.create_connection(
            connection_request_model(),
            idempotency_key="recovered",
            actor="recovered",
        )
        result.request_id = request_id
        result.status = "ACTIVE"
        result.first_event_verified = True
        return result


class RecordingDiscoveryService:
    def __init__(self):
        self.calls = []

    @staticmethod
    def candidate(
        *,
        candidate_id="candidate-" + ("a" * 24),
        decision="pending",
        display_name="Arduino USB Serial",
    ):
        now = datetime.now(timezone.utc)
        return CandidateView(
            candidate_id=candidate_id,
            source="node-scan",
            node_name="etri-dev0001-jetorn",
            protocol="serial",
            transport="usb-serial",
            display_name=display_name,
            device_path="/dev/serial/by-id/usb-Arduino-001",
            decision=decision,
            presence="present",
            first_seen=now,
            last_seen=now,
            updated_at=now,
            matched_adapter_id="serial-jetson",
            matched_hardware_binding_id="jetson-arduino-serial-001",
            package_state="registration-ready",
            package_reason="검증된 연결과 일치",
            registration_ready=True,
        )

    async def list_inventory(self):
        self.calls.append(("list",))
        now = datetime.now(timezone.utc)
        return DiscoveryInventory(
            generated_at=now,
            stale_after_seconds=90,
            nodes=[
                DiscoveryNodeView(
                    node_name="etri-dev0001-jetorn",
                    agent_id="discovery/jetson",
                    last_report_at=now,
                    presence="online",
                    candidate_count=2,
                )
            ],
            candidates=[
                self.candidate(),
                self.candidate(
                    candidate_id="candidate-" + ("b" * 24),
                    decision="ignored",
                    display_name="Ignored port",
                ),
            ],
        )

    async def create_manual(self, candidate, request_ref):
        self.calls.append(
            (
                "create",
                candidate.display_name,
                request_ref.request_id,
                request_ref.payload_hash,
            )
        )
        created = self.candidate(display_name=candidate.display_name)
        return created.model_copy(
            update={
                "source": "manual",
                "protocol": candidate.protocol,
                "transport": candidate.transport,
                "device_path": candidate.device_path,
                "properties": candidate.properties,
                "presence": "declared",
                "package_state": "verification-required",
                "registration_ready": False,
            }
        )

    async def update_decision(self, candidate_id, request):
        self.calls.append(
            (
                "decision",
                candidate_id,
                request.decision,
                request.request_ref.request_id,
            )
        )
        return self.candidate(candidate_id=candidate_id).model_copy(
            update={"decision": request.decision}
        )

    async def delete_candidate(self, candidate_id, request_ref):
        self.calls.append(("delete", candidate_id, request_ref.request_id))
        return self.candidate(candidate_id=candidate_id)

    async def decommission_candidate(
        self,
        candidate_id,
        *,
        reason,
        actor,
        request_ref,
    ):
        self.calls.append(
            (
                "decommission",
                candidate_id,
                reason,
                actor,
                request_ref.request_id,
            )
        )
        return self.candidate(candidate_id=candidate_id).model_copy(
            update={"state": "EVENT_CONFIRMED", "decision": "accepted"}
        )


def settings(
    *,
    enabled=False,
    hmac_key=None,
    runtime_management=False,
    runtime_mutation=False,
    discovery_management=False,
):
    return Settings(
        device_management_enabled=enabled,
        device_management_hmac_key=hmac_key,
        adapter_runtime_management_enabled=runtime_management,
        adapter_runtime_mutation_enabled=runtime_mutation,
        device_discovery_management_enabled=discovery_management,
        adapter_controller_internal_hmac_key=(
            "internal-hmac" if runtime_management else None
        ),
    )


def client_for(
    service,
    *,
    enabled=False,
    hmac_key=None,
    runtime_management=False,
    runtime_mutation=False,
    runtime_service=None,
    connection_service=None,
    discovery_management=False,
    discovery_service=None,
):
    if runtime_management and connection_service is None:
        connection_service = RecordingConnectionService()
    app = FastAPI()
    app.include_router(
        create_device_management_router(
            settings(
                enabled=enabled,
                hmac_key=hmac_key,
                runtime_management=runtime_management,
                runtime_mutation=runtime_mutation,
                discovery_management=discovery_management,
            ),
            service,
            runtime_service=runtime_service,
            connection_service=connection_service,
            discovery_service=discovery_service,
        )
    )
    return TestClient(app)


def mutation_headers(**extra):
    return {
        "Idempotency-Key": "request-key",
        **extra,
    }


def runtime_plan_payload():
    return {
        "adapterId": "serial-jetson",
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-arduino-serial-001",
        "mode": "auto",
    }


def connection_request_payload():
    return {
        "adapterId": "serial-jetson",
        "runtime": {
            "mode": "auto",
            "targetNode": "etri-dev0001-jetorn",
            "hardwareBindingId": "jetson-arduino-serial-001",
        },
        "device": request_payload()["device"],
        "profile": request_payload()["profile"],
    }


def connection_request_model():
    from app.connection_management_models import ConnectionOnboardingRequest

    return ConnectionOnboardingRequest.model_validate(
        connection_request_payload()
    )


def discovery_client(discovery_service):
    return client_for(
        RecordingService(),
        enabled=True,
        hmac_key="hmac",
        runtime_management=True,
        runtime_mutation=True,
        runtime_service=RecordingRuntimeService(),
        connection_service=RecordingConnectionService(),
        discovery_management=True,
        discovery_service=discovery_service,
    )


def test_discovery_inventory_filters_ignored_candidates_and_supports_search():
    discovery = RecordingDiscoveryService()
    with discovery_client(discovery) as client:
        default = client.get("/management/discovery")
        ignored = client.get(
            "/management/discovery",
            params={
                "includeIgnored": "true",
                "decision": "ignored",
                "q": "ignored",
            },
        )

    assert default.status_code == 200
    assert "decisionAuthenticationRequired" not in default.json()
    assert default.json()["totalCandidates"] == 2
    assert default.json()["filteredCandidates"] == 1
    assert default.json()["candidates"][0]["displayName"] == "Arduino USB Serial"
    assert ignored.status_code == 200
    assert ignored.json()["filteredCandidates"] == 1
    assert ignored.json()["candidates"][0]["decision"] == "ignored"


def test_discovery_mutations_require_idempotency_and_send_hashed_identity():
    discovery = RecordingDiscoveryService()
    payload = {
        "nodeName": "etri-dev0001-jetorn",
        "protocol": "mqtt",
        "transport": "mqtts",
        "displayName": "Line MQTT sensor",
        "properties": {
            "Broker": "mqtts://broker.example:8883",
            "Topic": "factory/line-1/temp",
        },
    }
    candidate_id = "candidate-" + ("a" * 24)
    with discovery_client(discovery) as client:
        missing_idempotency = client.post(
            "/management/discovery/manual",
            json=payload,
        )
        created = client.post(
            "/management/discovery/manual",
            json=payload,
            headers=mutation_headers(),
        )
        accepted = client.patch(
            f"/management/discovery/{candidate_id}",
            json={"decision": "accepted", "note": "현장 확인"},
            headers=mutation_headers(),
        )
        deleted = client.delete(
            f"/management/discovery/{candidate_id}",
            headers=mutation_headers(),
        )

    assert missing_idempotency.status_code == 400
    assert created.status_code == 201
    assert created.json()["presence"] == "declared"
    assert accepted.status_code == 200
    assert accepted.json()["decision"] == "accepted"
    assert deleted.status_code == 200
    mutation_calls = [item for item in discovery.calls if item[0] != "list"]
    assert [item[0] for item in mutation_calls] == ["create", "decision", "delete"]
    assert all(len(item[-1]) == 64 for item in mutation_calls)


def test_management_mutations_ignore_unrelated_authorization_header():
    discovery = RecordingDiscoveryService()
    candidate_id = "candidate-" + ("b" * 24)
    headers = {
        "Idempotency-Key": "decision-with-irrelevant-header",
        "Authorization": "Bearer unrelated-client-value",
    }
    with discovery_client(discovery) as client:
        inventory = client.get("/management/discovery")
        accepted = client.patch(
            f"/management/discovery/{candidate_id}",
            json={"decision": "accepted", "note": "PoC 운영자 승인"},
            headers=headers,
        )
        missing_idempotency = client.patch(
            f"/management/discovery/{candidate_id}",
            json={"decision": "accepted", "note": "idempotency 없음"},
        )

    assert inventory.status_code == 200
    assert "decisionAuthenticationRequired" not in inventory.json()
    assert accepted.status_code == 200
    assert accepted.json()["decision"] == "accepted"
    assert missing_idempotency.status_code == 400
    mutation_calls = [item for item in discovery.calls if item[0] != "list"]
    assert [item[0] for item in mutation_calls] == ["decision"]


def test_candidate_decommission_requires_exact_confirmation():
    discovery = RecordingDiscoveryService()
    candidate_id = "candidate-" + ("c" * 24)
    with discovery_client(discovery) as client:
        missing_confirmation = client.post(
            f"/management/discovery/{candidate_id}/decommission",
            json={"reason": "fixture cleanup"},
            headers=mutation_headers(),
        )
        removed = client.post(
            f"/management/discovery/{candidate_id}/decommission",
            json={"reason": "fixture cleanup"},
            headers={
                **mutation_headers(),
                "X-Confirm-Candidate": candidate_id,
            },
        )

    assert missing_confirmation.status_code == 409
    assert removed.status_code == 200
    assert discovery.calls[-1][0:4] == (
        "decommission",
        candidate_id,
        "fixture cleanup",
        "dashboard-operator",
    )


def test_management_openapi_has_no_authorization_header_parameter():
    discovery = RecordingDiscoveryService()
    with discovery_client(discovery) as client:
        schema = client.get("/openapi.json").json()

    mutation_paths = {
        "/management/devices": {"post"},
        "/management/devices/{name}": {"patch", "delete"},
        "/management/connections": {"post"},
        "/management/adapter-runtimes/{name}/restart": {"post"},
        "/management/adapter-runtimes/{name}": {"delete"},
        "/management/discovery/manual": {"post"},
        "/management/discovery/{candidate_id}": {"patch", "delete"},
        "/management/discovery/{candidate_id}/decommission": {"post"},
    }
    for path, methods in mutation_paths.items():
        for method in methods:
            parameters = schema["paths"][path][method].get("parameters", [])
            assert all(
                parameter["name"].lower() != "authorization"
                for parameter in parameters
            )


def test_read_only_catalog_and_validation_work_while_mutation_is_disabled():
    service = RecordingService()
    with client_for(service) as client:
        adapters = client.get("/management/adapters")
        validation = client.post("/management/devices/validate", json=request_payload())

    assert adapters.status_code == 200
    assert adapters.json()[0]["adapterId"] == "serial-jetson"
    assert adapters.json()[0]["mutationEnabled"] is False
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert ("validate", "virtual-temperature-002", "viewer") in service.calls


def test_catalog_exposes_enabled_mutation_mode_to_the_dashboard():
    service = RecordingService()
    with client_for(service, enabled=True, hmac_key="hmac") as client:
        response = client.get("/management/adapters")

    assert response.status_code == 200
    assert response.json()[0]["mutationEnabled"] is True


def test_mutation_is_hidden_when_feature_flag_is_disabled():
    service = RecordingService()
    with client_for(service) as client:
        response = client.post(
            "/management/devices", json=request_payload(), headers=mutation_headers()
        )

    assert response.status_code == 404
    assert not any(call[0] == "create" for call in service.calls)


def test_enabled_router_fails_fast_without_hmac_key():
    service = RecordingService()

    with pytest.raises(ValueError, match="HMAC"):
        client_for(service, enabled=True)


def test_create_requires_idempotency_key():
    service = RecordingService()
    with client_for(service, enabled=True, hmac_key="hmac") as client:
        response = client.post(
            "/management/devices",
            json=request_payload(),
        )

    assert response.status_code == 400
    assert not any(call[0] == "create" for call in service.calls)


def test_create_returns_operation_without_internal_payload_hash():
    service = RecordingService()
    with client_for(service, enabled=True, hmac_key="hmac") as client:
        response = client.post(
            "/management/devices",
            json=request_payload(),
            headers=mutation_headers(),
        )

    assert response.status_code == 201
    assert response.json()["requestId"] == "request-01"
    assert response.json()["status"] == "waiting_for_event"
    assert "payloadHash" not in response.json()
    assert service.calls[-1] == (
        "create",
        "virtual-temperature-002",
        "request-key",
        "dashboard-operator",
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
        with client_for(service, enabled=True, hmac_key="hmac") as client:
            response = client.post(
                "/management/devices",
                json=request_payload(),
                headers=mutation_headers(),
            )
        assert response.status_code == expected


def test_apply_failure_returns_gateway_error_with_safe_operation_identity():
    service = RecordingService()
    service.create_error = ManagementApplyError(
        operation("failed"), RuntimeError("metadata unavailable")
    )
    with client_for(service, enabled=True, hmac_key="hmac") as client:
        response = client.post(
            "/management/devices",
            json=request_payload(),
            headers=mutation_headers(),
        )

    assert response.status_code == 502
    assert response.json()["detail"]["requestId"] == "request-01"
    assert response.json()["detail"]["status"] == "failed"
    assert "payloadHash" not in response.text


def test_patch_uses_path_identity_and_allowlisted_body():
    service = RecordingService()
    with client_for(service, enabled=True, hmac_key="hmac") as client:
        response = client.patch(
            "/management/devices/device-01",
            json={"description": "updated"},
            headers=mutation_headers(),
        )

    assert response.status_code == 200
    assert response.json()["action"] == "patch"
    assert service.calls[-1] == (
        "patch",
        "device-01",
        "updated",
        "request-key",
        "dashboard-operator",
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


def test_delete_requires_exact_confirmation_and_is_idempotent():
    service = RecordingService()
    with client_for(service, enabled=True, hmac_key="hmac") as client:
        missing_confirmation = client.delete(
            "/management/devices/device-01",
            headers=mutation_headers(),
        )
        deleted = client.delete(
            "/management/devices/device-01",
            headers={
                **mutation_headers(),
                "X-Confirm-Device": "device-01",
            },
        )

    assert missing_confirmation.status_code == 409
    assert deleted.status_code == 200
    assert deleted.json()["action"] == "delete"
    assert service.calls[-1] == (
        "delete",
        "device-01",
        "request-key",
        "dashboard-operator",
    )


def test_runtime_routes_are_hidden_until_management_flag_is_enabled():
    runtime_service = RecordingRuntimeService()
    with client_for(
        RecordingService(),
        runtime_service=runtime_service,
    ) as client:
        response = client.get("/management/adapter-runtimes")

    assert response.status_code == 404
    assert runtime_service.calls == []


def test_runtime_inventory_and_plan_are_read_only_when_mutation_is_disabled():
    runtime_service = RecordingRuntimeService()
    with client_for(
        RecordingService(),
        runtime_management=True,
        runtime_service=runtime_service,
    ) as client:
        listed = client.get("/management/adapter-runtimes")
        planned = client.post(
            "/management/adapter-runtimes/plan",
            json=runtime_plan_payload(),
        )
        restart = client.post(
            "/management/adapter-runtimes/adapter-serial-02/restart",
            headers=mutation_headers(),
        )

    assert listed.status_code == 200
    assert listed.json()[0]["managementMode"] == "external"
    assert listed.json()[0]["mutationEnabled"] is False
    assert planned.status_code == 200
    assert planned.json()["action"] == "REUSE"
    assert restart.status_code == 404


def test_runtime_restart_and_retire_require_idempotency_and_exact_confirm():
    runtime_service = RecordingRuntimeService()
    common = {
        "enabled": True,
        "hmac_key": "hmac",
        "runtime_management": True,
        "runtime_mutation": True,
        "runtime_service": runtime_service,
    }
    with client_for(RecordingService(), **common) as client:
        unauthorized = client.post(
            "/management/adapter-runtimes/adapter-serial-02/restart"
        )
        restarted = client.post(
            "/management/adapter-runtimes/adapter-serial-02/restart",
            headers=mutation_headers(),
        )
        missing_confirm = client.delete(
            "/management/adapter-runtimes/adapter-serial-02",
            headers=mutation_headers(),
        )
        retired = client.delete(
            "/management/adapter-runtimes/adapter-serial-02",
            headers=mutation_headers(
                **{"X-Confirm-Runtime": "adapter-serial-02"}
            ),
        )

    assert unauthorized.status_code == 400
    assert restarted.status_code == 200
    assert missing_confirm.status_code == 409
    assert retired.status_code == 200
    assert [item[0] for item in runtime_service.calls].count(
        "restart_runtime"
    ) == 1
    assert [item[0] for item in runtime_service.calls].count(
        "retire_runtime"
    ) == 1


def test_connection_validation_is_read_only_and_apply_requires_idempotency():
    runtime_service = RecordingRuntimeService()
    connection_service = RecordingConnectionService()
    common = {
        "runtime_management": True,
        "runtime_mutation": True,
        "runtime_service": runtime_service,
        "connection_service": connection_service,
    }
    with client_for(
        RecordingService(),
        enabled=True,
        hmac_key="hmac",
        **common,
    ) as client:
        validated = client.post(
            "/management/connections/validate",
            json=connection_request_payload(),
        )
        applied = client.post(
            "/management/connections",
            json=connection_request_payload(),
            headers=mutation_headers(),
        )
        polled = client.get(
            "/management/connections/operations/connection-request"
        )

    assert validated.status_code == 200
    assert validated.json()["runtimePlan"]["action"] == "REUSE"
    assert applied.status_code == 201
    assert applied.json()["status"] == "WAITING_EVENT"
    assert "payloadHash" not in applied.json()
    assert polled.status_code == 200
    assert polled.json()["status"] == "ACTIVE"


def test_connection_and_runtime_domain_errors_are_mapped():
    invalid = ConnectionValidationResult(
        valid=False,
        issues=[ValidationIssue(code="runtime_unavailable", message="blocked")],
        runtime_plan=RuntimePlan(
            action="BLOCKED",
            allowed=False,
            adapter_id="serial-jetson",
            target_node="etri-dev0001-jetorn",
            hardware_binding_id="jetson-arduino-serial-001",
            verification_state="hardware-verified",
            reasons=[],
            plan_hash="f" * 64,
        ),
    )
    connection_cases = [
        (ConnectionValidationError(invalid), 422),
        (ConnectionIdempotencyConflict("different"), 409),
        (ConnectionOperationNotFound("missing"), 404),
    ]
    for error, expected in connection_cases:
        connection_service = RecordingConnectionService()
        connection_service.error = error
        with client_for(
            RecordingService(),
            enabled=True,
            hmac_key="hmac",
            runtime_management=True,
            runtime_mutation=True,
            runtime_service=RecordingRuntimeService(),
            connection_service=connection_service,
        ) as client:
            response = client.post(
                "/management/connections",
                json=connection_request_payload(),
                headers=mutation_headers(),
            )
        assert response.status_code == expected

    runtime_service = RecordingRuntimeService()
    runtime_service.error = ExternalRuntimeMutationError("read-only")
    with client_for(
        RecordingService(),
        enabled=True,
        hmac_key="hmac",
        runtime_management=True,
        runtime_mutation=True,
        runtime_service=runtime_service,
    ) as client:
        response = client.post(
            "/management/adapter-runtimes/device-serial-jetson/restart",
            headers=mutation_headers(),
        )
    assert response.status_code == 409


def test_repository_app_registers_default_disabled_mutation_route():
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/management/devices",
            json=request_payload(),
            headers=mutation_headers(),
        )

    assert response.status_code == 404
