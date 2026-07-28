import asyncio
import json
from functools import wraps
from uuid import UUID

import httpx
import pytest

from app.device_management_edgex import (
    EdgeXManagementBackendError,
    EdgeXManagementClient,
    EdgeXManagementResponseError,
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def envelope(field=None, value=None, *, status=200, message=""):
    payload = {"apiVersion": "v3", "statusCode": status}
    if message:
        payload["message"] = message
    if field is not None:
        payload[field] = value
    return payload


def client_for(handler):
    return EdgeXManagementClient(
        "http://metadata.test",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )


def escaped_path(request):
    return request.url.raw_path.decode().split("?", 1)[0]


@async_test
async def test_lists_device_services_from_v3_envelope():
    async def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v3/deviceservice/all"
        assert dict(request.url.params) == {"offset": "0", "limit": "1000"}
        return httpx.Response(
            200,
            json=envelope(
                "services",
                [
                    {
                        "name": "device-serial-jetson",
                        "adminState": "UNLOCKED",
                        "baseAddress": "http://device-serial-jetson:59910",
                    }
                ],
            ),
        )

    services = await client_for(handler).list_device_services()

    assert services[0]["name"] == "device-serial-jetson"


@async_test
async def test_lists_device_profiles_from_v3_envelope():
    async def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v3/deviceprofile/all"
        assert dict(request.url.params) == {"offset": "0", "limit": "1000"}
        return httpx.Response(
            200,
            json=envelope(
                "profiles",
                [
                    {
                        "name": "web-temperature-v1",
                        "deviceResources": [
                            {
                                "name": "temperature",
                                "properties": {
                                    "valueType": "Float64",
                                    "readWrite": "R",
                                },
                            }
                        ],
                    }
                ],
            ),
        )

    profiles = await client_for(handler).list_profiles()

    assert profiles[0]["name"] == "web-temperature-v1"


@async_test
async def test_single_device_and_profile_return_none_only_for_http_404():
    async def handler(request):
        assert escaped_path(request) in {
            "/api/v3/device/name/missing%20device",
            "/api/v3/deviceprofile/name/missing%20profile",
        }
        return httpx.Response(404, json=envelope(status=404, message="not found"))

    client = client_for(handler)

    assert await client.get_device("missing device") is None
    assert await client.get_profile("missing profile") is None


@async_test
async def test_reads_device_and_profile_objects_from_v3_envelopes():
    async def handler(request):
        if request.url.path.endswith("/device/name/device-01"):
            return httpx.Response(
                200,
                json=envelope("device", {"name": "device-01", "protocols": {}}),
            )
        return httpx.Response(
            200,
            json=envelope("profile", {"name": "profile-01", "deviceResources": []}),
        )

    client = client_for(handler)

    assert (await client.get_device("device-01"))["name"] == "device-01"
    assert (await client.get_profile("profile-01"))["name"] == "profile-01"


@async_test
async def test_lists_all_devices_for_reserved_tag_reconstruction():
    async def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v3/device/all"
        assert dict(request.url.params) == {"offset": "0", "limit": "1000"}
        return httpx.Response(
            200,
            json=envelope("devices", [{"name": "device-01", "tags": {}}])
            | {"totalCount": 1},
        )

    assert await client_for(handler).list_devices() == [
        {"name": "device-01", "tags": {}}
    ]


@async_test
async def test_add_profile_sends_official_v3_request_array():
    captured = {}
    profile = {"name": "profile-01", "deviceResources": [], "deviceCommands": []}

    async def handler(request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json=[envelope(status=201) | {"id": "profile-id"}],
        )

    result = await client_for(handler).add_profile(profile)

    assert result == "profile-id"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/deviceprofile"
    assert len(captured["body"]) == 1
    request = captured["body"][0]
    assert request["apiVersion"] == "v3"
    UUID(request["requestId"])
    assert request["profile"] == profile


@async_test
async def test_add_device_sends_official_v3_request_array():
    captured = {}
    device = {
        "name": "device-01",
        "serviceName": "device-serial-jetson",
        "profileName": "profile-01",
        "adminState": "UNLOCKED",
        "operatingState": "UNKNOWN",
        "protocols": {"serial": {"Port": "/dev/arduino-001"}},
        "properties": {},
    }

    async def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json=[envelope(status=201) | {"id": "device-id"}])

    result = await client_for(handler).add_device(device)

    assert result == "device-id"
    assert captured["body"][0]["device"] == device
    UUID(captured["body"][0]["requestId"])


@async_test
async def test_patch_device_sends_only_name_and_allowlisted_patch():
    captured = {}

    async def handler(request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=[envelope(status=200)])

    await client_for(handler).patch_device(
        "device-01", {"description": "updated", "adminState": "LOCKED"}
    )

    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v3/device"
    assert captured["body"][0]["device"] == {
        "name": "device-01",
        "description": "updated",
        "adminState": "LOCKED",
    }


@async_test
async def test_delete_device_uses_exact_encoded_name():
    captured = {}

    async def handler(request):
        captured["method"] = request.method
        captured["path"] = escaped_path(request)
        return httpx.Response(200, json=envelope(status=200))

    await client_for(handler).delete_device("device 01")

    assert captured == {
        "method": "DELETE",
        "path": "/api/v3/device/name/device%2001",
    }


@async_test
async def test_lists_devices_by_profile_and_deletes_exact_profile_name():
    calls = []

    async def handler(request):
        calls.append((request.method, escaped_path(request), dict(request.url.params)))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=envelope("devices", [{"name": "device-01"}])
                | {"totalCount": 1},
            )
        return httpx.Response(200, json=envelope(status=200))

    client = client_for(handler)
    devices = await client.list_devices_by_profile("profile 01")
    await client.delete_profile("profile 01")

    assert devices == [{"name": "device-01"}]
    assert calls == [
        (
            "GET",
            "/api/v3/device/profile/name/profile%2001",
            {"offset": "0", "limit": "1000"},
        ),
        ("DELETE", "/api/v3/deviceprofile/name/profile%2001", {}),
    ]


@async_test
@pytest.mark.parametrize(
    "payload",
    [
        {"apiVersion": "v2", "statusCode": 200, "services": []},
        {"apiVersion": "v3", "statusCode": "200", "services": []},
        {"apiVersion": "v3", "statusCode": 200, "services": {}},
        {"apiVersion": "v3", "statusCode": 500, "message": "database failed", "services": []},
    ],
)
async def test_rejects_malformed_or_failed_edgex_envelope(payload):
    async def handler(_request):
        return httpx.Response(200, json=payload)

    with pytest.raises(EdgeXManagementResponseError):
        await client_for(handler).list_device_services()


@async_test
async def test_wraps_transport_and_non_404_http_failures():
    async def transport_failure(_request):
        raise httpx.ConnectError("offline")

    with pytest.raises(EdgeXManagementBackendError, match="offline"):
        await client_for(transport_failure).list_device_services()

    async def server_failure(_request):
        return httpx.Response(503, json=envelope(status=503, message="unavailable"))

    with pytest.raises(EdgeXManagementBackendError, match="503"):
        await client_for(server_failure).get_device("device-01")


@async_test
async def test_rejects_malformed_mutation_response_array():
    async def handler(_request):
        return httpx.Response(201, json={"apiVersion": "v3", "statusCode": 201})

    with pytest.raises(EdgeXManagementResponseError, match="array"):
        await client_for(handler).add_device({"name": "device-01"})
