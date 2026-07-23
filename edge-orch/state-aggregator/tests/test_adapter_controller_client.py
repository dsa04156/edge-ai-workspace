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
