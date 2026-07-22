import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.edgex import (
    EdgeXBackendError,
    EdgeXClient,
    EdgeXResponseError,
    parse_edgex_origin,
)


def _response(payload, status_code=200):
    return httpx.Response(status_code, json=payload)


def _envelope(field, values):
    return {
        "apiVersion": "v3",
        "statusCode": 200,
        "totalCount": len(values),
        field: values,
    }


def _event(origin, *, event_id="event-1", readings=None):
    return {
        "id": event_id,
        "deviceName": "vib-arduino-acceleration-01",
        "profileName": "etri-vibration-mqtt",
        "sourceName": "telemetry",
        "origin": origin,
        "readings": readings
        if readings is not None
        else [
            {
                "resourceName": "acceleration_x",
                "valueType": "Float64",
                "value": "1.25",
                "origin": origin,
                "units": "g",
            }
        ],
    }


def test_inventory_parses_edgex_device_fields():
    def handler(request):
        assert request.url.path == "/api/v3/device/all"
        return _response(
            _envelope(
                "devices",
                [
                    {
                        "name": "vib-arduino-acceleration-01",
                        "description": "Acceleration canary",
                        "profileName": "etri-vibration-mqtt",
                        "serviceName": "device-mqtt",
                        "adminState": "UNLOCKED",
                        "operatingState": "UP",
                        "protocols": {"mqtt": {"Host": "mosquitto", "Port": "1883"}},
                        "tags": {},
                        "properties": {},
                    }
                ],
            )
        )

    client = EdgeXClient(
        "http://metadata", "http://data", transport=httpx.MockTransport(handler)
    )
    devices = asyncio.run(client.get_devices())

    assert len(devices) == 1
    assert devices[0].name == "vib-arduino-acceleration-01"
    assert devices[0].profile_name == "etri-vibration-mqtt"
    assert devices[0].device_service_name == "device-mqtt"
    assert devices[0].protocol_names == ["mqtt"]
    assert devices[0].admin_state == "UNLOCKED"
    assert devices[0].operating_state == "UP"


def test_inventory_maps_node_diagnostic_from_tags_then_properties():
    base = {
        "description": "",
        "profileName": "etri-vibration-mqtt",
        "serviceName": "device-mqtt",
        "adminState": "UNLOCKED",
        "operatingState": "UP",
        "protocols": {"mqtt": {}},
    }

    def handler(request):
        return _response(
            _envelope(
                "devices",
                [
                    {
                        **base,
                        "name": "tagged",
                        "tags": {"nodeName": "etri-dev0001-jetorn"},
                        "properties": {"node_name": "ignored-property-node"},
                    },
                    {
                        **base,
                        "name": "property-mapped",
                        "tags": {},
                        "properties": {
                            "placement": {"kubernetesNode": "etri-dev0002-raspi5"}
                        },
                    },
                ],
            )
        )

    client = EdgeXClient(
        "http://metadata", "http://data", transport=httpx.MockTransport(handler)
    )
    devices = asyncio.run(client.get_devices())

    assert devices[0].node_name == "etri-dev0001-jetorn"
    assert devices[1].node_name == "etri-dev0002-raspi5"


def test_latest_event_flattens_every_reading_with_typed_values():
    origin = 1_721_234_567_123_456_789
    readings = [
        {
            "resourceName": "acceleration_x",
            "valueType": "Float64",
            "value": "1.25",
            "origin": origin,
            "units": "g",
        },
        {
            "resourceName": "sample_count",
            "valueType": "Int64",
            "value": "42",
            "origin": origin + 1_000,
        },
        {
            "resourceName": "alarm",
            "valueType": "Bool",
            "value": "false",
            "origin": origin + 2_000,
        },
    ]

    def handler(request):
        assert request.url.path.endswith("/vib-arduino-acceleration-01")
        assert request.url.params["limit"] == "1"
        return _response(_envelope("events", [_event(origin, readings=readings)]))

    client = EdgeXClient(
        "http://metadata", "http://data", transport=httpx.MockTransport(handler)
    )
    points = asyncio.run(client.get_latest_event("vib-arduino-acceleration-01"))

    assert [point.resource_name for point in points] == [
        "acceleration_x",
        "sample_count",
        "alarm",
    ]
    assert [point.value for point in points] == [1.25, 42, False]
    assert all(point.source_name == "telemetry" for point in points)
    assert points[0].event_id == "event-1"
    assert points[0].origin == origin


def test_latest_source_readings_keep_newest_event_for_each_source():
    base_origin = 1_721_234_567_123_456_789

    def source_event(source_name, origin, event_id, resource_name, value):
        event = _event(
            origin,
            event_id=event_id,
            readings=[
                {
                    "resourceName": resource_name,
                    "valueType": "Int32",
                    "value": str(value),
                    "origin": origin,
                }
            ],
        )
        event["sourceName"] = source_name
        return event

    def handler(request):
        assert request.url.params["offset"] == "0"
        assert request.url.params["limit"] == "20"
        return _response(
            _envelope(
                "events",
                [
                    source_event("temperature", base_origin, "temp-new", "raw", 284),
                    source_event("temperature", base_origin - 2_000, "temp-old", "raw", 280),
                    source_event("light", base_origin - 1_000, "light-new", "value", 288),
                ],
            )
        )

    client = EdgeXClient(
        "http://metadata", "http://data", transport=httpx.MockTransport(handler)
    )
    points = asyncio.run(
        client.get_latest_source_readings("vib-arduino-acceleration-01")
    )

    assert [(point.source_name, point.value) for point in points] == [
        ("temperature", 284),
        ("light", 288),
    ]
    assert [point.event_id for point in points] == ["temp-new", "light-new"]


def test_history_filters_bounded_device_events_by_origin_before_flattening():
    before_start = 1_700_000_000_000_000_000
    start_origin = before_start + 1_000_000_000
    end_origin = start_origin + 5_000_000_000
    after_end = end_origin + 1_000_000_000

    def handler(request):
        assert request.url.params["offset"] == "5"
        assert request.url.params["limit"] == "20"
        assert "start" not in request.url.params
        assert "end" not in request.url.params
        return _response(
            _envelope(
                "events",
                [
                    _event(after_end, event_id="after-end"),
                    _event(before_start, event_id="before-start"),
                    _event(start_origin, event_id="at-start"),
                    _event(
                        end_origin,
                        event_id="at-end",
                        readings=[
                            {
                                "resourceName": "x",
                                "valueType": "Float32",
                                "value": "2.0",
                                "origin": end_origin,
                            },
                            {
                                "resourceName": "y",
                                "valueType": "Float32",
                                "value": "3.0",
                                "origin": end_origin,
                            },
                        ],
                    ),
                ],
            )
        )

    client = EdgeXClient(
        "http://metadata", "http://data", transport=httpx.MockTransport(handler)
    )
    points = asyncio.run(
        client.get_event_history(
            "vib-arduino-acceleration-01",
            offset=5,
            limit=20,
            start=start_origin,
            end=end_origin,
        )
    )

    assert [point.event_id for point in points] == ["at-end", "at-end", "at-start"]
    assert [point.resource_name for point in points] == ["x", "y", "acceleration_x"]


def test_nanosecond_origin_conversion_is_utc_without_float_rounding():
    parsed = parse_edgex_origin(1_700_000_000_123_456_789)

    assert parsed == datetime(2023, 11, 14, 22, 13, 20, 123456, tzinfo=timezone.utc)
    assert parsed.tzinfo is timezone.utc


def test_no_event_is_a_successful_empty_result():
    transport = httpx.MockTransport(
        lambda request: _response(_envelope("events", []))
    )
    client = EdgeXClient("http://metadata", "http://data", transport=transport)

    assert asyncio.run(client.get_latest_event("no-events")) == []
    assert asyncio.run(client.get_event_history("no-events")) == []


def test_malformed_response_raises_typed_response_error():
    transport = httpx.MockTransport(
        lambda request: _response(
            {"apiVersion": "v3", "statusCode": 200, "devices": {}}
        )
    )
    client = EdgeXClient("http://metadata", "http://data", transport=transport)

    with pytest.raises(EdgeXResponseError, match="devices must be a list"):
        asyncio.run(client.get_devices())


def test_backend_outage_raises_typed_backend_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = EdgeXClient(
        "http://metadata", "http://data", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(EdgeXBackendError, match="EdgeX request failed"):
        asyncio.run(client.get_devices())


def test_core_data_requests_respect_global_concurrency_limit():
    active_requests = 0
    peak_requests = 0

    async def handler(request):
        nonlocal active_requests, peak_requests
        if request.url.host != "data":
            return _response(_envelope("devices", []))
        active_requests += 1
        peak_requests = max(peak_requests, active_requests)
        await asyncio.sleep(0.01)
        active_requests -= 1
        return _response(_envelope("events", []))

    client = EdgeXClient(
        "http://metadata",
        "http://data",
        core_data_max_concurrency=1,
        transport=httpx.MockTransport(handler),
    )

    async def fetch_all():
        await asyncio.gather(
            *(client.get_latest_event(f"virtual-device-{index}") for index in range(6))
        )

    asyncio.run(fetch_all())

    assert peak_requests == 1
