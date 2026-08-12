import asyncio

import httpx
import pytest

from app.local_data import (
    TEMPERATURE_SOURCE,
    AxisSource,
    LocalDataClient,
    LocalDataResponseError,
    LocalDataUnavailable,
)
from app.models import AxisSample

SOURCE = AxisSource(
    axis="x",
    device_name="virtual-acceleration-x-001",
    resource_name="acceleration_x_raw",
)


def valid_payload() -> dict:
    return {
        "apiVersion": "v3",
        "statusCode": 200,
        "deviceName": SOURCE.device_name,
        "resourceName": SOURCE.resource_name,
        "count": 1,
        "retention": {"maxAge": "10m0s", "maxSamples": 10_000},
        "samples": [{"origin": 150, "valueType": "Int32", "value": 7}],
    }


def test_client_uses_source_identity_and_origin_cursor() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(
            "/api/v3/localdata/device/name/virtual-acceleration-x-001/"
            "resource/name/acceleration_x_raw"
        )
        assert request.url.params["from"] == "101"
        assert request.url.params["to"] == "200"
        assert request.url.params["limit"] == "1000"
        return httpx.Response(
            200,
            json={
                "apiVersion": "v3",
                "statusCode": 200,
                "deviceName": SOURCE.device_name,
                "resourceName": SOURCE.resource_name,
                "count": 1,
                "retention": {"maxAge": "10m0s", "maxSamples": 10_000},
                "samples": [{"origin": 150, "valueType": "Int32", "value": 7}],
            },
        )

    async def run() -> list:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.fetch(SOURCE, from_origin=101, to_origin=200)
        finally:
            await client.close()

    rows = asyncio.run(run())

    assert rows[0].origin == 150
    assert rows[0].value == 7


def test_client_reads_temperature_context_through_the_same_local_data_contract() -> (
    None
):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(
            "/api/v3/localdata/device/name/virtual-temperature-001/"
            "resource/name/temperature_raw"
        )
        return httpx.Response(
            200,
            json={
                "apiVersion": "v3",
                "statusCode": 200,
                "deviceName": TEMPERATURE_SOURCE.device_name,
                "resourceName": TEMPERATURE_SOURCE.resource_name,
                "count": 1,
                "retention": {"maxAge": "10m0s", "maxSamples": 10_000},
                "samples": [{"origin": 150, "valueType": "Int32", "value": 300}],
            },
        )

    async def run() -> list:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.fetch(
                TEMPERATURE_SOURCE,
                from_origin=None,
                to_origin=200,
            )
        finally:
            await client.close()

    rows = asyncio.run(run())

    assert rows == [AxisSample(origin=150, value_type="Int32", value=300)]


def test_client_accepts_finite_float64_for_replay_and_future_sensor_profiles() -> None:
    payload = valid_payload()
    payload["samples"] = [{"origin": 150, "valueType": "Float64", "value": 7.25}]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run() -> list:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.fetch(SOURCE, from_origin=None, to_origin=200)
        finally:
            await client.close()

    assert asyncio.run(run()) == [
        AxisSample(origin=150, value_type="Float64", value=7.25)
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"apiVersion": "v2"},
        {"statusCode": 500},
        {"deviceName": "wrong-device"},
        {"resourceName": "wrong-resource"},
        {"count": 2},
        {"retention": {"maxAge": "10m0s", "maxSamples": 0}},
        {"samples": [{"origin": 150, "valueType": "String", "value": "7"}]},
        {"samples": [{"origin": 0, "valueType": "Int32", "value": 7}]},
        {"samples": [{"origin": 150, "valueType": "Int32", "value": True}]},
    ],
)
def test_client_rejects_payload_outside_local_data_contract(change: dict) -> None:
    payload = valid_payload()
    payload.update(change)
    if "samples" in change:
        payload["count"] = len(change["samples"])

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run() -> None:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(LocalDataResponseError):
                await client.fetch(SOURCE, from_origin=None, to_origin=200)
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["connect", "status"])
def test_client_normalizes_transport_and_http_failures(failure: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("device service unavailable", request=request)
        return httpx.Response(503, json={"message": "unavailable"})

    async def run() -> None:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(LocalDataUnavailable):
                await client.fetch(SOURCE, from_origin=None, to_origin=200)
        finally:
            await client.close()

    asyncio.run(run())


def test_client_rejects_invalid_json_as_response_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
        )

    async def run() -> None:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(LocalDataResponseError):
                await client.fetch(SOURCE, from_origin=None, to_origin=200)
        finally:
            await client.close()

    asyncio.run(run())


def test_client_rejects_samples_that_are_not_origin_ordered() -> None:
    payload = valid_payload()
    payload["count"] = 2
    payload["samples"] = [
        {"origin": 200, "valueType": "Int32", "value": 8},
        {"origin": 150, "valueType": "Int32", "value": 7},
    ]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run() -> None:
        client = LocalDataClient(
            "http://device.test:59910",
            timeout_seconds=2.0,
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(LocalDataResponseError, match="origin ordered"):
                await client.fetch(SOURCE, from_origin=None, to_origin=250)
        finally:
            await client.close()

    asyncio.run(run())
