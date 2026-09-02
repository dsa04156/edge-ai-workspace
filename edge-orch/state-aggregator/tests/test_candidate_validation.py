from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.candidate_validation import (
    CandidateValidationEngine,
    ValidationContractCatalog,
)


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app/config/candidate_validation_contracts.json"
)


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)
        self.elapsed = 0.0

    def now(self) -> datetime:
        return self.value

    def monotonic(self) -> float:
        return self.elapsed

    async def sleep(self, seconds: float) -> None:
        self.elapsed += seconds
        self.value += timedelta(seconds=seconds)


def _pod(
    *,
    name: str,
    node: str,
    ip: str,
    ready: bool = True,
    plan_id: str | None = None,
):
    labels = (
        {"edge-ai.io/execution-plan-id": plan_id}
        if plan_id is not None
        else {"app.kubernetes.io/name": "sensor-anomaly-demo"}
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, labels=labels),
        spec=SimpleNamespace(node_name=node),
        status=SimpleNamespace(
            pod_ip=ip,
            conditions=[
                SimpleNamespace(type="Ready", status="True" if ready else "False")
            ],
        ),
    )


class FakeKube:
    def __init__(self, *, candidate_ready: bool = True) -> None:
        self.candidate = _pod(
            name="candidate-pod",
            node="server-b",
            ip="10.0.0.2",
            ready=candidate_ready,
            plan_id="runtime-plan-0123456789abcdef",
        )
        self.source = _pod(
            name="source-pod",
            node="edge-a",
            ip="10.0.0.1",
        )

    async def list_deployment_pods(self, namespace, name):
        return [self.candidate]

    async def list_pods(self, namespace, label_selector):
        return [self.source]


def _contract(*, timeout: float = 10):
    catalog = ValidationContractCatalog.load(CONTRACT_PATH)
    contract, error = catalog.resolve("sensor-anomaly-demo")
    assert error is None and contract is not None
    contract = contract.model_copy(deep=True)
    contract.stabilization.timeout_seconds = timeout
    contract.stabilization.poll_interval_seconds = 5
    contract.stabilization.minimum_stable_seconds = 10
    contract.stabilization.required_consecutive_successes = 3
    return contract


def _status(
    clock: FakeClock,
    *,
    input_state: str = "fresh",
    model_state: str = "ready",
    result: bool = True,
    latency_ms: float = 82,
    metrics_valid: bool = True,
    frames_processed: int = 30,
    execution_mode: str = "ACTIVE",
):
    observed_at = clock.now().isoformat()
    return {
        "inputState": input_state,
        "modelState": model_state,
        "latest": {"observedAt": observed_at} if result else None,
        "performance": {
            "metricsValid": metrics_valid,
            "processingLatencyP95Ms": latency_ms,
        },
        "counters": {
            "framesProcessed": frames_processed,
            "shadowFramesProcessed": frames_processed,
        },
        "storage": {"resultCount": frames_processed},
        "executionOwnership": {
            "enabled": True,
            "effectiveMode": execution_mode,
            "leaseValid": True,
        },
    }


def _transport(
    clock: FakeClock,
    *,
    input_states: list[str] | None = None,
    model_state: str = "ready",
    result: bool = True,
    latency_ms: float = 82,
    metrics_valid: bool = True,
    unreachable: bool = False,
    execution_mode: str = "ACTIVE",
) -> httpx.MockTransport:
    status_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_requests
        is_candidate = request.url.host in {
            "10.0.0.2",
            "sensor-anomaly-demo.edgex-edge.svc.cluster.local",
        }
        if is_candidate and unreachable:
            raise httpx.ConnectError("unreachable", request=request)
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/augmentation-readyz":
            active_input = (
                input_states[min(status_requests, len(input_states) - 1)]
                if input_states
                else "fresh"
            )
            if active_input != "fresh" or model_state != "ready":
                return httpx.Response(503, json={"status": "not-ready"})
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "capability": "sensor-anomaly-inference",
                },
            )
        if path == "/api/v1/status":
            active_input = (
                input_states[min(status_requests, len(input_states) - 1)]
                if is_candidate and input_states
                else "fresh"
            )
            if is_candidate:
                status_requests += 1
            return httpx.Response(
                200,
                json=_status(
                    clock,
                    input_state=active_input,
                    model_state=model_state if is_candidate else "ready",
                    result=result if is_candidate else True,
                    latency_ms=latency_ms if is_candidate else 180,
                    metrics_valid=metrics_valid if is_candidate else True,
                    frames_processed=30 + status_requests if is_candidate else 20,
                    execution_mode=execution_mode if is_candidate else "ACTIVE",
                ),
            )
        if path == "/api/v1/results":
            observed_at = clock.now().isoformat()
            return httpx.Response(
                200,
                json={
                    "count": 1 if result else 0,
                    "results": [{"observedAt": observed_at}] if result else [],
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    return httpx.MockTransport(handler)


def _validate(
    clock: FakeClock,
    *,
    transport: httpx.MockTransport,
    candidate_ready: bool = True,
    timeout: float = 10,
):
    engine = CandidateValidationEngine(
        FakeKube(candidate_ready=candidate_ready),
        transport=transport,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    observations = []

    async def observe(result):
        observations.append(result)

    result = asyncio.run(
        engine.validate(
            contract=_contract(timeout=timeout),
            candidate_namespace="edge-ai-workloads",
            candidate_name="sensor-anomaly-demo-replace-01234567",
            candidate_node="server-b",
            candidate_port=8080,
            plan_id="runtime-plan-0123456789abcdef",
            source_namespace="edgex-edge",
            source_selector={"app.kubernetes.io/name": "sensor-anomaly-demo"},
            source_node="edge-a",
            observer=observe,
        )
    )
    return result, observations


def _check(result, name):
    return next(item for item in result.checks if item.name == name)


def test_contract_loads_and_candidate_stabilizes_before_success() -> None:
    clock = FakeClock()
    result, observations = _validate(clock, transport=_transport(clock))

    assert result.status == "SUCCEEDED"
    assert result.consecutive_successes == 3
    assert result.stable_since == result.started_at
    assert clock.elapsed == 10
    assert result.candidate is not None and result.candidate.latency_ms == 82
    assert result.candidate.db_write_count == result.candidate.frames_processed
    assert result.source is not None and result.source.latency_ms == 180
    assert all(item.status == "SUCCEEDED" for item in result.checks)
    assert [item.status for item in observations] == [
        "RUNNING",
        "RUNNING",
        "SUCCEEDED",
    ]


def test_pre_activation_contract_requires_shadow_inference_without_active_frames() -> None:
    clock = FakeClock()
    contract = _contract().for_phase("pre_activation")
    engine = CandidateValidationEngine(
        FakeKube(),
        transport=_transport(clock, execution_mode="SHADOW"),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    result = asyncio.run(
        engine.validate(
            contract=contract,
            candidate_namespace="edge-ai-workloads",
            candidate_name="sensor-anomaly-demo-replace-01234567",
            candidate_node="server-b",
            candidate_port=8080,
            plan_id="runtime-plan-0123456789abcdef",
            source_namespace="edgex-edge",
            source_selector={"app.kubernetes.io/name": "sensor-anomaly-demo"},
            source_node="edge-a",
            frames_processed_pointer="/counters/shadowFramesProcessed",
        )
    )

    assert result.status == "SUCCEEDED"
    assert result.candidate is not None
    assert result.candidate.frames_processed is not None
    assert result.candidate.frames_processed > 0
    assert _check(result, "execution_shadow").status == "SUCCEEDED"
    assert _check(result, "shadow_inference").status == "SUCCEEDED"


def test_missing_or_invalid_contract_fails_closed(tmp_path) -> None:
    catalog = ValidationContractCatalog.load(CONTRACT_PATH)
    missing, missing_error = catalog.resolve("unknown-service")
    assert missing is None
    assert missing_error == "candidate_validation_contract_unsupported"

    invalid_path = tmp_path / "invalid-validation.json"
    invalid_path.write_text('{"contracts":[{"serviceId":"sensor-anomaly-demo"}]}')
    invalid = ValidationContractCatalog.load(invalid_path)
    contract, error = invalid.resolve("sensor-anomaly-demo")
    assert contract is None
    assert error == "candidate_validation_contract_unsupported"


@pytest.mark.parametrize(
    ("transport_kwargs", "expected_reason"),
    [
        ({"input_states": ["waiting"]}, "candidate_input_unavailable"),
        ({"input_states": ["stale"]}, "candidate_input_stale"),
        ({"model_state": "warming_up"}, "candidate_model_not_ready"),
        ({"result": False}, "candidate_inference_not_observed"),
        ({"latency_ms": 4500}, "candidate_latency_slo_violated"),
        ({"unreachable": True}, "candidate_endpoint_unreachable"),
    ],
)
def test_functional_failures_timeout_with_specific_reason(
    transport_kwargs,
    expected_reason,
) -> None:
    clock = FakeClock()
    result, _ = _validate(
        clock,
        transport=_transport(clock, **transport_kwargs),
    )

    assert result.status == "FAILED"
    assert result.reason_codes[0] == "candidate_validation_timeout"
    assert expected_reason in result.reason_codes


def test_optional_latency_is_explicitly_blocked_when_not_measurable() -> None:
    clock = FakeClock()
    result, _ = _validate(
        clock,
        transport=_transport(clock, metrics_valid=False),
    )

    assert result.status == "SUCCEEDED"
    latency = _check(result, "latency")
    assert latency.status == "BLOCKED"
    assert latency.evaluated is False
    assert latency.measurements == {"available": False}


def test_momentary_success_does_not_satisfy_dwell() -> None:
    clock = FakeClock()
    result, observations = _validate(
        clock,
        transport=_transport(
            clock,
            input_states=["fresh", "stale", "fresh"],
        ),
    )

    assert result.status == "FAILED"
    assert "candidate_validation_timeout" in result.reason_codes
    assert any(item.consecutive_successes == 0 for item in observations)


def test_pod_ready_is_rechecked_during_validation() -> None:
    clock = FakeClock()
    result, _ = _validate(
        clock,
        transport=_transport(clock),
        candidate_ready=False,
    )

    assert result.status == "FAILED"
    assert "candidate_not_ready" in result.reason_codes
    assert _check(result, "pod_ready").status == "BLOCKED"


def test_post_switch_validation_uses_service_route_and_requires_counter_increase() -> None:
    clock = FakeClock()
    transport = _transport(clock)
    engine = CandidateValidationEngine(
        FakeKube(),
        transport=transport,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    result = asyncio.run(
        engine.validate(
            contract=_contract(),
            candidate_namespace="edge-ai-workloads",
            candidate_name="candidate",
            candidate_node="server-b",
            candidate_port=8080,
            plan_id="runtime-plan-0123456789abcdef",
            source_namespace="edgex-edge",
            source_selector={"app.kubernetes.io/name": "sensor-anomaly-demo"},
            source_node="edge-a",
            candidate_base_url="http://sensor-anomaly-demo.edgex-edge.svc.cluster.local:8080",
            minimum_frames_processed_exclusive=30,
        )
    )

    assert result.status == "SUCCEEDED"
    counter = _check(result, "processing_counter_increased")
    assert counter.status == "SUCCEEDED"
    assert result.candidate.frames_processed > 30
