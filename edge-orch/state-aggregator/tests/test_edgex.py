import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.edgex import (
    EdgeXBackendError,
    EdgeXClient,
    EdgeXHTTPStatusError,
    EdgeXNotFoundError,
    EdgeXResponseError,
    EdgeXTransportError,
    parse_edgex_origin,
)
from app.models import EdgeXDevice, EdgeXDeviceProfile, EdgeXDeviceResource
from app.virtual_device_bindings import VirtualDeviceBindingConfig
from app.virtual_device_resolver import resolve_virtual_device


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


def test_history_sorts_events_newest_first_and_flattens_readings():
    old_origin = 1_700_000_000_000_000_000
    new_origin = old_origin + 5_000_000_000

    def handler(request):
        assert request.url.params["offset"] == "5"
        assert request.url.params["limit"] == "20"
        assert request.url.params["start"] == str(old_origin)
        assert request.url.params["end"] == str(new_origin)
        return _response(
            _envelope(
                "events",
                [
                    _event(old_origin, event_id="old"),
                    _event(
                        new_origin,
                        event_id="new",
                        readings=[
                            {
                                "resourceName": "x",
                                "valueType": "Float32",
                                "value": "2.0",
                                "origin": new_origin,
                            },
                            {
                                "resourceName": "y",
                                "valueType": "Float32",
                                "value": "3.0",
                                "origin": new_origin,
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
            start=old_origin,
            end=new_origin,
        )
    )

    assert [point.event_id for point in points] == ["new", "new", "old"]
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
def test_profile_lookup_parses_resources_and_preserves_operation_identity():
    def handler(request):
        assert request.url.raw_path == b"/api/v3/deviceprofile/name/profile%20one"
        return _response(
            {
                "apiVersion": "v3",
                "statusCode": 200,
                "profile": {
                    "name": "profile one",
                    "deviceResources": [{"name": "acceleration_x"}],
                },
            }
        )

    client = EdgeXClient("http://metadata", "http://data", transport=httpx.MockTransport(handler))
    profile = asyncio.run(client.get_device_profile("profile one"))

    assert profile.name == "profile one"
    assert [resource.name for resource in profile.device_resources] == ["acceleration_x"]


def test_profile_lookup_rejects_a_different_returned_identity():
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "profile": {
                        "name": "different-profile",
                        "deviceResources": [],
                    },
                }
            )
        ),
    )

    with pytest.raises(EdgeXResponseError) as raised:
        asyncio.run(client.get_device_profile("requested-profile"))

    assert raised.value.operation == "profile"
    assert raised.value.identity == "requested-profile"


def test_profile_resource_parse_error_keeps_profile_operation_context():
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "profile": {
                        "name": "profile",
                        "deviceResources": [{"name": 7}],
                    },
                }
            )
        ),
    )

    with pytest.raises(EdgeXResponseError) as raised:
        asyncio.run(client.get_device_profile("profile"))

    assert raised.value.operation == "profile"
    assert raised.value.identity == "profile"


@pytest.mark.parametrize(
    ("status_code", "error_type", "retryable"),
    [
        (404, EdgeXNotFoundError, False),
        (403, EdgeXHTTPStatusError, False),
        (503, EdgeXHTTPStatusError, True),
    ],
)
def test_http_failures_are_status_aware(status_code, error_type, retryable):
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(lambda request: _response({}, status_code)),
    )

    with pytest.raises(error_type) as raised:
        asyncio.run(client.get_device_profile("profile"))

    assert raised.value.operation == "profile"
    assert raised.value.identity == "profile"
    assert raised.value.status_code == status_code
    assert raised.value.retryable is retryable


def test_transport_and_malformed_failures_keep_operation_context():
    transport_client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("down", request=request))
        ),
    )
    malformed_client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(lambda request: _response({"apiVersion": "v3"})),
    )

    with pytest.raises(EdgeXTransportError) as transport_error:
        asyncio.run(transport_client.get_event_history("device"))
    with pytest.raises(EdgeXResponseError) as malformed_error:
        asyncio.run(malformed_client.get_devices())

    assert transport_error.value.operation == "events"
    assert transport_error.value.identity == "device"
    assert transport_error.value.retryable is True
    assert malformed_error.value.operation == "inventory"


def test_bounded_history_reads_later_pages_orders_ties_and_marks_truncation():
    origin = 1_700_000_000_000_000_000
    pages = {
        0: [_event(origin, event_id="z"), _event(origin, event_id="a")],
        2: [_event(origin - 1, event_id="later")],
    }
    requests = []

    def handler(request):
        offset = int(request.url.params["offset"])
        requests.append((offset, request.url.params["end"]))
        events = (
            [_event(origin - 1, event_id="later")]
            if request.url.params["end"] != str(origin)
            else pages.get(offset, [])
        )
        return _response(
            {
                "apiVersion": "v3",
                "statusCode": 200,
                "totalCount": 3,
                "events": events,
            }
        )

    client = EdgeXClient("http://metadata", "http://data", transport=httpx.MockTransport(handler))
    history = asyncio.run(
        client.get_bounded_event_history(
            "device",
            observation_time=origin,
            freshness_seconds=90,
            page_size=2,
            max_pages=1,
            max_events_per_device=2,
            max_prior_probe_events_per_device=1,
        )
    )

    assert requests == [(0, str(origin))]
    assert [point.event_id for point in history.events] == ["a", "z"]
    assert history.events_scanned == 2
    assert history.pages_scanned == 1
    assert history.history_truncated is True
    assert history.prior_probe_events == []

def test_bounded_history_later_page_match_resolves_without_false_absence():
    origin = 1_700_000_000_000_000_000
    unrelated = _event(origin, event_id="unrelated")
    unrelated["sourceName"] = "other"
    matching = _event(origin - 1, event_id="required-match")
    pages = {0: [unrelated], 1: [matching]}
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return _response(
            {
                "apiVersion": "v3",
                "statusCode": 200,
                "totalCount": 2,
                "events": pages.get(offset, []),
            }
        )

    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(handler),
    )
    observation_time = datetime.fromtimestamp(origin / 1_000_000_000, timezone.utc)
    history = asyncio.run(
        client.get_bounded_event_history(
            "vib-arduino-acceleration-01",
            observation_time=observation_time,
            freshness_seconds=90,
            page_size=1,
            max_pages=2,
            max_events_per_device=2,
            max_prior_probe_events_per_device=1,
        )
    )
    instance = VirtualDeviceBindingConfig.model_validate(
        {
            "apiVersion": "virtual-device-binding/v1",
            "instances": [
                {
                    "id": "virtual-acceleration",
                    "physicalDeviceRef": {
                        "name": "vib-arduino-acceleration-01",
                        "expectedProfileName": "etri-vibration-mqtt",
                    },
                    "capabilities": [
                        {
                            "id": "vibration",
                            "freshnessSeconds": 90,
                            "inputs": [
                                {
                                    "inputId": "acceleration-x",
                                    "capabilityField": "acceleration_x",
                                    "required": True,
                                    "bindings": [
                                        {
                                            "sourceName": "telemetry",
                                            "resourceName": "acceleration_x",
                                        }
                                    ],
                                    "acceptedValueTypes": ["Float64"],
                                    "acceptedUnits": ["g"],
                                }
                            ],
                        }
                    ],
                    "aiServiceRef": {
                        "serviceId": "pump-anomaly-v1",
                        "inputContract": "pump-anomaly-input/v1",
                        "bindingMode": "declarative_read_only",
                        "inputFieldMap": [
                            {
                                "inputId": "acceleration-x",
                                "aiField": "accel_x",
                            }
                        ],
                    },
                }
            ],
        }
    ).instances[0]

    view = resolve_virtual_device(
        instance,
        config_revision="revision",
        observation_time=observation_time,
        device=EdgeXDevice(
            name="vib-arduino-acceleration-01",
            profile_name="etri-vibration-mqtt",
            device_service_name="device-virtual",
            admin_state="UNLOCKED",
            operating_state="UP",
        ),
        profile=EdgeXDeviceProfile(
            name="etri-vibration-mqtt",
            device_resources=[
                EdgeXDeviceResource(name="acceleration_x"),
            ],
        ),
        history=history,
    )

    assert offsets == [0, 1]
    assert history.pages_scanned == 2
    assert history.events_scanned == 2
    assert history.history_truncated is False
    assert view.binding_status == "ready"
    assert (
        view.capabilities[0].inputs[0].original_event_ref.event_id
        == "required-match"
    )


def test_flattened_points_keep_complete_event_and_reading_provenance():
    event_origin = 1_700_000_000_000_000_000
    reading_origin = event_origin + 7
    event = _event(
        event_origin,
        event_id="complete-provenance",
        readings=[
            {
                "resourceName": "acceleration_x",
                "valueType": "Float64",
                "value": "1.25",
                "origin": reading_origin,
                "units": "g",
            }
        ],
    )
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(lambda request: _response(_envelope("events", [event]))),
    )

    point = asyncio.run(client.get_latest_event("vib-arduino-acceleration-01"))[0]

    assert point.event_id == "complete-provenance"
    assert point.event_origin == event_origin
    assert point.reading_origin == reading_origin
    assert point.profile_name == "etri-vibration-mqtt"
    assert point.device_name == "vib-arduino-acceleration-01"
    assert point.source_name == "telemetry"
    assert point.resource_name == "acceleration_x"
def test_bounded_history_rejects_query_budget_above_hard_caps():
    client = EdgeXClient("http://metadata", "http://data")

    with pytest.raises(ValueError, match="hard bounds"):
        asyncio.run(
            client.get_bounded_event_history(
                "device",
                observation_time=1_700_000_000_000_000_000,
                freshness_seconds=90,
                page_size=101,
                max_pages=1,
                max_events_per_device=1,
                max_prior_probe_events_per_device=1,
            )
        )


def test_bounded_history_preserves_incomplete_provenance_for_resolver():
    origin = 1_700_000_000_000_000_000
    incomplete = {
        "apiVersion": "v3",
        "origin": origin,
        "readings": [
            {
                "valueType": "Float64",
                "value": "1.0",
                "origin": origin,
                "units": "g",
            }
        ],
    }
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "totalCount": 1,
                    "events": [incomplete],
                }
            )
        ),
    )

    history = asyncio.run(
        client.get_bounded_event_history(
            "device",
            observation_time=origin,
            freshness_seconds=90,
            page_size=10,
            max_pages=1,
            max_events_per_device=10,
            max_prior_probe_events_per_device=1,
        )
    )

    assert len(history.events) == 1
    point = history.events[0]
    assert point.event_id is None
    assert point.device_name == ""
    assert point.profile_name == ""
    assert point.source_name == ""
    assert point.resource_name == ""


def test_bounded_history_degrades_invalid_provenance_instead_of_failing_authority():
    invalid = {
        "apiVersion": "v3",
        "id": {"invalid": True},
        "deviceName": 7,
        "profileName": [],
        "sourceName": {},
        "origin": "not-an-origin",
        "readings": [
            {
                "resourceName": 9,
                "valueType": "Float64",
                "value": "1.0",
                "origin": "also-invalid",
                "units": "g",
            }
        ],
    }
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "totalCount": 1,
                    "events": [invalid],
                }
            )
        ),
    )

    history = asyncio.run(
        client.get_bounded_event_history(
            "device",
            observation_time=1_700_000_000_000_000_000,
            freshness_seconds=90,
            page_size=10,
            max_pages=1,
            max_events_per_device=10,
            max_prior_probe_events_per_device=1,
        )
    )

    point = history.events[0]
    assert point.event_id is None
    assert point.event_origin is None
    assert point.reading_origin is None
    assert point.device_name == ""
    assert point.profile_name == ""
    assert point.source_name == ""
    assert point.resource_name == ""


def test_bounded_history_marks_page_count_inconsistency():
    origin = 1_700_000_000_000_000_000
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "totalCount": 0,
                    "events": [_event(origin, event_id="unexpected")],
                }
            )
        ),
    )

    history = asyncio.run(
        client.get_bounded_event_history(
            "device",
            observation_time=origin,
            freshness_seconds=90,
            page_size=10,
            max_pages=1,
            max_events_per_device=10,
            max_prior_probe_events_per_device=1,
        )
    )

    assert history.history_truncated is True


@pytest.mark.parametrize(
    ("total_count", "expected_truncated"),
    [(2, False), (3, True), (0, True)],
)
def test_prior_probe_uses_authoritative_total_count(
    total_count, expected_truncated
):
    origin = 1_700_000_000_000_000_000
    events = [
        _event(origin - index, event_id=f"prior-{index}")
        for index in range(2)
    ]
    client = EdgeXClient(
        "http://metadata",
        "http://data",
        transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "totalCount": total_count,
                    "events": events,
                }
            )
        ),
    )

    history = asyncio.run(
        client.get_prior_event_history(
            "device",
            before=origin,
            limit=2,
        )
    )

    assert history.events_scanned == 2
    assert history.history_truncated is expected_truncated
