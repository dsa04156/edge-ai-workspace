from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.inference_api import InferenceEngine
from app.main import create_app


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
    assert second.json()["serverProcessingMs"] >= 0
    assert second.json()["componentScores"] == {
        "vibration": 0.0,
        "temperature": 0.0,
    }
    assert readiness.json() == {
        "status": "ready",
        "capability": "sensor-anomaly-inference",
        "role": "inference-server",
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
            "/api/v1/inference",
            json=_payload("stable-request", 1_000_000_000),
        )
        replay = client.post(
            "/api/v1/inference",
            json=_payload("stable-request", 1_000_000_000),
        )
        conflict = client.post(
            "/api/v1/inference",
            json=_payload("stable-request", 2_000_000_000),
        )

    assert replay.json() == original.json()
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "requestId was reused with another payload"


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
