import asyncio
import json
import time

import httpx
import pytest

from telemetry_plane.commands import (
    MAX_COMMAND_BODY_BYTES,
    MAX_COMMAND_ENVELOPE_BYTES,
    MAX_COMMAND_IDENTIFIER_BYTES,
    CommandError,
    CommandExpiredError,
    CommandRequest,
    CommandUnavailableError,
    HTTPSCommandBridge,
    TerminalCommandCache,
    TerminalCommandResult,
    command_fingerprint,
    command_from_payload,
)
from telemetry_plane.config import TLSSettings


def run(coro):
    return asyncio.run(coro)


def command_payload(**overrides):
    now = time.time()
    payload = {
        "edge_id": "etri-dev0001-jetorn",
        "device_name": "camera-1",
        "command_id": "cmd-read-1",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }
    payload.update(overrides)
    return payload


def request_from_payload(payload=None):
    return command_from_payload("etri-dev0001-jetorn", "camera-1", payload or command_payload())


def terminal(request, status=200, code="local_command_failed"):
    body = {"edge_id": request.edge_id, "command_id": request.command_id, "status": "failed",
            "error": {"code": code, "message": "failed"}}
    return TerminalCommandResult(command_fingerprint(request), status, body)


def test_command_policy_is_server_owned_and_request_id_is_rejected():
    with pytest.raises(CommandError, match="not supported"):
        request_from_payload(command_payload(operation="reboot"))
    with pytest.raises(CommandError, match="server-owned"):
        request_from_payload(command_payload(policy_version="client-policy"))
    with pytest.raises(CommandError, match="exactly"):
        request_from_payload(command_payload(request_id="legacy-id"))


def test_command_payload_rejects_expiry_identity_and_non_finite_json():
    now = time.time()
    with pytest.raises(CommandExpiredError, match="expired"):
        request_from_payload(command_payload(issued_at=now - 5, expires_at=now - 1))
    with pytest.raises(CommandError, match="edge_id"):
        request_from_payload(command_payload(edge_id="other-edge"))
    with pytest.raises(CommandError, match="device_name"):
        request_from_payload(command_payload(device_name="other-device"))
    with pytest.raises(CommandError, match="finite"):
        request_from_payload(command_payload(command={"measurement": float("nan")}))
    with pytest.raises(CommandError, match="exceeds"):
        request_from_payload(command_payload(command={"body": "x" * MAX_COMMAND_BODY_BYTES}))
    with pytest.raises(CommandError, match="exactly"):
        request_from_payload(command_payload(unexpected=True))
    with pytest.raises(CommandError, match="Unix timestamp"):
        request_from_payload(command_payload(issued_at="1"))
    with pytest.raises(CommandError, match="Unix timestamp"):
        request_from_payload(command_payload(expires_at=True))
    with pytest.raises(CommandError, match="finite"):
        request_from_payload(command_payload(issued_at=float("nan")))
    with pytest.raises(CommandError, match="exceeds"):
        request_from_payload(command_payload(command_id="x" * (MAX_COMMAND_IDENTIFIER_BYTES + 1)))
    with pytest.raises(CommandError, match="envelope exceeds"):
        request_from_payload(command_payload(unexpected="x" * MAX_COMMAND_ENVELOPE_BYTES))
    with pytest.raises(CommandError, match="finite"):
        request_from_payload(command_payload(unexpected=float("nan")))
def test_command_payload_rejects_future_issued_command_with_excess_remaining_ttl():
    now = 1_000.0
    with pytest.raises(CommandExpiredError, match="exceeds"):
        command_from_payload(
            "etri-dev0001-jetorn",
            "camera-1",
            command_payload(issued_at=now + 20, expires_at=now + 50),
            max_ttl_seconds=30,
            now=now,
        )



def test_terminal_cache_is_request_bound_and_preserves_status():
    request = request_from_payload()
    cache = TerminalCommandCache(1)
    cached = terminal(request, 502)
    cache.put(request.command_id, cached)
    assert cache.get(request.command_id) == cached
    assert cache.get(request.command_id).status_code == 502
    with pytest.raises(ValueError, match="mutually exclusive"):
        cache.put(request.command_id, TerminalCommandResult(
            command_fingerprint(request), 200,
            {"edge_id": request.edge_id, "command_id": request.command_id, "status": "succeeded",
             "result": {}, "error": {"code": "unexpected", "message": "unexpected"}},
        ))
    with pytest.raises(ValueError, match="inconsistent"):
        cache.put(request.command_id, TerminalCommandResult(
            command_fingerprint(request), 200,
            {"edge_id": request.edge_id, "command_id": request.command_id, "status": "failed",
             "error": {"code": "failed", "message": "failed"}},
        ))


async def _bridge_response(status, body, encoded_device_name="camera-1"):
    async def handler(request):
        assert request.url.raw_path == f"/v1/commands/{encoded_device_name}".encode()
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_https_bridge_encodes_device_name_and_forwards_terminal_success():
    request = command_from_payload("etri-dev0001-jetorn", "camera/a b", command_payload(device_name="camera/a b"))
    body = {"edge_id": request.edge_id, "command_id": request.command_id, "status": "succeeded", "result": {}}
    client = run(_bridge_response(200, body, "camera%2Fa%20b"))
    bridge = HTTPSCommandBridge({"etri-dev0001-jetorn": "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    assert run(bridge.request(request)) == body
    run(client.aclose())


def test_https_bridge_maps_non_success_terminal_responses_and_expiry():
    request = request_from_payload()
    failed = {"edge_id": request.edge_id, "command_id": request.command_id, "status": "failed",
              "error": {"code": "invalid_command", "message": "rejected"}}
    client = run(_bridge_response(400, failed))
    bridge = HTTPSCommandBridge({request.edge_id: "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandError, match="rejected"):
        run(bridge.request(request))
    run(client.aclose())

    expired = {**failed, "error": {"code": "command_expired", "message": "expired"}}
    client = run(_bridge_response(504, expired))
    bridge = HTTPSCommandBridge({request.edge_id: "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandExpiredError, match="expired"):
        run(bridge.request(request))
    run(client.aclose())

    client = run(_bridge_response(503, failed))
    bridge = HTTPSCommandBridge({request.edge_id: "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandUnavailableError, match="not queued"):
        run(bridge.request(request))
    run(client.aclose())


def test_https_bridge_timeout_is_unavailable_and_never_replayed():
    calls = []

    async def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("edge offline", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    bridge = HTTPSCommandBridge({"etri-dev0001-jetorn": "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandUnavailableError, match="not queued"):
        run(bridge.request(request_from_payload()))
    assert len(calls) == 1
    run(client.aclose())
def test_read_status_rejects_payload_smuggling_and_huge_timestamps():
    with pytest.raises(CommandError, match="server-owned operation schema"):
        request_from_payload(command_payload(command={"write": True}))
    with pytest.raises(CommandError, match="Unix timestamp"):
        request_from_payload(command_payload(expires_at=10 ** 10_000))


def test_https_bridge_rejects_status_mismatch_and_non_finite_terminal_body():
    request = request_from_payload()
    failed = {"edge_id": request.edge_id, "command_id": request.command_id, "status": "failed",
              "error": {"code": "invalid_command", "message": "rejected"}}
    client = run(_bridge_response(200, failed))
    bridge = HTTPSCommandBridge({request.edge_id: "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandError, match="inconsistent"):
        run(bridge.request(request))
    run(client.aclose())

    raw_succeeded = (
        f'{{"edge_id":{json.dumps(request.edge_id)},"command_id":{json.dumps(request.command_id)},'
        '"status":"succeeded","result":{"value":NaN}}'
    ).encode()

    async def handler(_request):
        return httpx.Response(200, content=raw_succeeded)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    bridge = HTTPSCommandBridge({request.edge_id: "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandError, match="finite"):
        run(bridge.request(request))
    run(client.aclose())
    contradictory = {"edge_id": request.edge_id, "command_id": request.command_id, "status": "succeeded",
                     "result": {}, "error": {"code": "unexpected", "message": "unexpected"}}
    client = run(_bridge_response(200, contradictory))
    bridge = HTTPSCommandBridge({request.edge_id: "https://edge-one:8443"}, TLSSettings("ca", "cert", "key"), client)
    with pytest.raises(CommandError, match="mutually exclusive"):
        run(bridge.request(request))
    run(client.aclose())
