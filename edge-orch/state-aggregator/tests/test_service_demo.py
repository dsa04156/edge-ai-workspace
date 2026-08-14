import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import yaml
from app import main
from app.config import Settings
from app.models import NodeState
from app.service_demo import (
    ServiceDemoBackendError,
    ServiceDemoClient,
    ServiceDemoResponseError,
)
from app.augmentation_crds import AugmentationResourceCrd, AugmentationResourceCrdState
from app.service_augmentation import ServiceAugmentationEvaluator
from fastapi.testclient import TestClient

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
            "modelVersion": "baseline-1.0.0",
            "inputContract": "okdong.pump-motor.telemetry/v1",
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
            "version": "baseline-1.0.0",
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
        "performance": {
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "windowSeconds": 300,
            "processingLatencyP95Ms": 20,
            "backlog": 0,
            "throughputPerSecond": 2,
            "sampleCount": 30,
            "metricsValid": True,
        },
        "inferenceRouting": {
            "configuredMode": "approved",
            "state": "remote",
            "effectiveTarget": "server1",
            "approvalId": "approval-001",
            "consecutiveFailures": 0,
            "rollbackRemainingSeconds": 0,
            "lastError": None,
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
    assert state.latest.model_version == "baseline-1.0.0"
    assert state.latest.input_contract == "okdong.pump-motor.telemetry/v1"
    assert state.latest.component_scores is not None
    assert state.latest.component_scores.vibration == 0.2
    assert state.latest.temperature_features is not None
    assert state.latest.temperature_features.raw == 300
    assert state.model is not None
    assert state.model.algorithm == "weighted-multi-sensor-feature-score-v1"
    assert state.model.version == "baseline-1.0.0"
    assert set(state.model.components) == {"vibration", "temperature"}
    assert state.counters.context_samples_processed == 30
    assert state.performance is not None
    assert state.performance.processing_latency_p95_ms == 20
    assert state.inference_routing.effective_target == "server1"
    assert state.inference_routing.approval_id == "approval-001"
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


def test_client_reads_persisted_results_and_alert_history() -> None:
    payload = live_payload()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/results":
            assert request.url.params["limit"] == "5"
            assert request.url.params["anomaly"] == "true"
            return httpx.Response(
                200,
                json={
                    "apiVersion": "v1",
                    "count": 1,
                    "results": [payload["latest"]],
                },
            )
        if request.url.path == "/api/v1/alerts":
            assert request.url.params["limit"] == "5"
            return httpx.Response(
                200,
                json={
                    "apiVersion": "v1",
                    "count": 1,
                    "alerts": [
                        {
                            "alertId": "pump-anomaly-001",
                            "transition": "opened",
                            "status": "open",
                            "origin": 1_000_000_000,
                            "observedAt": "2026-08-03T10:00:00Z",
                            "assetId": "arduino-001",
                            "score": 5.2,
                            "modelVersion": "baseline-1.0.0",
                            "message": "이상 상태 전환",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = ServiceDemoClient(
        "http://sensor-anomaly-demo.test",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )

    results = asyncio.run(client.get_results(limit=5, anomaly=True))
    alerts = asyncio.run(client.get_alerts(limit=5))

    assert results.mode == "live"
    assert results.count == 1
    assert results.results[0].model_version == "baseline-1.0.0"
    assert alerts.mode == "live"
    assert alerts.alerts[0].alert_id == "pump-anomaly-001"
    assert alerts.alerts[0].status == "open"


def test_service_demo_route_returns_degraded_snapshot_on_upstream_failure(
    monkeypatch,
) -> None:
    class FailingClient:
        async def get_state(self):
            raise ServiceDemoBackendError("request failed")

    monkeypatch.setattr(main, "service_demo_client", FailingClient(), raising=False)

    with TestClient(main.app) as client:
        response = client.get("/state/service-demo")
        services_response = client.get("/state/services")

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
    assert services_response.status_code == 200
    service = services_response.json()["services"][0]
    assert service["service_id"] == "sensor-anomaly-demo"
    assert service["status"] == "degraded"
    assert service["mode"] == "unavailable"
    assert service["design_contract"]["contract_id"] == "sensor-anomaly-demo-v1"


def test_service_inventory_lists_current_deployed_service(monkeypatch) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=live_payload())

    observed = asyncio.run(
        ServiceDemoClient(
            "http://sensor-anomaly-demo.test",
            timeout_seconds=2,
            transport=httpx.MockTransport(handler),
        ).get_state()
    )

    class StaticClient:
        async def get_state(self):
            return observed

    monkeypatch.setattr(main, "service_demo_client", StaticClient(), raising=False)

    with TestClient(main.app) as client:
        response = client.get("/state/services")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["services"]) == 1
    service = payload["services"][0]
    assert service["display_name"] == "펌프·모터 진동·온도 이상감지"
    assert service["lifecycle"] == "deployed"
    assert service["execution_mode"] == "fixed"
    assert service["status"] == "normal"
    assert service["node"] == "etri-dev0001-jetorn"
    assert len(service["input_devices"]) == 4
    assert service["model_version"] == "baseline-1.0.0"
    assert service["latest_observed_at"] == "2026-07-22T10:00:00Z"
    assert service["inference_target"] == "edge-local"
    assert service["catalog_version"] == "edgeai.etri/service-catalog/v1"
    assert service["definition_source"] == "git:service_catalog.json"
    assert service["descriptor"]["input_contract"]["authority"] == "EdgeX"
    assert service["descriptor"]["graph"]["topology"] == "linear-inference-split-v1"
    assert service["design_contract"] == {
        "contract_id": "sensor-anomaly-demo-v1",
        "source_mode": "local_recent",
        "pipeline_algorithm": "weighted-multi-sensor-feature-score-v1",
        "vibration_algorithm": "online-vibration-feature-gaussian-v1",
        "temperature_algorithm": "online-temperature-feature-gaussian-v1",
        "vibration_window_samples": 20,
        "temperature_window_samples": 10,
        "warmup_samples": 30,
        "threshold": 4.0,
        "vibration_weight": 0.7,
        "temperature_weight": 0.3,
        "inputs": [
            {
                "stage_id": "sensor-x",
                "device_name": "virtual-acceleration-x-001",
                "resource_name": "acceleration_x_raw",
            },
            {
                "stage_id": "sensor-y",
                "device_name": "virtual-acceleration-y-001",
                "resource_name": "acceleration_y_raw",
            },
            {
                "stage_id": "sensor-z",
                "device_name": "virtual-acceleration-z-001",
                "resource_name": "acceleration_z_raw",
            },
            {
                "stage_id": "sensor-context",
                "device_name": "virtual-temperature-001",
                "resource_name": "temperature_raw",
            },
        ],
    }


def test_result_and_alert_routes_isolate_upstream_failure(monkeypatch) -> None:
    class FailingClient:
        async def get_results(self, **_):
            raise ServiceDemoBackendError("request failed")

        async def get_alerts(self, **_):
            raise ServiceDemoBackendError("request failed")

    monkeypatch.setattr(main, "service_demo_client", FailingClient(), raising=False)

    with TestClient(main.app) as client:
        results = client.get("/state/service-demo/results?limit=5")
        alerts = client.get("/state/service-demo/alerts?limit=5")

    assert results.status_code == 200
    assert results.json()["mode"] == "unavailable"
    assert results.json()["results"] == []
    assert alerts.status_code == 200
    assert alerts.json()["mode"] == "unavailable"
    assert alerts.json()["alerts"] == []


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
    env = {item["name"]: item["value"] for item in container["env"] if "value" in item}

    assert env["SENSOR_ANOMALY_DEMO_URL"] == (
        "http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080"
    )
    assert env["SENSOR_ANOMALY_DEMO_TIMEOUT_SECONDS"] == "10"


def test_sensor_demo_observation_timeout_covers_the_edge_round_trip(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SENSOR_ANOMALY_DEMO_TIMEOUT_SECONDS", raising=False)

    assert Settings().sensor_anomaly_demo_timeout_seconds == 10.0


def test_service_augmentation_route_combines_service_resource_and_server1_gates(
    monkeypatch,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=live_payload())

    observed = asyncio.run(
        ServiceDemoClient(
            "http://sensor-anomaly-demo.test",
            timeout_seconds=2,
            transport=httpx.MockTransport(handler),
        ).get_state()
    )

    class StaticClient:
        async def get_state(self):
            return observed

    async def resource_profiles(refresh: bool = False):
        return {
            "service_resource_profiles": [
                {
                    "service": "sensor-anomaly-demo",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "resource_requirements": {
                        "limits": {"cpu_cores": 1, "memory_mib": 1024}
                    },
                    "current_usage": {
                        "cpu_cores": 0.3,
                        "memory_working_set_mib": 256,
                        "usage_coverage_ratio": 1,
                    },
                }
            ]
        }

    async def resources():
        return AugmentationResourceCrdState(
            generated_at=datetime.now(timezone.utc),
            resources=[
                AugmentationResourceCrd(
                    name="server1-sensor-anomaly-inference",
                    display_name="server1 sensor anomaly inference",
                    resource_type="gpu-inference",
                    node="etri-ser0001-cg0msb",
                    capabilities=["gpu_inference", "anomaly_model"],
                    phase="Available",
                    observed_instances=1,
                    free_instances=1,
                    binding_state="available",
                    endpoint_ready=True,
                )
            ],
        )

    monkeypatch.setattr(main, "service_demo_client", StaticClient(), raising=False)
    monkeypatch.setattr(main.service, "get_resource_profile_state", resource_profiles)
    monkeypatch.setattr(main.augmentation_crds, "get_augmentation_resources", resources)
    monkeypatch.setattr(
        main,
        "service_augmentation_evaluator",
        ServiceAugmentationEvaluator(),
    )

    with TestClient(main.app) as client:
        response = client.get("/state/service-demo/augmentation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "sensor-anomaly-demo"
    assert payload["mode"] == "observed-only"
    assert payload["state"] == "NORMAL"
    assert payload["anomaly_signal_used"] is False
    assert all(gate["passed"] for gate in payload["gates"])


def test_service_augmentation_route_uses_fresh_prometheus_node_metrics_when_cadvisor_is_missing(
    monkeypatch,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=live_payload())

    observed = asyncio.run(
        ServiceDemoClient(
            "http://sensor-anomaly-demo.test",
            timeout_seconds=2,
            transport=httpx.MockTransport(handler),
        ).get_state()
    )

    class StaticClient:
        async def get_state(self):
            return observed

    async def resource_profiles(refresh: bool = False):
        return {
            "service_resource_profiles": [
                {
                    "service": "sensor-anomaly-demo",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "resource_requirements": {
                        "limits": {"cpu_cores": 0.25, "memory_mib": 128}
                    },
                    "current_usage": {
                        "cpu_cores": 0,
                        "memory_working_set_mib": 0,
                        "usage_coverage_ratio": 0,
                    },
                }
            ]
        }

    async def resources():
        return AugmentationResourceCrdState(
            generated_at=datetime.now(timezone.utc),
            resources=[
                AugmentationResourceCrd(
                    name="server1-sensor-anomaly-inference",
                    display_name="server1 sensor anomaly inference",
                    resource_type="gpu-inference",
                    node="etri-ser0001-cg0msb",
                    capabilities=["gpu_inference", "anomaly_model"],
                    phase="Available",
                    observed_instances=1,
                    free_instances=1,
                    binding_state="available",
                    endpoint_ready=True,
                )
            ],
        )

    node = NodeState(
        hostname="etri-dev0001-jetorn",
        instance="192.168.0.3:9100",
        node_type="edge_ai_device",
        collected_at=datetime.now(timezone.utc),
        raw_metrics={
            "up": 1.0,
            "cpu_utilization": 0.9,
            "memory_usage_ratio": 0.5,
        },
        compute_pressure="high",
        memory_pressure="low",
        network_pressure="low",
        node_health="degraded",
    )

    monkeypatch.setattr(main, "service_demo_client", StaticClient(), raising=False)
    monkeypatch.setattr(main.service, "get_resource_profile_state", resource_profiles)
    monkeypatch.setattr(main.service, "get_nodes", lambda: [node])
    monkeypatch.setattr(main.augmentation_crds, "get_augmentation_resources", resources)
    monkeypatch.setattr(
        main,
        "service_augmentation_evaluator",
        ServiceAugmentationEvaluator(),
    )

    with TestClient(main.app) as client:
        response = client.get("/state/service-demo/augmentation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "OBSERVING"
    assert payload["reason_codes"] == ["resource_pressure_observing"]
    assert payload["metrics"]["cpu_percent"] == 90
    assert payload["metrics"]["memory_percent"] == 50
    assert payload["metrics"]["resource_metric_source"] == "prometheus-node"
    assert payload["metrics"]["service_metric_source"] == "service-api"
    assert next(gate for gate in payload["gates"] if gate["id"] == "metrics")[
        "passed"
    ] is True
