from __future__ import annotations

import asyncio
import json
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


def _remote_payload(
    request_id: str,
    origin: int,
    *,
    timestamp: str | None = None,
    model_version: str = "baseline-1.0.0",
    processing_time_ms: float = 1.5,
) -> dict:
    return {
        "apiVersion": "v1",
        "serviceId": "sensor-anomaly-demo",
        "requestId": request_id,
        "timestamp": timestamp or datetime.fromtimestamp(
            origin / 1_000_000_000, timezone.utc
        ).isoformat(),
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
        "modelVersion": model_version,
        "processingTimeMs": processing_time_ms,
        "serverProcessingMs": processing_time_ms,
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
        payload = json.loads(request.read())
        return httpx.Response(200, json=_remote_payload(
            payload["requestId"], 100, timestamp=payload["timestamp"]
        ))

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
    assert all(
        '"requestId":"sensor-anomaly-demo:unknown:100"' in body
        for body in calls
    )


def test_approved_router_uses_remote_result_and_records_approval() -> None:
    asyncio.run(_approved_router_uses_remote_result_and_records_approval())


async def _approved_router_uses_remote_result_and_records_approval() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        return httpx.Response(200, json=_remote_payload(
            payload["requestId"], 100, timestamp=payload["timestamp"]
        ))

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


def test_preflight_measures_readiness_from_the_source_worker() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/augmentation-readyz"
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "capability": "sensor-anomaly-inference",
                    "modelVersion": "baseline-1.0.0",
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-001",
            client=RemoteInferenceClient(
                base_url="http://server1",
                timeout_seconds=0.1,
                max_attempts=1,
                http=http,
            ),
            failure_threshold=1,
            rollback_cooldown_seconds=30,
            source_node="edge-a",
            remote_node="server-b",
        )
        result = await router.preflight()
        await http.aclose()
        assert result.ready is True
        assert result.source_node == "edge-a"
        assert result.remote_node == "server-b"
        assert result.network_latency_ms is not None
        assert result.reason_codes == ["remote_readiness_observed_from_source"]

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["request-id", "origin", "model-state"])
def test_remote_contract_mismatch_or_unready_model_falls_back_local(
    invalid: str,
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            request_payload = json.loads(request.read())
            payload = _remote_payload(
                request_payload["requestId"],
                100,
                timestamp=request_payload["timestamp"],
            )
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
        assert routed.execution.execution_mode == "fallback"
        assert routed.execution.reason_code in {
            "remote_invalid_response",
            "remote_service_not_ready",
        }
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
    assert status.fallback_count == 3
    assert status.last_reason_code == "remote_cooldown_active"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("timeout", "remote_timeout"),
        ("connection", "remote_connection_failure"),
        ("unready", "remote_service_not_ready"),
        ("model", "remote_model_version_mismatch"),
        ("stale", "remote_stale_response"),
    ],
)
def test_remote_failures_have_stable_reason_codes_and_local_fallback(
    kind: str,
    expected: str,
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if kind == "timeout":
                raise httpx.ReadTimeout("slow", request=request)
            if kind == "connection":
                raise httpx.ConnectError("down", request=request)
            request_payload = json.loads(request.read())
            if kind == "unready":
                return httpx.Response(503, json={"detail": "not ready"})
            payload = _remote_payload(
                request_payload["requestId"],
                100,
                timestamp=request_payload["timestamp"],
            )
            if kind == "model":
                payload["modelVersion"] = "other-model"
            if kind == "stale":
                payload["timestamp"] = "2026-01-01T00:00:00Z"
            return httpx.Response(200, json=payload)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-001",
            client=RemoteInferenceClient(
                base_url="http://server1",
                timeout_seconds=0.01,
                max_attempts=1,
                http=http,
            ),
            failure_threshold=1,
            rollback_cooldown_seconds=30,
        )
        routed = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
        )
        await http.aclose()
        assert routed is not None
        assert routed.target == "edge-local"
        assert routed.execution.fallback is True
        assert routed.execution.reason_code == expected
        assert routed.execution.total_latency_ms is not None

    asyncio.run(scenario())


def test_sustained_remote_latency_violation_falls_back() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.read())
            return httpx.Response(200, json=_remote_payload(
                payload["requestId"], 100, timestamp=payload["timestamp"],
                processing_time_ms=0,
            ))

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-001",
            client=RemoteInferenceClient(
                base_url="http://server1", timeout_seconds=0.1, max_attempts=1, http=http
            ),
            failure_threshold=2,
            rollback_cooldown_seconds=30,
            latency_threshold_ms=0.001,
            latency_failure_threshold=2,
        )
        first = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
        )
        second = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
        )
        await http.aclose()
        assert first is not None and first.target == "server1"
        assert second is not None and second.target == "edge-local"
        assert second.execution.reason_code == "remote_latency_threshold_exceeded"

    asyncio.run(scenario())


def test_non_active_workload_never_calls_remote() -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-001",
            client=RemoteInferenceClient(
                base_url="http://server1", timeout_seconds=0.1, max_attempts=1, http=http
            ),
            failure_threshold=1,
            rollback_cooldown_seconds=30,
        )
        routed = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
            allow_remote=False,
        )
        await http.aclose()
        assert calls == 0
        assert routed is not None and routed.target == "edge-local"
        assert routed.execution.reason_code == "remote_disabled_for_non_active_workload"

    asyncio.run(scenario())


def test_explicit_local_to_remote_transition_requires_matching_approval() -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            payload = json.loads(request.read())
            return httpx.Response(200, json=_remote_payload(
                payload["requestId"], 100, timestamp=payload["timestamp"]
            ))

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-001",
            client=RemoteInferenceClient(
                base_url="http://server1", timeout_seconds=0.1, max_attempts=1, http=http
            ),
            failure_threshold=1,
            rollback_cooldown_seconds=30,
            initial_target="local",
        )
        local = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
        )
        with pytest.raises(ValueError, match="approval"):
            router.activate_remote("wrong")
        activated = router.activate_remote("approval-001")
        remote = await router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
        )
        await http.aclose()
        assert local is not None and local.execution.execution_mode == "local"
        assert activated.inference_mode == "REMOTE"
        assert remote is not None and remote.execution.execution_mode == "remote"
        assert calls == 1

    asyncio.run(scenario())


def test_response_arriving_after_mode_change_is_rejected_as_stale() -> None:
    async def scenario() -> None:
        request_started = asyncio.Event()
        release_response = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.read())
            request_started.set()
            await release_response.wait()
            return httpx.Response(200, json=_remote_payload(
                payload["requestId"], 100, timestamp=payload["timestamp"]
            ))

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        router = RemoteInferenceRouter(
            mode="approved",
            approval_id="approval-001",
            client=RemoteInferenceClient(
                base_url="http://server1", timeout_seconds=1, max_attempts=1, http=http
            ),
            failure_threshold=1,
            rollback_cooldown_seconds=30,
        )
        task = asyncio.create_task(router.infer(
            AccelerationFrame(origin=100, x=1, y=2, z=3),
            AxisSample(origin=100, value_type="Float64", value=30),
            local=lambda: _local_decision(100),
        ))
        await request_started.wait()
        router.activate_local()
        release_response.set()
        routed = await task
        await http.aclose()
        assert routed is not None and routed.target == "edge-local"
        assert routed.execution.execution_mode == "fallback"
        assert routed.execution.reason_code == "remote_stale_response"
        assert router.status().inference_mode == "LOCAL"

    asyncio.run(scenario())


def test_approved_mode_requires_explicit_url_and_approval_id() -> None:
    with pytest.raises(ValueError, match="remote_inference_url"):
        Settings(
            remote_inference_mode="approved",
            remote_inference_approval_id="approval",
            remote_inference_control_token="control-token-001",
        )
    with pytest.raises(ValueError, match="remote_inference_approval_id"):
        Settings(
            remote_inference_mode="approved",
            remote_inference_url="http://server1",
            remote_inference_control_token="control-token-001",
        )
    with pytest.raises(ValueError, match="remote_inference_control_token"):
        Settings(
            remote_inference_mode="approved",
            remote_inference_url="http://server1",
            remote_inference_approval_id="approval",
        )
