from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

import httpx

from .model_adapter import ModelDecision
from .models import (
    AccelerationFrame,
    AxisSample,
    InferenceInputFrame,
    InferenceRequest,
    InferenceResponse,
    InferenceRoutingStatus,
    InferenceTemperature,
    TemperatureFeatures,
    VibrationFeatures,
)


class RemoteInferenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoutedInference:
    decision: ModelDecision
    target: Literal["edge-local", "server1"]


class RemoteInferenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_attempts: int,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self._owns_http = http is None
        self.http = http or httpx.AsyncClient(timeout=timeout_seconds)

    async def infer(
        self,
        frame: AccelerationFrame,
        temperature: AxisSample,
    ) -> ModelDecision:
        request = InferenceRequest(
            request_id=f"sensor-anomaly-demo:{frame.origin}",
            input_contract="okdong.pump-motor.telemetry/v1",
            frame=InferenceInputFrame(
                origin=frame.origin,
                x=float(frame.x),
                y=float(frame.y),
                z=float(frame.z),
            ),
            temperature=InferenceTemperature(
                origin=temperature.origin,
                value=float(temperature.value),
            ),
        )
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                response = await self.http.post(
                    f"{self.base_url}/api/v1/inference",
                    json=request.model_dump(mode="json", by_alias=True),
                )
                response.raise_for_status()
                parsed = InferenceResponse.model_validate(response.json())
                if parsed.request_id != request.request_id:
                    raise ValueError("remote response requestId mismatch")
                if parsed.origin != frame.origin:
                    raise ValueError("remote response origin mismatch")
                if parsed.input_contract != request.input_contract:
                    raise ValueError("remote response input contract mismatch")
                if parsed.model_state != "ready":
                    raise ValueError("remote model is not ready")
                return _decision(parsed)
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
        assert last_error is not None
        raise RemoteInferenceError(
            f"remote inference failed after {self.max_attempts} attempt(s): "
            f"{last_error.__class__.__name__}"
        ) from last_error

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()


class RemoteInferenceRouter:
    def __init__(
        self,
        *,
        mode: Literal["disabled", "approved"],
        approval_id: str | None,
        client: RemoteInferenceClient | None,
        failure_threshold: int,
        rollback_cooldown_seconds: int,
    ) -> None:
        if mode == "approved" and (not approval_id or client is None):
            raise ValueError("approved routing requires approval_id and client")
        self.mode = mode
        self.approval_id = approval_id
        self.client = client
        self.failure_threshold = failure_threshold
        self.rollback_cooldown_seconds = rollback_cooldown_seconds
        self.consecutive_failures = 0
        self.rollback_until: datetime | None = None
        self.last_error: str | None = None
        self._effective_target: Literal["edge-local", "server1"] = (
            "server1" if mode == "approved" else "edge-local"
        )

    async def infer(
        self,
        frame: AccelerationFrame,
        temperature: AxisSample,
        *,
        local: Callable[[], ModelDecision | None],
        now: datetime | None = None,
    ) -> RoutedInference | None:
        observed_at = _utc(now)
        if self.mode != "approved" or self._rollback_active(observed_at):
            decision = local()
            return (
                RoutedInference(decision, "edge-local")
                if decision is not None
                else None
            )

        assert self.client is not None
        try:
            decision = await self.client.infer(frame, temperature)
        except RemoteInferenceError as exc:
            self.consecutive_failures += 1
            self.last_error = str(exc)
            self._effective_target = "edge-local"
            if self.consecutive_failures >= self.failure_threshold:
                self.rollback_until = observed_at + timedelta(
                    seconds=self.rollback_cooldown_seconds
                )
            decision = local()
            return (
                RoutedInference(decision, "edge-local")
                if decision is not None
                else None
            )

        self.consecutive_failures = 0
        self.rollback_until = None
        self.last_error = None
        self._effective_target = "server1"
        return RoutedInference(decision, "server1")

    def status(self, *, now: datetime | None = None) -> InferenceRoutingStatus:
        observed_at = _utc(now)
        remaining = 0
        if self.rollback_until is not None:
            remaining = max(
                0,
                math.ceil((self.rollback_until - observed_at).total_seconds()),
            )
        rolled_back = remaining > 0
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
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    def _rollback_active(self, now: datetime) -> bool:
        if self.rollback_until is None:
            return False
        if now < self.rollback_until:
            return True
        self.rollback_until = None
        self.consecutive_failures = 0
        self.last_error = None
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


def _utc(value: datetime | None) -> datetime:
    observed = value or datetime.now(timezone.utc)
    return observed if observed.tzinfo is not None else observed.replace(tzinfo=timezone.utc)
