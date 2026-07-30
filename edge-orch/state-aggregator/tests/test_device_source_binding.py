from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.device_source import (
    DeviceSourceBindingService,
    DeviceSourceCatalog,
    DeviceSourceNotFoundError,
    DeviceSourceUnavailableError,
    DeviceSourceUpstreamError,
)
from app.device_source_models import (
    DeviceSourceBinding,
    DeviceSourceBindingRequest,
    DeviceSourceCatalogDocument,
    DeviceSourceSample,
    DeviceSourceSampleResponse,
)
from app.main import app, device_source_binding_service
from app.models import TelemetryPoint


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "config"
    / "device_source_catalog.json"
)
ORIGIN = 1_800_000_000_000_000_000


def _device(
    *,
    name: str = "virtual-temperature-001",
    service_name: str = "device-serial-jetson",
    node_name: str = "etri-dev0001-jetorn",
) -> dict:
    return {
        "name": name,
        "profileName": "etri-arduino-temperature",
        "serviceName": service_name,
        "adminState": "UNLOCKED",
        "operatingState": "UP",
        "tags": {"nodeName": node_name},
        "properties": {},
    }


def _profile() -> dict:
    return {
        "name": "etri-arduino-temperature",
        "deviceResources": [
            {
                "name": "temperature_raw",
                "properties": {
                    "valueType": "Int32",
                    "readWrite": "R",
                    "units": "raw",
                },
            }
        ],
    }


class FakeMetadata:
    def __init__(self, device: dict | None = None, profile: dict | None = None):
        self.device = _device() if device is None else device
        self.profile = _profile() if profile is None else profile

    async def get_device(self, name: str):
        if self.device and self.device.get("name") == name:
            return self.device
        return None

    async def get_profile(self, name: str):
        if self.profile and self.profile.get("name") == name:
            return self.profile
        return None


class FakeCoreData:
    def __init__(self, points: list[TelemetryPoint] | None = None):
        self.points = points or []
        self.calls: list[dict] = []

    async def get_event_history(
        self,
        device_name: str,
        *,
        offset: int = 0,
        limit: int = 100,
        start=None,
        end=None,
    ):
        self.calls.append(
            {
                "device_name": device_name,
                "offset": offset,
                "limit": limit,
                "start": start,
                "end": end,
            }
        )
        return self.points


def _catalog() -> DeviceSourceCatalog:
    return DeviceSourceCatalog.load(CATALOG_PATH)


def _service(
    *,
    metadata: FakeMetadata | None = None,
    core_data: FakeCoreData | None = None,
    handler=None,
) -> DeviceSourceBindingService:
    transport = httpx.MockTransport(handler) if handler is not None else None
    return DeviceSourceBindingService(
        _catalog(),
        metadata or FakeMetadata(),
        core_data or FakeCoreData(),
        2,
        transport=transport,
        now_ns=lambda: ORIGIN,
    )


def _local_payload(*, value_type: str = "Int32", value=291) -> dict:
    return {
        "apiVersion": "v3",
        "statusCode": 200,
        "deviceName": "virtual-temperature-001",
        "resourceName": "temperature_raw",
        "count": 1,
        "retention": {
            "maxAge": "10m0s",
            "maxSamples": 10_000,
            "maxBytes": 67_108_864,
        },
        "samples": [
            {"origin": ORIGIN - 1_000, "valueType": value_type, "value": value}
        ],
    }


def test_catalog_exposes_only_verified_device_service_local_data_endpoints():
    catalog = _catalog()

    assert catalog.read_modes_for("device-serial-jetson") == [
        "local_latest",
        "local_window",
        "history",
    ]
    assert catalog.read_modes_for("device-sensehat-raspi") == [
        "local_latest",
        "local_window",
        "history",
    ]
    assert catalog.read_modes_for("device-modbus") == ["history"]


@pytest.mark.parametrize(
    "base_url",
    [
        "mqtt://broker.example",
        "http://user:password@service.example:59910",
        "http://service.example:59910/local",
        "http://service.example:59910?target=other",
    ],
)
def test_catalog_rejects_unsafe_local_data_base_urls(base_url: str):
    document = DeviceSourceCatalogDocument.model_validate(
        {
            "services": [
                {
                    "serviceName": "device-test",
                    "nodeName": "edge-01",
                    "baseUrl": base_url,
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="baseUrl"):
        DeviceSourceCatalog(document)


def test_local_latest_uses_allowlisted_service_and_profile_resource():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "device-serial-jetson.edgex-edge.svc.cluster.local"
        assert request.url.path.endswith(
            "/api/v3/localdata/device/name/virtual-temperature-001/"
            "resource/name/temperature_raw/latest"
        )
        assert not request.url.params
        return httpx.Response(200, json=_local_payload())

    response = asyncio.run(
        _service(handler=handler).sample(
            DeviceSourceBindingRequest(
                device_name="virtual-temperature-001",
                resource_name="temperature_raw",
                read_mode="local_latest",
                limit=1,
            )
        )
    )

    assert response.source_kind == "device_service_local_cache"
    assert response.durable is False
    assert response.preview_only is True
    assert response.retention is not None
    assert response.retention.max_age == "10m0s"
    assert response.samples[0].value == 291
    assert response.samples[0].units == "raw"


def test_local_window_converts_window_to_origin_range():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["from"] == str(ORIGIN - 10_000_000_000)
        assert request.url.params["to"] == str(ORIGIN)
        assert request.url.params["limit"] == "25"
        return httpx.Response(200, json=_local_payload())

    response = asyncio.run(
        _service(handler=handler).sample(
            DeviceSourceBindingRequest(
                device_name="virtual-temperature-001",
                resource_name="temperature_raw",
                read_mode="local_window",
                window="-10s",
                limit=25,
            )
        )
    )

    assert len(response.samples) == 1
    assert response.binding.window == "-10s"


def test_history_uses_core_data_and_filters_selected_resource():
    timestamp = datetime.fromtimestamp(ORIGIN / 1_000_000_000, tz=timezone.utc)
    core_data = FakeCoreData(
        [
            TelemetryPoint(
                device_name="virtual-temperature-001",
                source_name="temperature",
                resource_name="other",
                value_type="Int32",
                value=1,
                timestamp=timestamp,
                origin=ORIGIN - 2,
            ),
            TelemetryPoint(
                device_name="virtual-temperature-001",
                source_name="temperature",
                resource_name="temperature_raw",
                value_type="Int32",
                value=292,
                timestamp=timestamp,
                origin=ORIGIN - 1,
                event_id="event-1",
                units="raw",
            ),
        ]
    )
    response = asyncio.run(
        _service(core_data=core_data).sample(
            DeviceSourceBindingRequest(
                device_name="virtual-temperature-001",
                resource_name="temperature_raw",
                read_mode="history",
                window="-1h",
                limit=20,
            )
        )
    )

    assert response.source_kind == "edgex_core_data"
    assert response.durable is True
    assert response.retention is None
    assert [sample.value for sample in response.samples] == [292]
    assert core_data.calls[0]["device_name"] == "virtual-temperature-001"
    assert core_data.calls[0]["limit"] == 20


def test_binding_rejects_unknown_device_and_profile_resource():
    service = _service()

    with pytest.raises(DeviceSourceNotFoundError, match="device"):
        asyncio.run(
            service.sample(
                DeviceSourceBindingRequest(
                    device_name="missing-device",
                    resource_name="temperature_raw",
                )
            )
        )
    with pytest.raises(DeviceSourceNotFoundError, match="resource"):
        asyncio.run(
            service.sample(
                DeviceSourceBindingRequest(
                    device_name="virtual-temperature-001",
                    resource_name="missing_resource",
                )
            )
        )


def test_local_binding_rejects_unverified_service_and_node_mismatch():
    unverified = FakeMetadata(
        device=_device(service_name="device-modbus", node_name="edge-plc")
    )
    mismatch = FakeMetadata(device=_device(node_name="different-node"))

    with pytest.raises(DeviceSourceUnavailableError, match="no verified"):
        asyncio.run(
            _service(metadata=unverified).sample(
                DeviceSourceBindingRequest(
                    device_name="virtual-temperature-001",
                    resource_name="temperature_raw",
                )
            )
        )
    with pytest.raises(DeviceSourceUnavailableError, match="node identity"):
        asyncio.run(
            _service(metadata=mismatch).sample(
                DeviceSourceBindingRequest(
                    device_name="virtual-temperature-001",
                    resource_name="temperature_raw",
                )
            )
        )


def test_local_binding_rejects_value_type_outside_profile_contract():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_local_payload(value_type="Float64", value=291.0),
        )

    with pytest.raises(DeviceSourceUpstreamError, match="valueType"):
        asyncio.run(
            _service(handler=handler).sample(
                DeviceSourceBindingRequest(
                    device_name="virtual-temperature-001",
                    resource_name="temperature_raw",
                )
            )
        )


def test_sample_api_returns_camel_case_contract_without_token(monkeypatch):
    async def fake_sample(request: DeviceSourceBindingRequest):
        assert request.device_name == "virtual-temperature-001"
        return DeviceSourceSampleResponse(
            sampled_at=datetime.now(timezone.utc),
            source_kind="device_service_local_cache",
            durable=False,
            binding=DeviceSourceBinding(
                device_name=request.device_name,
                resource_name=request.resource_name,
                read_mode=request.read_mode,
                window=request.window,
                limit=request.limit,
                profile_name="etri-arduino-temperature",
                device_service_name="device-serial-jetson",
                node_name="etri-dev0001-jetorn",
                admin_state="UNLOCKED",
                operating_state="UP",
            ),
            samples=[
                DeviceSourceSample(
                    origin=ORIGIN,
                    timestamp=datetime.now(timezone.utc),
                    resource_name=request.resource_name,
                    value_type="Int32",
                    value=291,
                )
            ],
        )

    monkeypatch.setattr(device_source_binding_service, "sample", fake_sample)
    with TestClient(app) as client:
        response = client.post(
            "/state/device-source-bindings/sample",
            json={
                "deviceName": "virtual-temperature-001",
                "resourceName": "temperature_raw",
                "readMode": "local_latest",
                "window": "-10s",
                "limit": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["previewOnly"] is True
    assert payload["sourceKind"] == "device_service_local_cache"
    assert payload["binding"]["deviceServiceName"] == "device-serial-jetson"
    assert payload["samples"][0]["resourceName"] == "temperature_raw"


def test_sample_api_returns_structured_unavailable_error(monkeypatch):
    async def fail_sample(_: DeviceSourceBindingRequest):
        raise DeviceSourceUnavailableError("local source is not verified")

    monkeypatch.setattr(device_source_binding_service, "sample", fail_sample)
    with TestClient(app) as client:
        response = client.post(
            "/state/device-source-bindings/sample",
            json={
                "deviceName": "virtual-temperature-001",
                "resourceName": "temperature_raw",
                "readMode": "local_latest",
                "window": "-10s",
                "limit": 1,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "device_source_unavailable",
        "message": "local source is not verified",
    }


def test_deployment_configures_catalog_and_read_only_local_data_client_label():
    manifest = (
        Path(__file__).resolve().parents[1] / "k8s" / "deployment.yaml"
    ).read_text(encoding="utf-8")

    assert 'edge-ai.io/local-data-client: "true"' in manifest
    assert "DEVICE_SOURCE_CATALOG_PATH" in manifest
    assert "/app/app/config/device_source_catalog.json" in manifest
