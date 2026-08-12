import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.adapter_controller_client import (
    AdapterControllerBackendError,
    AdapterControllerClient,
    AdapterControllerResponseError,
)
from app.adapter_runtime_models import RuntimePlanRequest
from app.device_discovery_models import (
    CandidateDecommissionUpdate,
    CandidateMutationRef,
    ManualCandidateCreate,
    ManualCandidateInput,
)


HMAC_KEY = "state-aggregator-controller-hmac"


def runtime_payload():
    return {
        "runtimeName": "device-serial-jetson",
        "adapterId": "serial-jetson",
        "templateId": "serial-device-service-v1",
        "serviceName": "device-serial-jetson",
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-arduino-serial-001",
        "managementMode": "external",
        "managementOwner": "argocd",
        "purpose": "operational",
        "verificationState": "hardware-verified",
        "phase": "SERVICE_READY",
        "consumers": 6,
        "mutable": False,
        "workloadName": "device-serial-jetson",
    }


def verify_signature(request: httpx.Request):
    timestamp = request.headers["X-Controller-Timestamp"]
    signature = request.headers["X-Controller-Signature"]
    body_hash = hashlib.sha256(request.content).hexdigest()
    canonical = (
        f"{timestamp}\n{request.method}\n{request.url.path}\n{body_hash}"
    ).encode()
    expected = hmac.new(
        HMAC_KEY.encode(),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(signature, expected)
    assert "Authorization" not in request.headers


def test_client_signs_list_and_parses_strict_runtime_response():
    def handler(request):
        verify_signature(request)
        assert request.url.path == "/internal/v1/runtimes"
        return httpx.Response(200, json=[runtime_payload()])

    client = AdapterControllerClient(
        "http://controller",
        HMAC_KEY,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(client.list_runtimes())

    assert result[0].runtime_name == "device-serial-jetson"
    assert result[0].management_mode == "external"
    assert result[0].purpose == "operational"


def test_client_sends_only_allowlisted_plan_fields():
    def handler(request):
        verify_signature(request)
        payload = json.loads(request.content)
        assert payload == {
            "adapterId": "serial-jetson",
            "targetNode": "etri-dev0001-jetorn",
            "hardwareBindingId": "jetson-arduino-serial-001",
            "mode": "auto",
        }
        return httpx.Response(
            200,
            json={
                "action": "REUSE",
                "allowed": True,
                "adapterId": "serial-jetson",
                "templateId": "serial-device-service-v1",
                "runtimeName": "device-serial-jetson",
                "serviceName": "device-serial-jetson",
                "targetNode": "etri-dev0001-jetorn",
                "hardwareBindingId": "jetson-arduino-serial-001",
                "managementMode": "external",
                "verificationState": "hardware-verified",
                "reasons": [],
                "planHash": "a" * 64,
            },
        )

    client = AdapterControllerClient(
        "http://controller",
        HMAC_KEY,
        transport=httpx.MockTransport(handler),
    )
    request = RuntimePlanRequest(
        adapter_id="serial-jetson",
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-arduino-serial-001",
        mode="auto",
    )

    result = asyncio.run(client.plan_runtime(request))

    assert result.action == "REUSE"
    assert result.plan_hash == "a" * 64


def test_client_forwards_allowlisted_mqtt_runtime_settings():
    settings_hash = "b" * 64

    def handler(request):
        verify_signature(request)
        payload = json.loads(request.content)
        assert payload["settings"] == {
            "Broker": (
                "mqtt://edge-mqtt-simulator.edgex-edge.svc.cluster.local:1883"
            ),
            "IncomingTopic": "incoming/data/#",
            "Qos": 0,
        }
        return httpx.Response(
            200,
            json={
                "action": "DEPLOY",
                "allowed": True,
                "adapterId": "mqtt",
                "templateId": "mqtt-device-service-v1",
                "runtimeName": "adapter-mqtt-0123456789",
                "serviceName": "device-mqtt_0123456789",
                "targetNode": "etri-dev0001-jetorn",
                "hardwareBindingId": "jetson-mqtt-network-001",
                "managementMode": "controller",
                "verificationState": "template-verified",
                "settingsHash": settings_hash,
                "reasons": [],
                "planHash": "a" * 64,
            },
        )

    client = AdapterControllerClient(
        "http://controller",
        HMAC_KEY,
        transport=httpx.MockTransport(handler),
    )
    request = RuntimePlanRequest(
        adapter_id="mqtt",
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-mqtt-network-001",
        mode="auto",
        settings={
            "Broker": (
                "mqtt://edge-mqtt-simulator.edgex-edge.svc.cluster.local:1883"
            ),
            "IncomingTopic": "incoming/data/#",
            "Qos": 0,
        },
    )

    result = asyncio.run(client.plan_runtime(request))

    assert result.action == "DEPLOY"
    assert result.settings_hash == settings_hash


def test_client_maps_backend_and_invalid_contract_without_leaking_body():
    cases = [
        (
            httpx.MockTransport(
                lambda request: httpx.Response(
                    500,
                    text="secret backend details",
                )
            ),
            AdapterControllerBackendError,
        ),
        (
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"unexpected": "secret response"},
                )
            ),
            AdapterControllerResponseError,
        ),
    ]

    for transport, expected in cases:
        client = AdapterControllerClient(
            "http://controller",
            HMAC_KEY,
            transport=transport,
        )
        with pytest.raises(expected) as caught:
            asyncio.run(client.list_runtimes())
        assert "secret" not in str(caught.value)


def test_client_rejects_missing_internal_hmac_key():
    with pytest.raises(ValueError, match="HMAC"):
        AdapterControllerClient("http://controller", "")


def test_client_signs_discovery_queries_and_manual_candidate_mutation():
    now = "2026-07-24T10:00:00+00:00"

    def candidate_payload():
        return {
            "candidateId": "candidate-" + ("a" * 24),
            "source": "manual",
            "nodeName": "etri-dev0001-jetorn",
            "protocol": "mqtt",
            "transport": "mqtts",
            "displayName": "Line MQTT sensor",
            "properties": {
                "Broker": "mqtts://broker.example:8883",
                "Topic": "factory/line-1/temp",
            },
            "decision": "pending",
            "presence": "declared",
            "firstSeen": now,
            "lastSeen": now,
            "updatedAt": now,
            "matchedAdapterId": "mqtt",
            "packageState": "verification-required",
            "packageReason": "실기기 검증 필요",
            "registrationReady": False,
        }

    def handler(request):
        verify_signature(request)
        if request.method == "GET":
            assert request.url.path == "/internal/v1/discovery"
            return httpx.Response(
                200,
                json={
                    "generatedAt": now,
                    "staleAfterSeconds": 90,
                    "nodes": [],
                    "candidates": [candidate_payload()],
                },
            )
        assert request.url.path == "/internal/v1/discovery/manual"
        payload = json.loads(request.content)
        assert "requestRef" in payload
        assert payload["candidate"]["properties"]["Topic"] == "factory/line-1/temp"
        return httpx.Response(201, json=candidate_payload())

    client = AdapterControllerClient(
        "http://controller",
        HMAC_KEY,
        transport=httpx.MockTransport(handler),
    )
    inventory = asyncio.run(client.list_discovery_inventory())
    created = asyncio.run(
        client.create_manual_candidate(
            ManualCandidateCreate(
                candidate=ManualCandidateInput(
                    node_name="etri-dev0001-jetorn",
                    protocol="mqtt",
                    transport="mqtts",
                    display_name="Line MQTT sensor",
                    properties={
                        "Broker": "mqtts://broker.example:8883",
                        "Topic": "factory/line-1/temp",
                    },
                ),
                request_ref=CandidateMutationRef(
                    request_id="b" * 64,
                    payload_hash="c" * 64,
                ),
            )
        )
    )

    assert inventory.candidates[0].source == "manual"
    assert created.protocol == "mqtt"


def test_client_decommission_requires_exact_candidate_header():
    now = "2026-07-24T10:00:00+00:00"
    candidate_id = "candidate-" + ("d" * 24)

    def handler(request):
        verify_signature(request)
        assert request.method == "POST"
        assert request.url.path == (
            f"/internal/v1/discovery/{candidate_id}/decommission"
        )
        assert request.headers["X-Confirm-Candidate"] == candidate_id
        payload = json.loads(request.content)
        assert payload["reason"] == "fixture cleanup"
        return httpx.Response(
            200,
            json={
                "candidateId": candidate_id,
                "source": "manual",
                "nodeName": "etri-dev0001-jetorn",
                "protocol": "modbus",
                "transport": "modbus-tcp",
                "displayName": "fixture",
                "decision": "accepted",
                "state": "EVENT_CONFIRMED",
                "presence": "declared",
                "firstSeen": now,
                "lastSeen": now,
                "updatedAt": now,
                "packageState": "registration-ready",
                "packageReason": "verified",
                "registrationReady": True,
            },
        )

    result = asyncio.run(
        AdapterControllerClient(
            "http://controller",
            HMAC_KEY,
            transport=httpx.MockTransport(handler),
        ).decommission_candidate(
            candidate_id,
            CandidateDecommissionUpdate(
                actor="dashboard-operator",
                reason="fixture cleanup",
                request_ref=CandidateMutationRef(
                    request_id="e" * 64,
                    payload_hash="f" * 64,
                ),
            ),
        )
    )

    assert result.state == "EVENT_CONFIRMED"
