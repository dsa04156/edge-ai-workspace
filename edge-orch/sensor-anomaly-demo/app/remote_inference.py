from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

import httpx
from pydantic import ValidationError

from .inference_executor import (
    InferenceExecutionRequest,
    InferenceExecutionResult,
    LocalInferenceExecutor,
    RemoteInferenceExecutor,
)
from .model_adapter import ModelDecision
from .models import (
    AccelerationFrame,
    AxisSample,
    InferenceInputFrame,
    InferenceRequest,
    InferenceResponse,
    InferenceRoutingPreflight,
    InferenceRoutingStatus,
    InferenceTemperature,
    TemperatureFeatures,
    VibrationFeatures,
)


class RemoteInferenceError(RuntimeError):
    def __init__(self, reason_code: str, *, elapsed_ms: float, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.elapsed_ms = max(0.0, elapsed_ms)


@dataclass(frozen=True)
class RoutedInference:
    execution: InferenceExecutionResult
    target: Literal["edge-local", "server1"]

    @property
    def decision(self) -> ModelDecision:
        return self.execution.decision

    @property
    def request_id(self) -> str:
        return self.execution.request_id


class RemoteInferenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_attempts: int,
        remote_node: str = "etri-ser0002-cgnmsb",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.remote_node = remote_node
        self._owns_http = http is None
        self.http = http or httpx.AsyncClient(timeout=timeout_seconds)

    async def execute(
        self,
        request: InferenceExecutionRequest,
    ) -> InferenceExecutionResult:
        payload = InferenceRequest(
            service_id=request.service_id,
            request_id=request.request_id,
            timestamp=request.timestamp,
            model_version=request.model_version,
            source_node=request.source_node,
            input_contract="okdong.pump-motor.telemetry/v1",
            frame=InferenceInputFrame(
                origin=request.frame.origin,
                x=float(request.frame.x),
                y=float(request.frame.y),
                z=float(request.frame.z),
            ),
            temperature=InferenceTemperature(
                origin=request.temperature.origin,
                value=float(request.temperature.value),
            ),
        )
        started = time.perf_counter()
        last_reason = "remote_invalid_response"
        last_detail = "remote inference failed"
        for _ in range(self.max_attempts):
            try:
                response = await self.http.post(
                    f"{self.base_url}/infer",
                    json=payload.model_dump(mode="json", by_alias=True),
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 503:
                    raise RemoteInferenceError(
                        "remote_service_not_ready",
                        elapsed_ms=_elapsed_ms(started),
                        detail="remote readiness gate returned 503",
                    )
                if response.status_code == 409:
                    raise RemoteInferenceError(
                        "remote_model_version_mismatch",
                        elapsed_ms=_elapsed_ms(started),
                        detail="remote model contract rejected the request",
                    )
                response.raise_for_status()
                parsed = InferenceResponse.model_validate(response.json())
                self._validate_response(parsed, payload)
                total_latency_ms = _elapsed_ms(started)
                processing_ms = (
                    parsed.processing_time_ms
                    if parsed.processing_time_ms is not None
                    else parsed.server_processing_ms
                )
                network_latency_ms = (
                    max(0.0, total_latency_ms - processing_ms)
                    if processing_ms is not None
                    else total_latency_ms
                )
                return InferenceExecutionResult(
                    decision=_decision(parsed),
                    request_id=request.request_id,
                    execution_mode="remote",
                    model_version=parsed.model_version,
                    source_node=request.source_node,
                    remote_node=self.remote_node,
                    network_latency_ms=round(network_latency_ms, 6),
                    remote_processing_ms=processing_ms,
                    total_latency_ms=round(total_latency_ms, 6),
                )
            except RemoteInferenceError as exc:
                if exc.elapsed_ms > 0:
                    raise
                raise RemoteInferenceError(
                    exc.reason_code,
                    elapsed_ms=_elapsed_ms(started),
                    detail=str(exc),
                ) from exc
            except httpx.TimeoutException as exc:
                last_reason = "remote_timeout"
                last_detail = exc.__class__.__name__
            except httpx.RequestError as exc:
                last_reason = "remote_connection_failure"
                last_detail = exc.__class__.__name__
            except (httpx.HTTPStatusError, ValidationError, ValueError) as exc:
                last_reason = "remote_invalid_response"
                last_detail = exc.__class__.__name__
        raise RemoteInferenceError(
            last_reason,
            elapsed_ms=_elapsed_ms(started),
            detail=(
                f"remote inference failed after {self.max_attempts} attempt(s): "
                f"{last_detail}"
            ),
        )

    async def infer(
        self,
        frame: AccelerationFrame,
        temperature: AxisSample,
        *,
        model_version: str = "baseline-1.0.0",
        source_node: str = "unknown",
    ) -> ModelDecision:
        result = await self.execute(
            InferenceExecutionRequest(
                service_id="sensor-anomaly-demo",
                request_id=f"sensor-anomaly-demo:{source_node}:{frame.origin}",
                timestamp=datetime.fromtimestamp(
                    frame.origin / 1_000_000_000,
                    timezone.utc,
                ),
                model_version=model_version,
                source_node=source_node,
                frame=frame,
                temperature=temperature,
            )
        )
        return result.decision

    async def probe_readiness(self, model_version: str) -> float:
        started = time.perf_counter()
        try:
            response = await self.http.get(
                f"{self.base_url}/api/v1/augmentation-readyz",
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise RemoteInferenceError(
                "remote_timeout",
                elapsed_ms=_elapsed_ms(started),
                detail="remote readiness probe timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise RemoteInferenceError(
                "remote_connection_failure",
                elapsed_ms=_elapsed_ms(started),
                detail="remote readiness endpoint is unreachable",
            ) from exc
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise RemoteInferenceError(
                "remote_service_not_ready",
                elapsed_ms=_elapsed_ms(started),
                detail="remote readiness contract failed",
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "ready"
            or payload.get("capability") != "sensor-anomaly-inference"
        ):
            raise RemoteInferenceError(
                "remote_invalid_response",
                elapsed_ms=_elapsed_ms(started),
                detail="remote readiness response is invalid",
            )
        if payload.get("modelVersion") != model_version:
            raise RemoteInferenceError(
                "remote_model_version_mismatch",
                elapsed_ms=_elapsed_ms(started),
                detail="remote readiness modelVersion mismatch",
            )
        return round(_elapsed_ms(started), 6)

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    @staticmethod
    def _validate_response(
        response: InferenceResponse,
        request: InferenceRequest,
    ) -> None:
        if response.service_id != request.service_id:
            raise ValueError("remote response serviceId mismatch")
        if response.request_id != request.request_id:
            raise ValueError("remote response requestId mismatch")
        if response.origin != request.frame.origin:
            raise ValueError("remote response origin mismatch")
        if response.input_contract != request.input_contract:
            raise ValueError("remote response input contract mismatch")
        if response.model_state != "ready":
            raise RemoteInferenceError(
                "remote_service_not_ready",
                elapsed_ms=0,
                detail="remote model is not ready",
            )
        if response.model_version != request.model_version:
            raise RemoteInferenceError(
                "remote_model_version_mismatch",
                elapsed_ms=0,
                detail="remote response modelVersion mismatch",
            )
        if response.timestamp is None or request.timestamp is None:
            raise ValueError("remote response timestamp is missing")
        if _utc(response.timestamp) != _utc(request.timestamp):
            raise RemoteInferenceError(
                "remote_stale_response",
                elapsed_ms=0,
                detail="remote response timestamp mismatch",
            )


class RemoteInferenceRouter:
    def __init__(
        self,
        *,
        mode: Literal["disabled", "approved"],
        approval_id: str | None,
        client: RemoteInferenceClient | None,
        failure_threshold: int,
        rollback_cooldown_seconds: int,
        source_node: str = "unknown",
        remote_node: str = "etri-ser0002-cgnmsb",
        local_model_version: str = "baseline-1.0.0",
        remote_model_version: str = "baseline-1.0.0",
        latency_threshold_ms: float = 1_000.0,
        latency_failure_threshold: int = 3,
        initial_target: Literal["local", "remote"] = "remote",
    ) -> None:
        if mode == "approved" and (not approval_id or client is None):
            raise ValueError("approved routing requires approval_id and client")
        self.mode = mode
        self.approval_id = approval_id
        self.client = client
        self.failure_threshold = failure_threshold
        self.rollback_cooldown_seconds = rollback_cooldown_seconds
        self.source_node = source_node
        self.remote_node = remote_node
        self.local_model_version = local_model_version
        self.remote_model_version = remote_model_version
        self.latency_threshold_ms = latency_threshold_ms
        self.latency_failure_threshold = latency_failure_threshold
        self.consecutive_failures = 0
        self.consecutive_latency_violations = 0
        self.rollback_until: datetime | None = None
        self.last_error: str | None = None
        self.last_reason_code: str | None = None
        self.remote_attempts = 0
        self.remote_successes = 0
        self.fallback_count = 0
        self.remote_ready: bool | None = None
        self._last_execution: InferenceExecutionResult | None = None
        self._routing_epoch = 0
        self._requested_target: Literal["edge-local", "server1"] = (
            "server1"
            if mode == "approved" and initial_target == "remote"
            else "edge-local"
        )
        self._effective_target: Literal["edge-local", "server1"] = (
            self._requested_target
        )

    async def infer(
        self,
        frame: AccelerationFrame,
        temperature: AxisSample,
        *,
        local: Callable[[], ModelDecision | None],
        now: datetime | None = None,
        request_id: str | None = None,
        allow_remote: bool = True,
    ) -> RoutedInference | None:
        observed_at = _utc(now)
        request = InferenceExecutionRequest(
            service_id="sensor-anomaly-demo",
            request_id=(
                request_id
                or f"sensor-anomaly-demo:{self.source_node}:{frame.origin}"
            ),
            timestamp=datetime.fromtimestamp(
                frame.origin / 1_000_000_000,
                timezone.utc,
            ),
            model_version=self.remote_model_version,
            source_node=self.source_node,
            frame=frame,
            temperature=temperature,
        )
        if (
            self.mode != "approved"
            or self._requested_target != "server1"
            or not allow_remote
        ):
            return await self._local(
                request,
                local,
                fallback=False,
                reason_code=(
                    "remote_disabled_for_non_active_workload"
                    if self.mode == "approved" and not allow_remote
                    else None
                ),
            )
        if self._rollback_active(observed_at):
            return await self._local(
                request,
                local,
                fallback=True,
                reason_code="remote_cooldown_active",
            )

        assert self.client is not None
        epoch = self._routing_epoch
        self.remote_attempts += 1
        try:
            execution = await RemoteInferenceExecutor(self.client).execute(request)
            if epoch != self._routing_epoch or self._requested_target != "server1":
                return await self._local(
                    request,
                    local,
                    fallback=True,
                    reason_code="remote_stale_response",
                    elapsed_before_local_ms=execution.total_latency_ms or 0,
                )
            self.remote_ready = True
            self.remote_successes += 1
            if (
                execution.total_latency_ms is not None
                and execution.total_latency_ms > self.latency_threshold_ms
            ):
                self.consecutive_latency_violations += 1
            else:
                self.consecutive_latency_violations = 0
            if self.consecutive_latency_violations >= self.latency_failure_threshold:
                self._start_rollback(observed_at, "remote_latency_threshold_exceeded")
                return await self._local(
                    request,
                    local,
                    fallback=True,
                    reason_code="remote_latency_threshold_exceeded",
                    elapsed_before_local_ms=execution.total_latency_ms or 0,
                )
        except RemoteInferenceError as exc:
            self.remote_ready = (
                False
                if exc.reason_code
                in {
                    "remote_connection_failure",
                    "remote_service_not_ready",
                }
                else self.remote_ready
            )
            self.consecutive_failures += 1
            self.last_error = str(exc)
            self.last_reason_code = exc.reason_code
            if self.consecutive_failures >= self.failure_threshold:
                self._start_rollback(observed_at, exc.reason_code)
            return await self._local(
                request,
                local,
                fallback=True,
                reason_code=exc.reason_code,
                elapsed_before_local_ms=exc.elapsed_ms,
            )

        self.consecutive_failures = 0
        self.rollback_until = None
        self.last_error = None
        self.last_reason_code = None
        self._effective_target = "server1"
        self._last_execution = execution
        return RoutedInference(execution=execution, target="server1")

    def activate_remote(self, approval_id: str) -> InferenceRoutingStatus:
        if self.mode != "approved" or approval_id != self.approval_id:
            raise ValueError("remote_inference_approval_required")
        self._routing_epoch += 1
        self._requested_target = "server1"
        self._effective_target = "server1"
        self.rollback_until = None
        self.consecutive_failures = 0
        self.consecutive_latency_violations = 0
        self.last_error = None
        self.last_reason_code = "remote_activation_approved"
        return self.status()

    async def preflight(self) -> InferenceRoutingPreflight:
        observed_at = datetime.now(timezone.utc)
        if self.mode != "approved" or self.client is None:
            return InferenceRoutingPreflight(
                ready=False,
                source_node=self.source_node,
                remote_node=self.remote_node,
                target_model_version=self.remote_model_version,
                reason_codes=["remote_inference_not_approved"],
                observed_at=observed_at,
            )
        try:
            network_latency_ms = await self.client.probe_readiness(
                self.remote_model_version
            )
        except RemoteInferenceError as exc:
            return InferenceRoutingPreflight(
                ready=False,
                source_node=self.source_node,
                remote_node=self.remote_node,
                target_model_version=self.remote_model_version,
                network_latency_ms=exc.elapsed_ms,
                reason_codes=[exc.reason_code],
                observed_at=observed_at,
            )
        return InferenceRoutingPreflight(
            ready=True,
            source_node=self.source_node,
            remote_node=self.remote_node,
            target_model_version=self.remote_model_version,
            network_latency_ms=network_latency_ms,
            reason_codes=["remote_readiness_observed_from_source"],
            observed_at=observed_at,
        )

    def activate_local(
        self,
        *,
        reason_code: str = "local_mode_requested",
    ) -> InferenceRoutingStatus:
        self._routing_epoch += 1
        self._requested_target = "edge-local"
        self._effective_target = "edge-local"
        self.rollback_until = None
        self.last_reason_code = reason_code
        return self.status()

    def status(self, *, now: datetime | None = None) -> InferenceRoutingStatus:
        observed_at = _utc(now)
        remaining = 0
        if self.rollback_until is not None:
            remaining = max(
                0,
                math.ceil((self.rollback_until - observed_at).total_seconds()),
            )
        rolled_back = remaining > 0
        latest = self._last_execution
        inference_mode: Literal["LOCAL", "REMOTE", "LOCAL_FALLBACK"] = (
            "LOCAL"
            if self._requested_target == "edge-local" and not rolled_back
            else
            "LOCAL_FALLBACK"
            if latest is not None and latest.fallback
            else "REMOTE"
            if self._effective_target == "server1"
            else "LOCAL"
        )
        return InferenceRoutingStatus(
            configured_mode=self.mode,
            state=(
                "disabled"
                if self.mode == "disabled"
                else "rolled-back"
                if rolled_back
                else "remote"
            ),
            effective_target="edge-local" if rolled_back else self._effective_target,
            approval_id=self.approval_id,
            consecutive_failures=self.consecutive_failures,
            rollback_remaining_seconds=remaining,
            last_error=self.last_error,
            inference_mode=inference_mode,
            source_node=self.source_node,
            remote_node=self.remote_node if self.mode == "approved" else None,
            remote_ready=self.remote_ready,
            target_model_version=(
                self.remote_model_version if self.mode == "approved" else None
            ),
            local_latency_ms=latest.local_latency_ms if latest else None,
            network_latency_ms=latest.network_latency_ms if latest else None,
            remote_processing_ms=latest.remote_processing_ms if latest else None,
            total_latency_ms=latest.total_latency_ms if latest else None,
            remote_attempts=self.remote_attempts,
            remote_successes=self.remote_successes,
            offload_success_rate=(
                round(self.remote_successes / self.remote_attempts, 6)
                if self.remote_attempts > 0
                else None
            ),
            fallback_count=self.fallback_count,
            last_reason_code=(latest.reason_code if latest else self.last_reason_code),
            observed_at=observed_at,
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def _local(
        self,
        request: InferenceExecutionRequest,
        local: Callable[[], ModelDecision | None],
        *,
        fallback: bool,
        reason_code: str | None,
        elapsed_before_local_ms: float = 0,
    ) -> RoutedInference | None:
        local_request = replace(request, model_version=self.local_model_version)
        try:
            execution = await LocalInferenceExecutor(
                local,
                fallback=fallback,
                reason_code=reason_code,
                elapsed_before_local_ms=elapsed_before_local_ms,
            ).execute(local_request)
        except RuntimeError:
            return None
        if fallback:
            self.fallback_count += 1
        self._effective_target = "edge-local"
        self._last_execution = execution
        self.last_reason_code = reason_code
        return RoutedInference(execution=execution, target="edge-local")

    def _start_rollback(self, now: datetime, reason_code: str) -> None:
        self.rollback_until = now + timedelta(
            seconds=self.rollback_cooldown_seconds
        )
        self._effective_target = "edge-local"
        self.last_reason_code = reason_code

    def _rollback_active(self, now: datetime) -> bool:
        if self.rollback_until is None:
            return False
        if now < self.rollback_until:
            return True
        self.rollback_until = None
        self.consecutive_failures = 0
        self.consecutive_latency_violations = 0
        self.last_error = None
        self.last_reason_code = "remote_retry_after_cooldown"
        self._effective_target = "server1"
        return False


def _decision(response: InferenceResponse) -> ModelDecision:
    return ModelDecision(
        status=response.status,
        score=response.score,
        vibration_score=response.component_scores.vibration,
        temperature_score=response.component_scores.temperature,
        vibration_features=VibrationFeatures(
            origin=response.origin,
            rms=response.vibration_features.rms,
            peak=response.vibration_features.peak,
            kurtosis=response.vibration_features.kurtosis,
            sample_count=response.vibration_features.sample_count,
        ),
        temperature_features=TemperatureFeatures(
            origin=response.temperature_features.origin,
            raw=response.temperature_features.raw,
            mean=response.temperature_features.mean,
            stddev=response.temperature_features.stddev,
            delta=response.temperature_features.delta,
            sample_count=response.temperature_features.sample_count,
        ),
    )


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1_000)


def _utc(value: datetime | None) -> datetime:
    observed = value or datetime.now(timezone.utc)
    return observed if observed.tzinfo is not None else observed.replace(tzinfo=timezone.utc)
