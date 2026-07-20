from __future__ import annotations

import json
import sys

import pytest

from telemetry_plane.metadata_bootstrap import MetadataBootstrap, MetadataBootstrapError, load_contract
from telemetry_plane import metadata_bootstrap as bootstrap_module


def contract() -> dict:
    return {
        "service": {
            "name": "edge-telemetry-agent",
            "description": "Logical HTTPS telemetry ingestion service",
            "baseAddress": "https://edgex-ingest-gateway.edgex-system.svc:8443",
            "adminState": "UNLOCKED",
            "labels": ["https", "telemetry-agent"],
            "properties": {},
        },
        "profiles": [{
            "apiVersion": "v3",
            "name": "etri-sensehat",
            "manufacturer": "Raspberry Pi",
            "model": "Sense HAT",
            "labels": ["i2c", "sensehat"],
            "deviceResources": [{
                "name": "humidity",
                "isHidden": False,
                "properties": {"valueType": "Float64", "readWrite": "R"},
            }],
            "deviceCommands": [],
        }],
        "devices": [{
            "name": "sensehat-001",
            "description": "Sense HAT attached to Raspberry Pi",
            "adminState": "UNLOCKED",
            "operatingState": "UNKNOWN",
            "serviceName": "edge-telemetry-agent",
            "profileName": "etri-sensehat",
            "labels": ["i2c", "sensehat"],
            "protocols": {"i2c": {"Bus": "1", "Adapter": "edge-telemetry-agent"}},
            "properties": {},
        }],
    }


class Response:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class MetadataClient:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.calls = []
        self.closed = False

    def get(self, url):
        self.calls.append(("GET", url, None))
        segments = url.rsplit("/", 3)
        kind, name = segments[-3], segments[-1]
        key = (kind, name)
        if key not in self.existing:
            return Response(404, {"statusCode": 404})
        response_key = {"deviceservice": "service", "deviceprofile": "profile", "device": "device"}[kind]
        return Response(200, {response_key: {"name": name}})

    def post(self, url, json):
        self.calls.append(("POST", url, json))
        kind = url.rsplit("/", 1)[-1]
        response_key = {"deviceservice": "service", "deviceprofile": "profile", "device": "device"}[kind]
        self.existing.add((kind, json[0][response_key]["name"]))
        return Response(207, [{"statusCode": 201, "id": f"{kind}-id"}])

    def close(self):
        self.closed = True


def test_bootstrap_creates_missing_metadata_in_dependency_order() -> None:
    client = MetadataClient()
    bootstrap = MetadataBootstrap("http://edgex-core-metadata:59881", contract(), client=client)

    created = bootstrap.run()

    assert created == [
        "deviceservice/edge-telemetry-agent",
        "deviceprofile/etri-sensehat",
        "device/sensehat-001",
    ]
    posts = [call for call in client.calls if call[0] == "POST"]
    assert [call[1] for call in posts] == [
        "http://edgex-core-metadata:59881/api/v3/deviceservice",
        "http://edgex-core-metadata:59881/api/v3/deviceprofile",
        "http://edgex-core-metadata:59881/api/v3/device",
    ]
    assert all(call[2][0]["apiVersion"] == "v3" for call in posts)
    assert all(call[2][0]["requestId"] for call in posts)
    bootstrap.close()
    assert client.closed


def test_bootstrap_is_idempotent_when_named_objects_exist() -> None:
    client = MetadataClient({
        ("deviceservice", "edge-telemetry-agent"),
        ("deviceprofile", "etri-sensehat"),
        ("device", "sensehat-001"),
    })
    bootstrap = MetadataBootstrap("http://edgex-core-metadata:59881", contract(), client=client)

    assert bootstrap.run() == []
    assert not [call for call in client.calls if call[0] == "POST"]


def test_bootstrap_rejects_unconfirmed_multistatus() -> None:
    client = MetadataClient()

    def rejected(url, json):
        client.calls.append(("POST", url, json))
        return Response(207, [{"statusCode": 400, "message": "invalid"}])

    client.post = rejected
    bootstrap = MetadataBootstrap("http://edgex-core-metadata:59881", contract(), client=client)

    with pytest.raises(MetadataBootstrapError, match="status 400"):
        bootstrap.run()


def test_load_contract_requires_device_references_and_strict_json(tmp_path) -> None:
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(contract()))
    assert load_contract(path)["devices"][0]["profileName"] == "etri-sensehat"

    broken = contract()
    broken["devices"][0]["profileName"] = "missing-profile"
    path.write_text(json.dumps(broken))
    with pytest.raises(MetadataBootstrapError, match="unknown profile"):
        load_contract(path)

    path.write_text("{not json}")
    with pytest.raises(MetadataBootstrapError, match="valid JSON"):
        load_contract(path)


def test_cli_scopes_contract_validation_responder_around_bootstrap(
    monkeypatch, tmp_path, capsys
) -> None:
    contract_path = tmp_path / "metadata.json"
    contract_path.write_text(json.dumps(contract()))
    calls: list[object] = []

    class Responder:
        def __init__(self, host, port, service_name, devices):
            calls.append(("responder-init", host, port, service_name, devices))

        def start(self):
            calls.append("responder-start")

        def close(self):
            calls.append("responder-close")

    class Bootstrap:
        def __init__(self, metadata_url, desired):
            calls.append(("bootstrap-init", metadata_url, desired))

        def run(self):
            calls.append("bootstrap-run")
            return ["device/sensehat-001"]

        def close(self):
            calls.append("bootstrap-close")

    monkeypatch.setattr(bootstrap_module, "MetadataValidationResponder", Responder)
    monkeypatch.setattr(bootstrap_module, "MetadataBootstrap", Bootstrap)
    monkeypatch.setattr(sys, "argv", [
        "metadata-bootstrap",
        "--metadata-url", "http://edgex-core-metadata:59881",
        "--contract", str(contract_path),
        "--messagebus-host", "edgex-messagebus",
        "--messagebus-port", "1883",
    ])

    bootstrap_module.main()

    assert calls[0][:4] == (
        "responder-init", "edgex-messagebus", 1883, "edge-telemetry-agent"
    )
    assert calls[0][4] == contract()["devices"]
    assert calls[1][0] == "bootstrap-init"
    assert calls[2:] == [
        "responder-start",
        "bootstrap-run",
        "bootstrap-close",
        "responder-close",
    ]
    assert capsys.readouterr().out == "created device/sensehat-001\n"
