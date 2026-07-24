import json

import httpx

from app.edgex import EdgeXProbeError, EdgeXRegistrationClient


class FakeEdgeXAPI:
    def __init__(self):
        self.profile = None
        self.device = None
        self.events = []

    def metadata(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith(
            "/api/v3/deviceprofile/name/"
        ):
            if self.profile is None:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={"statusCode": 200, "profile": self.profile},
            )
        if request.method == "POST" and path == "/api/v3/deviceprofile":
            self.profile = request.read()
            request_body = json.loads(self.profile)[0]
            assert request_body["requestId"]
            body = request_body["profile"]
            self.profile = body
            return httpx.Response(
                207,
                json=[
                    {
                        "apiVersion": "v3",
                        "statusCode": 201,
                        "id": "profile-id",
                    }
                ],
            )
        if request.method == "GET" and path.startswith("/api/v3/device/name/"):
            if self.device is None:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={"statusCode": 200, "device": self.device},
            )
        if request.method == "POST" and path == "/api/v3/device":
            request_body = json.loads(request.read())[0]
            assert request_body["requestId"]
            self.device = request_body["device"]
            return httpx.Response(
                207,
                json=[
                    {
                        "apiVersion": "v3",
                        "statusCode": 201,
                        "id": "device-id",
                    }
                ],
            )
        return httpx.Response(404)

    def data(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"statusCode": 200, "events": list(self.events)},
        )


def profile():
    return {
        "name": "arduino-multisensor-v1",
        "manufacturer": "Arduino",
        "model": "v1",
        "deviceResources": [],
        "deviceCommands": [],
    }


def device():
    return {
        "name": "arduino-001",
        "serviceName": "device-serial",
        "profileName": "arduino-multisensor-v1",
        "adminState": "UNLOCKED",
        "protocols": {"serial": {"Port": "/dev/arduino-001"}},
        "tags": {"controllerCandidateId": "candidate-1"},
    }


def test_metadata_registration_is_idempotent_and_event_is_separate_gate():
    fake = FakeEdgeXAPI()
    client = EdgeXRegistrationClient(
        "http://metadata",
        "http://data",
        metadata_transport=httpx.MockTransport(fake.metadata),
        data_transport=httpx.MockTransport(fake.data),
    )

    assert client.ensure_profile(profile()) is True
    assert client.ensure_profile(profile()) is False
    assert client.ensure_device(device()) is True
    assert client.ensure_device(device()) is False
    assert client.first_event_received("arduino-001") is False
    fake.events.append({"deviceName": "arduino-001", "origin": 101})
    assert client.first_event_received("arduino-001") is True
    assert client.first_event_received(
        "arduino-001",
        not_before_ns=102,
    ) is False
    assert client.first_event_received(
        "arduino-001",
        not_before_ns=101,
    ) is True


def test_existing_different_profile_is_rejected():
    fake = FakeEdgeXAPI()
    fake.profile = {**profile(), "model": "different"}
    client = EdgeXRegistrationClient(
        "http://metadata",
        "http://data",
        metadata_transport=httpx.MockTransport(fake.metadata),
        data_transport=httpx.MockTransport(fake.data),
    )

    try:
        client.ensure_profile(profile())
    except EdgeXProbeError as exc:
        assert "differs" in str(exc)
    else:
        raise AssertionError("mismatched existing profile was accepted")


def test_core_data_not_found_means_event_is_not_yet_received():
    client = EdgeXRegistrationClient(
        "http://metadata",
        "http://data",
        metadata_transport=httpx.MockTransport(
            lambda request: httpx.Response(404)
        ),
        data_transport=httpx.MockTransport(
            lambda request: httpx.Response(404)
        ),
    )

    assert client.first_event_received("arduino-001") is False
