import json

import httpx

import pytest

from app.edgex import EdgeXProbeError, EdgeXServiceProbe


def response(payload, status_code=200):
    return httpx.Response(
        status_code,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


def test_probe_requires_matching_unlocked_edgex_service():
    probe = EdgeXServiceProbe(
        "http://metadata",
        transport=httpx.MockTransport(
            lambda request: response(
                {
                    "apiVersion": "v3",
                    "statusCode": 200,
                    "service": {
                        "name": "device-serial-02",
                        "adminState": "UNLOCKED",
                    },
                }
            )
        ),
    )

    assert probe.service_ready("device-serial-02") is True


def test_probe_treats_missing_locked_or_invalid_backend_as_not_ready():
    payloads = [
        response({}, 404),
        response(
            {
                "apiVersion": "v3",
                "statusCode": 200,
                "service": {
                    "name": "device-serial-02",
                    "adminState": "LOCKED",
                },
            }
        ),
        httpx.Response(200, content=b"not-json"),
    ]
    for payload in payloads:
        probe = EdgeXServiceProbe(
            "http://metadata",
            transport=httpx.MockTransport(lambda request, item=payload: item),
        )
        assert probe.service_ready("device-serial-02") is False


def test_consumer_count_fails_closed_when_metadata_is_unavailable():
    failures = [
        httpx.Response(503, content=b"unavailable"),
        httpx.Response(200, content=b"not-json"),
    ]
    for failure in failures:
        probe = EdgeXServiceProbe(
            "http://metadata",
            transport=httpx.MockTransport(
                lambda request, item=failure: item
            ),
        )
        with pytest.raises(EdgeXProbeError):
            probe.consumer_count("device-serial-02")


def test_consumer_count_treats_only_explicit_not_found_as_zero():
    probe = EdgeXServiceProbe(
        "http://metadata",
        transport=httpx.MockTransport(
            lambda request: response({}, 404)
        ),
    )

    assert probe.consumer_count("device-serial-02") == 0
