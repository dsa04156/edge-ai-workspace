from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.config import Settings
from app.model_adapter import ModelDecision
from app.models import (
    AccelerationFrame,
    AxisSample,
    TemperatureFeatures,
    VibrationFeatures,
)
from app.remote_inference import RemoteInferenceClient, RemoteInferenceRouter


def _remote_payload(request_id: str, origin: int) -> dict:
    return {
        "apiVersion": "v1",
        "requestId": request_id,
        "inputContract": "okdong.pump-motor.telemetry/v1",
        "origin": origin,
        "status": "normal",
        "anomaly": False,
        "score": 0.5,
        "componentScores": {"vibration": 0.4, "temperature": 0.7},
        "vibrationFeatures": {
            "rms": 1.0,
            "peak": 2.0,
            "kurtosis": 3.0,
            "sampleCount": 20,
        },
        "temperatureFeatures": {
            "origin": origin,
            "raw": 30.0,
            "mean": 29.5,
            "stddev": 0.2,
            "delta": 0.5,
            "sampleCount": 10,
            "alignmentLagMs": 0.0,
        },
        "modelState": "ready",
        "modelVersion": "baseline-1.0.0",
    }


def _local_decision(origin: int) -> ModelDecision:
    return ModelDecision(
        status="normal",
        score=0.1,
        vibration_score=0.1,
        temperature_score=0.1,
        vibration_features=VibrationFeatures(
            origin=origin,
            rms=1.0,
            peak=2.0,
            kurtosis=3.0,
            sample_count=20,
        ),
        temperature_features=TemperatureFeatures(
            origin=origin,
            raw=30.0,
            mean=30.0,
            stddev=0.0,
            delta=0.0,
            sample_count=10,
        ),
    )


def test_remote_client_retries_with_same_id_after_timeout() -> None:
    asyncio.run(_remote_client_retries_with_same_id_after_timeout())


async def _remote_client_retries_with_same_id_after_timeout() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.read().decode("utf-8")
        calls.append(request_id)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(
            200,
            json=_remote_payload("sensor-anomaly-demo:100", 100),
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RemoteInferenceClient(
        base_url="http://server1",
        timeout_seconds=0.1,
        max_attempts=2,
        http=http,
    )

    result = await client.infer(
        AccelerationFrame(origin=100, x=1, y=2, z=3),
        AxisSample(origin=100, value_type="Float64", value=30.0),
    )
    await client.close()

    assert result.score == 0.5
    assert len(calls) == 2
    assert all('"requestId":"sensor-anomaly-demo:100"' in body for body in calls)


def test_approved_router_uses_remote_result_and_records_approval() -> None:
    asyncio.run(_approved_router_uses_remote_result_and_records_approval())


async def _approved_router_uses_remote_result_and_records_approval() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_remote_payload("sensor-anomaly-demo:100", 100),
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RemoteInferenceClient(
        base_url="http://server1",
        timeout_seconds=0.1,
        max_attempts=1,
        http=http,
    )
    router = RemoteInferenceRouter(
        mode="approved",
        approval_id="approval-20260813-001",
        client=client,
        failure_threshold=2,
        rollback_cooldown_seconds=900,
    )

    routed = await router.infer(
        AccelerationFrame(origin=100, x=1, y=2, z=3),
        AxisSample(origin=100, value_type="Float64", value=30.0),
        local=lambda: _local_decision(100),
    )
    await client.close()

    assert routed.target == "server1"
    assert routed.decision.score == 0.5
    assert router.status().approval_id == "approval-20260813-001"
    assert router.status().effective_target == "server1"


@pytest.mark.parametrize("invalid", ["request-id", "origin", "model-state"])
def test_remote_contract_mismatch_or_unready_model_falls_back_local(
    invalid: str,
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _remote_payload("sensor-anomaly-demo:100", 100)
            if invalid == "request-id":
                payload["requestId"] = "another-request"
            elif invalid == "origin":
                payload["origin"] = 101
            else:
                payload["modelState"] = "warming_up"
            return httpx.Response(200, json=payload)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-20260813-001",
            client=RemoteInferenceClient(
                base_url="http://server1",
                timeout_seconds=0.1,
                max_attempts=1,
                http=http,
            ),
            failure_threshold=1,
            rollback_cooldown_seconds=900,
        )
        routed = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30.0),
            local=lambda: _local_decision(100),
        )
        await http.aclose()

        assert routed is not None and routed.target == "edge-local"
        assert router.status().state == "rolled-back"
        assert router.status().last_error is not None

    asyncio.run(scenario())


def test_remote_failures_rollback_to_local_until_cooldown() -> None:
    asyncio.run(_remote_failures_rollback_to_local_until_cooldown())


async def _remote_failures_rollback_to_local_until_cooldown() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("unreachable", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RemoteInferenceClient(
        base_url="http://server1",
        timeout_seconds=0.1,
        max_attempts=1,
        http=http,
    )
    router = RemoteInferenceRouter(
        mode="approved",
        approval_id="approval-20260813-001",
        client=client,
        failure_threshold=2,
        rollback_cooldown_seconds=900,
    )
    frame = AccelerationFrame(origin=100, x=1, y=2, z=3)
    temperature = AxisSample(origin=100, value_type="Float64", value=30.0)
    now = datetime(2026, 8, 13, tzinfo=timezone.utc)

    first = await router.infer(
        frame,
        temperature,
        local=lambda: _local_decision(100),
        now=now,
    )
    second = await router.infer(
        frame,
        temperature,
        local=lambda: _local_decision(100),
        now=now,
    )
    during_cooldown = await router.infer(
        frame,
        temperature,
        local=lambda: _local_decision(100),
        now=now.replace(minute=10),
    )
    await client.close()

    assert first.target == "edge-local"
    assert second.target == "edge-local"
    assert during_cooldown.target == "edge-local"
    assert attempts == 2
    status = router.status(now=now.replace(minute=10))
    assert status.state == "rolled-back"
    assert status.effective_target == "edge-local"
    assert status.rollback_remaining_seconds == 300


def test_approved_mode_requires_explicit_url_and_approval_id() -> None:
    with pytest.raises(ValueError, match="remote_inference_url"):
        Settings(remote_inference_mode="approved", remote_inference_approval_id="approval")
    with pytest.raises(ValueError, match="remote_inference_approval_id"):
        Settings(remote_inference_mode="approved", remote_inference_url="http://server1")
