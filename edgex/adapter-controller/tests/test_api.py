import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import (
    ControllerConflict,
    ControllerNotFound,
    ControllerValidationError,
    create_controller_router,
)
from app.config import Settings


HMAC_KEY = "controller-test-hmac-key"


def plan_payload():
    return {
        "adapterId": "serial-jetson",
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-arduino-serial-001",
        "mode": "auto",
    }


def apply_payload():
    return {
        "plan": plan_payload(),
        "requestRef": {
            "requestId": "a" * 64,
            "payloadHash": "b" * 64,
            "planHash": "c" * 64,
        },
    }


def runtime_payload(name="device-serial-jetson", management_mode="external"):
    return {
        "runtimeName": name,
        "adapterId": "serial-jetson",
        "templateId": "serial-device-service-v1",
        "serviceName": name,
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-arduino-serial-001",
        "managementMode": management_mode,
        "managementOwner": "argocd" if management_mode == "external" else "controller",
        "verificationState": "hardware-verified",
        "phase": "SERVICE_READY",
        "consumers": 6,
        "mutable": management_mode == "controller",
    }


class RecordingService:
    def __init__(self):
        self.calls = []
        self.error = None

    def list_runtimes(self):
        self.calls.append(("list",))
        if self.error:
            raise self.error
        return [runtime_payload()]

    def plan(self, request):
        self.calls.append(("plan", request.adapter_id, request.mode))
        if self.error:
            raise self.error
        return {
            "action": "REUSE",
            "allowed": True,
            "adapterId": request.adapter_id,
            "templateId": "serial-device-service-v1",
            "runtimeName": "device-serial-jetson",
            "serviceName": "device-serial-jetson",
            "targetNode": request.target_node,
            "hardwareBindingId": request.hardware_binding_id,
            "managementMode": "external",
            "verificationState": "hardware-verified",
            "reasons": [],
            "planHash": "c" * 64,
        }

    def apply_runtime(self, name, request):
        self.calls.append(("apply", name, request.request_ref.request_id))
        if self.error:
            raise self.error
        return runtime_payload(name, "controller")

    def restart_runtime(self, name, request):
        self.calls.append(("restart", name, request.request_id))
        if self.error:
            raise self.error
        return runtime_payload(name, "controller")

    def retire_runtime(self, name, request):
        self.calls.append(("retire", name, request.request_id))
        if self.error:
            raise self.error
        result = runtime_payload(name, "controller")
        result["phase"] = "RETIRED"
        return result


def settings(*, mutation_enabled=False):
    return Settings(
        namespace="edgex-edge",
        internal_hmac_key=HMAC_KEY,
        mutation_enabled=mutation_enabled,
        signature_max_age_seconds=60,
    )


def client_for(service, *, mutation_enabled=False):
    app = FastAPI()
    app.include_router(
        create_controller_router(
            settings(mutation_enabled=mutation_enabled),
            service,
        )
    )
    return TestClient(app)


def signed_headers(method, path, payload=None, *, timestamp=None, key=HMAC_KEY):
    timestamp = str(timestamp or int(time.time()))
    body = (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if payload is not None
        else b""
    )
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{timestamp}\n{method.upper()}\n{path}\n{body_hash}".encode()
    signature = hmac.new(key.encode(), canonical, hashlib.sha256).hexdigest()
    return {
        "X-Controller-Timestamp": timestamp,
        "X-Controller-Signature": signature,
        "Content-Type": "application/json",
    }, body


def request(
    client,
    method,
    path,
    payload=None,
    *,
    headers_override=None,
    **kwargs,
):
    headers, body = signed_headers(method, path, payload)
    headers.update(headers_override or {})
    return client.request(
        method,
        path,
        content=body,
        headers=headers,
        **kwargs,
    )


def test_read_only_list_and_plan_require_valid_hmac():
    service = RecordingService()
    with client_for(service) as client:
        unsigned = client.get("/internal/v1/runtimes")
        listed = request(client, "GET", "/internal/v1/runtimes")
        planned = request(
            client,
            "POST",
            "/internal/v1/runtimes/plan",
            plan_payload(),
        )

    assert unsigned.status_code == 401
    assert listed.status_code == 200
    assert listed.json()[0]["managementMode"] == "external"
    assert planned.status_code == 200
    assert planned.json()["action"] == "REUSE"


def test_signature_rejects_wrong_key_and_expired_timestamp():
    service = RecordingService()
    with client_for(service) as client:
        wrong_headers, _ = signed_headers(
            "GET",
            "/internal/v1/runtimes",
            key="wrong",
        )
        wrong = client.get("/internal/v1/runtimes", headers=wrong_headers)
        expired_headers, _ = signed_headers(
            "GET",
            "/internal/v1/runtimes",
            timestamp=int(time.time()) - 120,
        )
        expired = client.get("/internal/v1/runtimes", headers=expired_headers)

    assert wrong.status_code == 401
    assert expired.status_code == 401
    assert service.calls == []


def test_mutation_routes_are_hidden_when_flag_is_disabled():
    service = RecordingService()
    with client_for(service) as client:
        applied = request(
            client,
            "PUT",
            "/internal/v1/runtimes/adapter-serial-01",
            apply_payload(),
        )

    assert applied.status_code == 404
    assert not any(item[0] == "apply" for item in service.calls)


def test_guarded_apply_restart_and_retire_use_typed_request_identity():
    service = RecordingService()
    action = {"requestId": "d" * 64, "payloadHash": "e" * 64}
    with client_for(service, mutation_enabled=True) as client:
        applied = request(
            client,
            "PUT",
            "/internal/v1/runtimes/adapter-serial-01",
            apply_payload(),
        )
        restarted = request(
            client,
            "POST",
            "/internal/v1/runtimes/adapter-serial-01/restart",
            action,
        )
        retired = request(
            client,
            "DELETE",
            "/internal/v1/runtimes/adapter-serial-01",
            action,
            headers_override={
                "X-Confirm-Runtime": "adapter-serial-01",
            },
        )

    assert applied.status_code == 201
    assert restarted.status_code == 200
    assert retired.status_code == 200
    assert [item[0] for item in service.calls] == ["apply", "restart", "retire"]


def test_retire_requires_exact_runtime_confirmation():
    service = RecordingService()
    action = {"requestId": "d" * 64, "payloadHash": "e" * 64}
    path = "/internal/v1/runtimes/adapter-serial-01"
    with client_for(service, mutation_enabled=True) as client:
        headers, body = signed_headers("DELETE", path, action)
        missing = client.request("DELETE", path, content=body, headers=headers)
        headers["X-Confirm-Runtime"] = "different-runtime"
        wrong = client.request("DELETE", path, content=body, headers=headers)

    assert missing.status_code == 409
    assert wrong.status_code == 409
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ControllerNotFound("missing"), 404),
        (ControllerConflict("conflict"), 409),
        (ControllerValidationError("invalid"), 422),
    ],
)
def test_domain_errors_are_safely_mapped(error, expected):
    service = RecordingService()
    service.error = error
    with client_for(service) as client:
        response = request(client, "GET", "/internal/v1/runtimes")

    assert response.status_code == expected
    assert "payloadHash" not in response.text
    assert HMAC_KEY not in response.text


def test_health_endpoints_do_not_expose_configuration():
    with client_for(RecordingService()) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")

    assert health.json() == {"status": "ok"}
    assert ready.json() == {"status": "ready"}
    assert HMAC_KEY not in health.text + ready.text
