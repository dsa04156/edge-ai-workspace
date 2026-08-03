from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .models import AxisName, AxisSample


class LocalDataError(RuntimeError):
    """Base error for the Device Service Local Data boundary."""


class LocalDataResponseError(LocalDataError):
    """The Device Service returned data outside the v3 contract."""


class LocalDataUnavailable(LocalDataError):
    """The Device Service could not be reached or returned HTTP failure."""


@dataclass(frozen=True)
class AxisSource:
    axis: AxisName
    device_name: str
    resource_name: str

    @property
    def key(self) -> str:
        return self.axis


@dataclass(frozen=True)
class ScalarSource:
    name: str
    device_name: str
    resource_name: str

    @property
    def key(self) -> str:
        return self.name


LocalDataSource = AxisSource | ScalarSource


ACCELERATION_SOURCES: tuple[AxisSource, ...] = (
    AxisSource("x", "virtual-acceleration-x-001", "acceleration_x_raw"),
    AxisSource("y", "virtual-acceleration-y-001", "acceleration_y_raw"),
    AxisSource("z", "virtual-acceleration-z-001", "acceleration_z_raw"),
)

TEMPERATURE_SOURCE = ScalarSource(
    "temperature",
    "virtual-temperature-001",
    "temperature_raw",
)


class LocalDataClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
        )

    async def fetch(
        self,
        source: LocalDataSource,
        from_origin: int | None,
        to_origin: int,
    ) -> list[AxisSample]:
        device_name = quote(source.device_name, safe="")
        resource_name = quote(source.resource_name, safe="")
        path = (
            f"/api/v3/localdata/device/name/{device_name}/resource/name/{resource_name}"
        )
        params: dict[str, int] = {"to": to_origin, "limit": 1_000}
        if from_origin is not None:
            params["from"] = from_origin

        try:
            response = await self._client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise LocalDataUnavailable(
                f"Local Data request failed for {source.device_name}/{source.resource_name}"
            ) from exc
        return self._validated_samples(response, source)

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _validated_samples(
        response: httpx.Response,
        source: LocalDataSource,
    ) -> list[AxisSample]:
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise LocalDataResponseError(
                "Local Data response is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise LocalDataResponseError("Local Data response must be an object")
        if payload.get("apiVersion") != "v3":
            raise LocalDataResponseError("Local Data apiVersion must be v3")
        status_code = payload.get("statusCode")
        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or status_code < 200
            or status_code >= 300
        ):
            raise LocalDataResponseError("Local Data statusCode must be successful")
        if payload.get("deviceName") != source.device_name:
            raise LocalDataResponseError("Local Data deviceName does not match request")
        if payload.get("resourceName") != source.resource_name:
            raise LocalDataResponseError(
                "Local Data resourceName does not match request"
            )

        retention = payload.get("retention")
        if not isinstance(retention, dict):
            raise LocalDataResponseError("Local Data retention must be an object")
        max_age = retention.get("maxAge")
        max_samples = retention.get("maxSamples")
        if not isinstance(max_age, str) or not max_age:
            raise LocalDataResponseError("Local Data retention.maxAge must be text")
        if (
            isinstance(max_samples, bool)
            or not isinstance(max_samples, int)
            or max_samples <= 0
        ):
            raise LocalDataResponseError(
                "Local Data retention.maxSamples must be positive"
            )

        samples = payload.get("samples")
        count = payload.get("count")
        if not isinstance(samples, list):
            raise LocalDataResponseError("Local Data samples must be an array")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count != len(samples)
        ):
            raise LocalDataResponseError("Local Data count must match samples")

        validated: list[AxisSample] = []
        previous_origin: int | None = None
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                raise LocalDataResponseError(f"samples[{index}] must be an object")
            origin = sample.get("origin")
            value_type = sample.get("valueType")
            value = sample.get("value")
            if isinstance(origin, bool) or not isinstance(origin, int) or origin <= 0:
                raise LocalDataResponseError(
                    f"samples[{index}].origin must be positive"
                )
            if value_type == "Int32":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise LocalDataResponseError(
                        f"samples[{index}].value must be an integer for Int32"
                    )
            elif value_type == "Float64":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise LocalDataResponseError(
                        f"samples[{index}].value must be finite for Float64"
                    )
                value = float(value)
            else:
                raise LocalDataResponseError(
                    f"samples[{index}].valueType must be Int32 or Float64"
                )
            if previous_origin is not None and origin < previous_origin:
                raise LocalDataResponseError(
                    "Local Data samples must be origin ordered"
                )
            validated.append(
                AxisSample(origin=origin, value_type=value_type, value=value)
            )
            previous_origin = origin
        return validated
