from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.inference_api import InferenceEngine
from app.main import create_app
from app.model_adapter import build_model_adapter
from app.models import (
    AccelerationFrame,
    AxisSample,
    InferenceRequest,
    InferenceRoutingPreflight,
    InferenceRoutingStatus,
)


def _settings() -> Settings:
    return Settings(
        service_role="inference-server",
        warmup_samples=2,
        vibration_window_samples=2,
        temperature_window_samples=2,
        context_max_skew_seconds=1,
    )


def _payload(request_id: str, origin: int, value: float = 1.0) -> dict:
    return {
        "apiVersion": "v1",
        "requestId": request_id,
        "inputContract": "okdong.pump-motor.telemetry/v1",
        "frame": {
            "origin": origin,
            "x": value,
            "y": value + 1,
            "z": value + 2,
        },
        "temperature": {
            "origin": origin,
            "value": 30 + value,
        },
    }


def test_inference_server_warms_model_and_exposes_real_readiness() -> None:
    settings = _settings()
    engine = InferenceEngine(settings)

    with TestClient(
        create_app(settings=settings, inference_engine=engine)
    ) as client:
        assert client.get("/healthz").json() == {
            "status": "ok",
            "role": "inference-server",
        }
        assert client.get("/readyz").status_code == 200
        assert client.get("/api/v1/augmentation-readyz").status_code == 503

        first = client.post(
            "/api/v1/inference",
            json=_payload("request-1", 1_000_000_000),
        )
        second = client.post(
            "/api/v1/inference",
            json=_payload("request-2", 2_000_000_000, 2.0),
        )

        readiness = client.get("/api/v1/augmentation-readyz")

    assert first.status_code == 200
    assert first.json()["status"] == "warming_up"
    assert first.json()["modelState"] == "warming_up"
    assert second.status_code == 200
    assert second.json()["modelState"] == "ready"
    assert second.json()["modelVersion"] == "baseline-1.0.0"
    assert second.json()["serviceId"] == "sensor-anomaly-demo"
    assert second.json()["requestId"] == "request-2"
    assert second.json()["timestamp"] is not None
    assert second.json()["processingTimeMs"] >= 0
    assert second.json()["serverProcessingMs"] >= 0
    assert second.json()["componentScores"] == {
        "vibration": 0.0,
        "temperature": 0.0,
    }
    assert readiness.json() == {
        "status": "ready",
        "capability": "sensor-anomaly-inference",
        "role": "inference-server",
        "modelVersion": "baseline-1.0.0",
        "modelBackend": "online-baseline",
        "accelerator": "cpu",
        "acceleratorDevice": "host-cpu",
    }


def test_inference_request_is_idempotent_and_rejects_key_reuse() -> None:
    settings = _settings()
    engine = InferenceEngine(settings)

    with TestClient(
        create_app(settings=settings, inference_engine=engine)
    ) as client:
        original = client.post(
            "/infer",
            json=_payload("stable-request", 1_000_000_000),
        )
        replay = client.post(
            "/infer",
            json=_payload("stable-request", 1_000_000_000),
        )
        conflict = client.post(
            "/api/v1/inference",
            json=_payload("stable-request", 2_000_000_000),
        )

    assert replay.json() == original.json()
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "requestId was reused with another payload"


def test_remote_and_legacy_paths_share_the_same_inference_engine() -> None:
    settings = _settings()
    payload = _payload("shared-path", 1_000_000_000)
    with TestClient(
        create_app(settings=settings, inference_engine=InferenceEngine(settings))
    ) as client:
        remote = client.post("/infer", json=payload)
        legacy = client.post("/api/v1/inference", json=payload)

    assert remote.status_code == 200
    assert legacy.status_code == 200
    assert remote.json() == legacy.json()


def test_local_and_remote_executors_produce_consistent_model_results() -> None:
    settings = _settings()
    local = build_model_adapter(settings)
    remote = InferenceEngine(settings)

    for index, value in enumerate((1.0, 2.0), start=1):
        origin = index * 1_000_000_000
        payload = _payload(f"consistency-{index}", origin, value)
        local.ingest_temperature(
            AxisSample(
                origin=origin,
                value_type="Float64",
                value=30 + value,
            )
        )
        local_result = local.infer(
            AccelerationFrame(
                origin=origin,
                x=value,
                y=value + 1,
                z=value + 2,
            ),
            origin,
        )
        remote_result = remote.infer(InferenceRequest.model_validate(payload))

        assert local_result is not None
        assert remote_result.status == local_result.status
        assert remote_result.score == local_result.score
        assert remote_result.component_scores.vibration == local_result.vibration_score
        assert remote_result.component_scores.temperature == local_result.temperature_score
        assert remote_result.model_version == local.version


def test_inference_rejects_model_version_mismatch() -> None:
    settings = _settings()
    payload = _payload("wrong-model", 1_000_000_000)
    payload["modelVersion"] = "another-model"
    with TestClient(
        create_app(settings=settings, inference_engine=InferenceEngine(settings))
    ) as client:
        response = client.post("/infer", json=payload)

    assert response.status_code == 409
    assert "modelVersion" in response.json()["detail"]


def test_inference_endpoint_enforces_contract_and_alignment() -> None:
    settings = _settings()

    with TestClient(
        create_app(settings=settings, inference_engine=InferenceEngine(settings))
    ) as client:
        missing_temperature = _payload("missing-temperature", 1_000_000_000)
        missing_temperature.pop("temperature")
        skewed = _payload("skewed", 3_000_000_000)
        skewed["temperature"]["origin"] = 1_000_000_000
        wrong_contract = _payload("wrong-contract", 1_000_000_000)
        wrong_contract["inputContract"] = "unknown/v1"

        assert client.post(
            "/api/v1/inference", json=missing_temperature
        ).status_code == 422
        assert client.post("/api/v1/inference", json=skewed).status_code == 422
        assert client.post(
            "/api/v1/inference", json=wrong_contract
        ).status_code == 422


def test_edge_worker_does_not_expose_remote_inference_mutation() -> None:
    from tests.test_api import FakeRuntime

    with TestClient(create_app(runtime=FakeRuntime())) as client:
        response = client.post(
            "/api/v1/inference",
            json=_payload("edge-request", 1_000_000_000),
        )

    assert response.status_code == 404


def test_routing_change_requires_explicit_approval_header() -> None:
    from tests.test_api import FakeRuntime

    class Router:
        async def preflight(self) -> InferenceRoutingPreflight:
            return InferenceRoutingPreflight(
                ready=True,
                source_node="etri-dev0001-jetorn",
                remote_node="etri-ser0002-cgnmsb",
                target_model_version="baseline-1.0.0",
                network_latency_ms=12.5,
                reason_codes=["remote_readiness_observed_from_source"],
            )

        def activate_remote(self, approval_id: str) -> InferenceRoutingStatus:
            assert approval_id == "approval-001"
            return InferenceRoutingStatus(
                configured_mode="approved",
                state="remote",
                effective_target="server1",
                approval_id=approval_id,
                inference_mode="REMOTE",
            )

        def activate_local(self) -> InferenceRoutingStatus:
            return InferenceRoutingStatus(
                configured_mode="approved",
                state="remote",
                effective_target="edge-local",
                approval_id="approval-001",
                inference_mode="LOCAL",
            )

    runtime = FakeRuntime()
    runtime.inference_router = Router()
    settings = Settings(
        remote_inference_mode="approved",
        remote_inference_url="http://server1",
        remote_inference_approval_id="approval-001",
        remote_inference_control_token="control-token-001",
    )
    with TestClient(create_app(runtime=runtime, settings=settings)) as client:
        denied = client.post(
            "/api/v1/inference-routing", json={"mode": "REMOTE"}
        )
        allowed = client.post(
            "/api/v1/inference-routing",
            json={"mode": "REMOTE"},
            headers={"X-Offload-Approval": "control-token-001"},
        )
        preflight = client.get("/api/v1/inference-routing/preflight")

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["inferenceMode"] == "REMOTE"
    assert preflight.status_code == 200
    assert preflight.json()["networkLatencyMs"] == 12.5
