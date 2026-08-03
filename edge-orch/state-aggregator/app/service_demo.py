from __future__ import annotations

from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from .service_demo_models import (
    ServiceDemoAxisValues,
    ServiceDemoBinding,
    ServiceDemoComponentScores,
    ServiceDemoCounters,
    ServiceDemoLatest,
    ServiceDemoModel,
    ServiceDemoScoreWeights,
    ServiceDemoState,
    ServiceDemoTemperatureFeatures,
    ServiceDemoVibrationFeatures,
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
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(f"{self.base_url}/api/v1/status")
                response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise ServiceDemoBackendError("sensor anomaly demo request failed") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceDemoResponseError(
                "sensor anomaly demo returned invalid JSON"
            ) from exc
        try:
            upstream = UpstreamServiceStatus.model_validate(payload)
        except ValidationError as exc:
            raise ServiceDemoResponseError(
                "sensor anomaly demo response failed validation"
            ) from exc
        return self._normalize(upstream)

    @staticmethod
    def _normalize(upstream: UpstreamServiceStatus) -> ServiceDemoState:
        latest = None
        if upstream.latest is not None:
            latest = ServiceDemoLatest(
                origin=upstream.latest.origin,
                observed_at=upstream.latest.observed_at,
                values=ServiceDemoAxisValues(
                    x=upstream.latest.values.x,
                    y=upstream.latest.values.y,
                    z=upstream.latest.values.z,
                ),
                magnitude=upstream.latest.magnitude,
                score=upstream.latest.score,
                anomaly=upstream.latest.anomaly,
                component_scores=(
                    ServiceDemoComponentScores(
                        **upstream.latest.component_scores.model_dump()
                    )
                    if upstream.latest.component_scores is not None
                    else None
                ),
                weights=(
                    ServiceDemoScoreWeights(
                        **upstream.latest.weights.model_dump()
                    )
                    if upstream.latest.weights is not None
                    else None
                ),
                vibration_features=(
                    ServiceDemoVibrationFeatures(
                        **upstream.latest.vibration_features.model_dump()
                    )
                    if upstream.latest.vibration_features is not None
                    else None
                ),
                temperature_features=(
                    ServiceDemoTemperatureFeatures(
                        **upstream.latest.temperature_features.model_dump()
                    )
                    if upstream.latest.temperature_features is not None
                    else None
                ),
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
