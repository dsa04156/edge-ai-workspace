import asyncio
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as main

from app.service_demo import (
    ServiceDemoBackendError,
    ServiceDemoClient,
    ServiceDemoResponseError,
)


ROOT = Path(__file__).resolve().parents[1]


def live_payload() -> dict:
    return {
        "apiVersion": "v1",
        "service": "sensor-anomaly-demo",
        "mode": "live",
        "status": "normal",
        "inputState": "fresh",
        "modelState": "ready",
        "source": {
            "physicalSource": "arduino-001",
            "deviceService": "device-serial-jetson",
            "devices": [
                "virtual-acceleration-x-001",
                "virtual-acceleration-y-001",
                "virtual-acceleration-z-001",
                "virtual-temperature-001",
            ],
        },
        "latest": {
            "origin": 1_000_000_000,
            "observedAt": "2026-07-22T10:00:00Z",
            "values": {"x": 3, "y": 4, "z": 0},
            "magnitude": 5.0,
            "score": 0.25,
            "anomaly": False,
            "componentScores": {"vibration": 0.2, "temperature": 0.366667},
            "weights": {"vibration": 0.7, "temperature": 0.3},
            "vibrationFeatures": {
                "rms": 5.1,
                "peak": 6.0,
                "kurtosis": 2.8,
                "sampleCount": 20,
            },
            "temperatureFeatures": {
                "origin": 999_000_000,
                "raw": 300,
                "mean": 298.5,
                "stddev": 1.2,
                "delta": 2.0,
                "sampleCount": 10,
                "alignmentLagMs": 1.0,
            },
        },
        "model": {
            "algorithm": "weighted-multi-sensor-feature-score-v1",
            "sampleCount": 30,
            "warmupSamples": 30,
            "threshold": 4.0,
            "baselineMean": 5.0,
            "baselineStddev": 1.0,
            "stddevFloor": 1.0,
            "components": {
                "vibration": {
                    "algorithm": "online-vibration-feature-gaussian-v1",
                    "sampleCount": 30,
                    "warmupSamples": 30,
                    "threshold": 4.0,
                    "featureMeans": {"rms": 5.0},
                    "featureStddevs": {"rms": 1.0},
                    "stddevFloors": {"rms": 1.0},
                },
                "temperature": {
                    "algorithm": "online-temperature-feature-gaussian-v1",
                    "sampleCount": 30,
                    "warmupSamples": 30,
                    "threshold": 4.0,
                    "featureMeans": {"mean": 298.0},
                    "featureStddevs": {"mean": 1.0},
                    "stddevFloors": {"mean": 1.0},
                },
            },
            "weights": {"vibration": 0.7, "temperature": 0.3},
        },
        "counters": {
            "framesProcessed": 30,
            "duplicatesIgnored": 0,
            "incompleteFramesDropped": 0,
            "inputErrors": 0,
            "contextSamplesProcessed": 30,
            "unalignedFramesDropped": 0,
        },
        "lastError": None,
    }


def test_client_normalizes_live_upstream_into_consumer_binding() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/status"
        return httpx.Response(200, json=live_payload())

    client = ServiceDemoClient(
        "http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
    )
    state = asyncio.run(client.get_state())

    assert state.mode == "live"
    assert state.status == "normal"
    assert state.binding.physical_source == "arduino-001"
    assert state.binding.device_service == "device-serial-jetson"
    assert state.binding.consumer == "sensor-anomaly-demo"
    assert state.binding.node == "etri-dev0001-jetorn"
    assert state.latest is not None and state.latest.origin == 1_000_000_000
    assert state.latest.component_scores is not None
    assert state.latest.component_scores.vibration == 0.2
    assert state.latest.temperature_features is not None
    assert state.latest.temperature_features.raw == 300
    assert state.model is not None
    assert state.model.algorithm == "weighted-multi-sensor-feature-score-v1"
    assert set(state.model.components) == {"vibration", "temperature"}
    assert state.counters.context_samples_processed == 30
    assert state.observation_error is None


@pytest.mark.parametrize("failure", ["connect", "status"])
def test_client_normalizes_transport_and_http_failures(failure: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("demo unavailable", request=request)
        return httpx.Response(503, json={"message": "unavailable"})

    client = ServiceDemoClient(
        "http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ServiceDemoBackendError):
        asyncio.run(client.get_state())


def test_client_rejects_invalid_json_and_schema() -> None:
    responses = [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={**live_payload(), "mode": "fixture"}),
    ]

    async def handler(_: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    client = ServiceDemoClient(
        "http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ServiceDemoResponseError):
        asyncio.run(client.get_state())
    with pytest.raises(ServiceDemoResponseError):
        asyncio.run(client.get_state())


def test_service_demo_route_returns_degraded_snapshot_on_upstream_failure(
    monkeypatch,
) -> None:
    class FailingClient:
        async def get_state(self):
            raise ServiceDemoBackendError("request failed")

    monkeypatch.setattr(main, "service_demo_client", FailingClient(), raising=False)

    with TestClient(main.app) as client:
        response = client.get("/state/service-demo")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "unavailable"
    assert payload["status"] == "degraded"
    assert payload["input_state"] == "error"
    assert payload["binding"]["consumer"] == "sensor-anomaly-demo"
    assert payload["latest"] is None
    assert payload["observation_error"] == (
        "sensor anomaly demo unavailable: ServiceDemoBackendError"
    )


def test_state_aggregator_deployment_uses_sensor_demo_service_fqdn() -> None:
    resources = [
        item
        for item in yaml.safe_load_all(
            (ROOT / "k8s/deployment.yaml").read_text(encoding="utf-8")
        )
        if item
    ]
    deployment = next(item for item in resources if item["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {
        item["name"]: item["value"]
        for item in container["env"]
        if "value" in item
    }

    assert env["SENSOR_ANOMALY_DEMO_URL"] == (
        "http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080"
    )
    assert env["SENSOR_ANOMALY_DEMO_TIMEOUT_SECONDS"] == "2"
