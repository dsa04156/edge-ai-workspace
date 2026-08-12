from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import ValidationError

from .service_demo_models import (
    ServiceDemoAlertState,
    ServiceDemoAlertTransition,
    ServiceDemoAxisValues,
    ServiceDemoBinding,
    ServiceDemoComponentScores,
    ServiceDemoCounters,
    ServiceDemoLatest,
    ServiceDemoModel,
    ServiceDemoResultState,
    ServiceDemoScoreWeights,
    ServiceDemoState,
    ServiceDemoTemperatureFeatures,
    ServiceDemoVibrationFeatures,
    UpstreamAlertEnvelope,
    UpstreamLatest,
    UpstreamResultEnvelope,
    UpstreamServiceStatus,
)

DEMO_INPUT_DEVICES = [
    "virtual-acceleration-x-001",
    "virtual-acceleration-y-001",
    "virtual-acceleration-z-001",
    "virtual-temperature-001",
]


class ServiceDemoError(RuntimeError):
    """Base error for live sensor demo observation."""


class ServiceDemoBackendError(ServiceDemoError):
    """The demo service could not be reached or returned HTTP failure."""


class ServiceDemoResponseError(ServiceDemoError):
    """The demo service returned data outside its v1 contract."""


class ServiceDemoClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def get_state(self) -> ServiceDemoState:
        payload = await self._request("/api/v1/status")
        try:
            upstream = UpstreamServiceStatus.model_validate(payload)
        except ValidationError as exc:
            raise ServiceDemoResponseError(
                "sensor anomaly demo response failed validation"
            ) from exc
        return self._normalize(upstream)

    async def get_results(
        self,
        *,
        limit: int,
        anomaly: bool | None = None,
    ) -> ServiceDemoResultState:
        parameters: dict[str, Any] = {"limit": limit}
        if anomaly is not None:
            parameters["anomaly"] = str(anomaly).lower()
        payload = await self._request("/api/v1/results", params=parameters)
        try:
            upstream = UpstreamResultEnvelope.model_validate(payload)
        except ValidationError as exc:
            raise ServiceDemoResponseError(
                "sensor anomaly result response failed validation"
            ) from exc
        return ServiceDemoResultState(
            generated_at=datetime.now(timezone.utc),
            mode="live",
            count=upstream.count,
            results=[self._latest(row) for row in upstream.results],
        )

    async def get_alerts(self, *, limit: int) -> ServiceDemoAlertState:
        payload = await self._request("/api/v1/alerts", params={"limit": limit})
        try:
            upstream = UpstreamAlertEnvelope.model_validate(payload)
        except ValidationError as exc:
            raise ServiceDemoResponseError(
                "sensor anomaly alert response failed validation"
            ) from exc
        return ServiceDemoAlertState(
            generated_at=datetime.now(timezone.utc),
            mode="live",
            count=upstream.count,
            alerts=[
                ServiceDemoAlertTransition(**row.model_dump())
                for row in upstream.alerts
            ],
        )

    async def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    params=params,
                )
                response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ServiceDemoBackendError("sensor anomaly demo request failed") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceDemoResponseError(
                "sensor anomaly demo returned invalid JSON"
            ) from exc

    @staticmethod
    def _normalize(upstream: UpstreamServiceStatus) -> ServiceDemoState:
        latest = (
            ServiceDemoClient._latest(upstream.latest)
            if upstream.latest is not None
            else None
        )
        return ServiceDemoState(
            generated_at=datetime.now(timezone.utc),
            mode="live",
            status=upstream.status,
            input_state=upstream.input_state,
            model_state=upstream.model_state,
            binding=ServiceDemoBinding(
                physical_source=upstream.source.physical_source,
                device_service=upstream.source.device_service,
                devices=upstream.source.devices,
            ),
            latest=latest,
            model=ServiceDemoModel(**upstream.model.model_dump()),
            counters=ServiceDemoCounters(**upstream.counters.model_dump()),
            last_error=upstream.last_error,
        )

    @staticmethod
    def _latest(upstream: UpstreamLatest) -> ServiceDemoLatest:
        return ServiceDemoLatest(
            origin=upstream.origin,
            observed_at=upstream.observed_at,
            values=ServiceDemoAxisValues(
                x=upstream.values.x,
                y=upstream.values.y,
                z=upstream.values.z,
            ),
            magnitude=upstream.magnitude,
            score=upstream.score,
            anomaly=upstream.anomaly,
            model_version=upstream.model_version,
            input_contract=upstream.input_contract,
            component_scores=(
                ServiceDemoComponentScores(**upstream.component_scores.model_dump())
                if upstream.component_scores is not None
                else None
            ),
            weights=(
                ServiceDemoScoreWeights(**upstream.weights.model_dump())
                if upstream.weights is not None
                else None
            ),
            vibration_features=(
                ServiceDemoVibrationFeatures(**upstream.vibration_features.model_dump())
                if upstream.vibration_features is not None
                else None
            ),
            temperature_features=(
                ServiceDemoTemperatureFeatures(
                    **upstream.temperature_features.model_dump()
                )
                if upstream.temperature_features is not None
                else None
            ),
        )


def degraded_service_demo_state(exc: Exception) -> ServiceDemoState:
    return ServiceDemoState(
        generated_at=datetime.now(timezone.utc),
        mode="unavailable",
        status="degraded",
        input_state="error",
        model_state="unavailable",
        binding=ServiceDemoBinding(devices=DEMO_INPUT_DEVICES),
        counters=ServiceDemoCounters(),
        observation_error=(
            f"sensor anomaly demo unavailable: {exc.__class__.__name__}"
        ),
    )


def degraded_service_demo_results(exc: Exception) -> ServiceDemoResultState:
    return ServiceDemoResultState(
        generated_at=datetime.now(timezone.utc),
        mode="unavailable",
        count=0,
        observation_error=(
            f"sensor anomaly results unavailable: {exc.__class__.__name__}"
        ),
    )


def degraded_service_demo_alerts(exc: Exception) -> ServiceDemoAlertState:
    return ServiceDemoAlertState(
        generated_at=datetime.now(timezone.utc),
        mode="unavailable",
        count=0,
        observation_error=(
            f"sensor anomaly alerts unavailable: {exc.__class__.__name__}"
        ),
    )
