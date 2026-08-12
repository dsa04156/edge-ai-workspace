import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

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

    def list_discovery_inventory(self):
        self.calls.append(("list_discovery",))
        now = datetime.now(timezone.utc).isoformat()
        return {
            "generatedAt": now,
            "staleAfterSeconds": 90,
            "nodes": [],
            "candidates": [],
        }

    def ingest_discovery_report(self, report):
        self.calls.append(("report", report.node_name, len(report.candidates)))
        return self.list_discovery_inventory()

    def create_manual_candidate(self, request):
        self.calls.append(("manual", request.candidate.display_name))
        now = datetime.now(timezone.utc).isoformat()
        return {
            "candidateId": "candidate-" + ("a" * 24),
            "source": "manual",
            "nodeName": request.candidate.node_name,
            "protocol": request.candidate.protocol,
            "transport": request.candidate.transport,
            "displayName": request.candidate.display_name,
            "properties": request.candidate.properties,
            "decision": "pending",
            "presence": "declared",
            "firstSeen": now,
            "lastSeen": now,
            "updatedAt": now,
            "packageState": "verification-required",
            "packageReason": "검증 필요",
            "registrationReady": False,
        }


def settings(*, mutation_enabled=False, discovery_enabled=False):
    return Settings(
        namespace="edgex-edge",
        internal_hmac_key=HMAC_KEY,
        mutation_enabled=mutation_enabled,
        device_discovery_enabled=discovery_enabled,
        signature_max_age_seconds=60,
    )


def client_for(service, *, mutation_enabled=False, discovery_enabled=False):
    app = FastAPI()
    app.include_router(
        create_controller_router(
            settings(
                mutation_enabled=mutation_enabled,
                discovery_enabled=discovery_enabled,
            ),
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
    canonical_path = path.split("?", 1)[0]
    canonical = (
        f"{timestamp}\n{method.upper()}\n{canonical_path}\n{body_hash}"
    ).encode()
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


class DiscoveryV1Service(RecordingService):
    @staticmethod
    def candidate():
        now = datetime.now(timezone.utc).isoformat()
        return {
            "candidateId": "candidate-" + ("d" * 64),
            "source": "node-scan",
            "nodeName": "etri-dev0001-jetorn",
            "protocol": "serial",
            "transport": "usb-serial",
            "displayName": "Arduino",
            "devicePath": "/dev/serial/by-id/arduino",
            "hardwareId": "arduino-001",
            "properties": {},
            "evidence": {},
            "decision": "pending",
            "state": "PENDING_APPROVAL",
            "authState": "not_checked",
            "presence": "present",
            "firstSeen": now,
            "lastSeen": now,
            "updatedAt": now,
            "packageState": "registration-ready",
            "packageReason": "exact match",
            "registrationReady": True,
        }

    def list_discovery_inventory(self):
        payload = super().list_discovery_inventory()
        payload["candidates"] = [self.candidate()]
        return payload

    def get_candidate(self, candidate_id):
        self.calls.append(("get_candidate", candidate_id))
        return self.candidate()

    def approve_candidate(self, candidate_id, payload):
        self.calls.append(("approve_candidate", candidate_id, payload.actor))
        result = self.candidate()
        result["state"] = "APPROVED"
        result["decision"] = "accepted"
        result["authState"] = "approved"
        return result

    def decommission_candidate(self, candidate_id, payload):
        self.calls.append(
            ("decommission_candidate", candidate_id, payload.actor, payload.reason)
        )
        result = self.candidate()
        result["state"] = "REJECTED"
        result["decision"] = "ignored"
        return result

    def get_discovery_plan(self, node_id):
        return {
            "nodeId": node_id,
            "serial": {"enabled": True, "allowedVidPid": ["2341:0043"]},
        }

    def list_device_bindings(self):
        return {"version": 1, "bindings": [], "errors": []}

    def list_discovery_events(self, candidate_id=None, limit=200):
        return []


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


def test_discovery_report_and_manual_candidate_require_feature_and_signed_contract():
    service = RecordingService()
    report = {
        "nodeName": "etri-dev0001-jetorn",
        "agentId": "discovery/jetson",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "candidates": [],
        "scanErrors": [],
    }
    manual = {
        "candidate": {
            "nodeName": "etri-dev0001-jetorn",
            "protocol": "mqtt",
            "transport": "mqtts",
            "displayName": "Line MQTT sensor",
            "properties": {
                "Broker": "mqtts://broker.example:8883",
                "Topic": "factory/line/temp",
            },
        },
        "requestRef": {
            "requestId": "a" * 64,
            "payloadHash": "b" * 64,
        },
    }
    with client_for(
        service,
        mutation_enabled=True,
        discovery_enabled=True,
    ) as client:
        inventory = request(client, "GET", "/internal/v1/discovery")
        reported = request(
            client,
            "POST",
            "/internal/v1/discovery/reports",
            report,
        )
        created = request(
            client,
            "POST",
            "/internal/v1/discovery/manual",
            manual,
        )

    assert inventory.status_code == 200
    assert reported.status_code == 202
    assert created.status_code == 201
    assert created.json()["protocol"] == "mqtt"
    assert [item[0] for item in service.calls] == [
        "list_discovery",
        "report",
        "list_discovery",
        "manual",
    ]


def test_discovery_v1_list_filter_pagination_and_candidate_lookup():
    service = DiscoveryV1Service()
    list_path = (
        "/api/v1/discovery/candidates?"
        "nodeId=etri-dev0001-jetorn&protocol=serial&"
        "state=PENDING_APPROVAL&page=1&pageSize=10"
    )
    with client_for(
        service,
        mutation_enabled=True,
        discovery_enabled=True,
    ) as client:
        listed = request(client, "GET", list_path)
        candidate_id = service.candidate()["candidateId"]
        fetched = request(
            client,
            "GET",
            f"/api/v1/discovery/candidates/{candidate_id}",
        )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["state"] == "PENDING_APPROVAL"
    assert fetched.status_code == 200
    assert fetched.json()["hardwareId"] == "arduino-001"


def test_discovery_v1_approval_is_authenticated_and_typed():
    service = DiscoveryV1Service()
    candidate_id = service.candidate()["candidateId"]
    path = f"/api/v1/discovery/candidates/{candidate_id}/approve"
    payload = {
        "actor": "operator-1",
        "reason": "physical label verified",
        "requestRef": {
            "requestId": "7" * 64,
            "payloadHash": "8" * 64,
        },
    }
    with client_for(
        service,
        mutation_enabled=True,
        discovery_enabled=True,
    ) as client:
        unsigned = client.post(path, json=payload)
        approved = request(client, "POST", path, payload)

    assert unsigned.status_code == 401
    assert unsigned.headers["x-error-code"] == (
        "INTERNAL_SIGNATURE_INVALID"
    )
    assert approved.status_code == 200
    assert approved.json()["state"] == "APPROVED"
    assert ("approve_candidate", candidate_id, "operator-1") in service.calls


def test_internal_decommission_requires_exact_candidate_confirmation():
    service = DiscoveryV1Service()
    candidate_id = service.candidate()["candidateId"]
    path = f"/internal/v1/discovery/{candidate_id}/decommission"
    payload = {
        "actor": "operator-1",
        "reason": "development fixture cleanup",
        "requestRef": {
            "requestId": "9" * 64,
            "payloadHash": "a" * 64,
        },
    }
    with client_for(
        service,
        mutation_enabled=True,
        discovery_enabled=True,
    ) as client:
        missing = request(client, "POST", path, payload)
        decommissioned = request(
            client,
            "POST",
            path,
            payload,
            headers_override={"X-Confirm-Candidate": candidate_id},
        )

    assert missing.status_code == 409
    assert decommissioned.status_code == 200
    assert decommissioned.json()["decision"] == "ignored"
    assert (
        "decommission_candidate",
        candidate_id,
        "operator-1",
        "development fixture cleanup",
    ) in service.calls


def test_agent_can_read_conservative_discovery_plan():
    service = DiscoveryV1Service()
    path = "/internal/v1/discovery/plans/etri-dev0001-jetorn"
    with client_for(
        service,
        mutation_enabled=True,
        discovery_enabled=True,
    ) as client:
        response = request(client, "GET", path)

    assert response.status_code == 200
    assert response.json()["serial"]["allowedVidPid"] == ["2341:0043"]
