from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError

from .device_management_edgex import (
    EdgeXManagementClient,
    EdgeXManagementError,
)
from .device_source_models import (
    DeviceSourceBinding,
    DeviceSourceBindingRequest,
    DeviceSourceCatalogDocument,
    DeviceSourceEndpoint,
    DeviceSourceReadMode,
    DeviceSourceRetention,
    DeviceSourceSample,
    DeviceSourceSampleResponse,
)
from .edgex import EdgeXClient, EdgeXError, parse_edgex_origin


class DeviceSourceBindingError(RuntimeError):
    status_code = 500
    code = "device_source_error"


class DeviceSourceNotFoundError(DeviceSourceBindingError):
    status_code = 404
    code = "device_source_not_found"


class DeviceSourceUnavailableError(DeviceSourceBindingError):
    status_code = 409
    code = "device_source_unavailable"


class DeviceSourceUpstreamError(DeviceSourceBindingError):
    status_code = 502
    code = "device_source_upstream_error"


class DeviceSourceCatalog:
    def __init__(self, document: DeviceSourceCatalogDocument) -> None:
        self.version = document.version
        self.services = document.services
        self._by_service = {item.service_name: item for item in self.services}
        if len(self._by_service) != len(self.services):
            raise ValueError("device source serviceName values must be unique")
        for endpoint in self.services:
            self._validate_base_url(endpoint.base_url)

    @classmethod
    def load(cls, path: Path) -> "DeviceSourceCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(DeviceSourceCatalogDocument.model_validate(payload))

    def endpoint_for(self, service_name: str) -> DeviceSourceEndpoint | None:
        return self._by_service.get(service_name)

    def read_modes_for(self, service_name: str) -> list[DeviceSourceReadMode]:
        endpoint = self.endpoint_for(service_name)
        local_modes: list[DeviceSourceReadMode] = (
            list(endpoint.read_modes) if endpoint is not None else []
        )
        return [*local_modes, "history"]

    @staticmethod
    def _validate_base_url(value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("device source baseUrl must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("device source baseUrl must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("device source baseUrl must not contain query or fragment")
        if parsed.path not in {"", "/"}:
            raise ValueError("device source baseUrl must not contain a path")


class DeviceSourceBindingService:
    def __init__(
        self,
        catalog: DeviceSourceCatalog,
        metadata: EdgeXManagementClient,
        core_data: EdgeXClient,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.catalog = catalog
        self.metadata = metadata
        self.core_data = core_data
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.now_ns = now_ns

    async def sample(
        self, request: DeviceSourceBindingRequest
    ) -> DeviceSourceSampleResponse:
        device, resource = await self._resolve_binding(request)
        profile_name = self._required_text(device, "profileName", "device")
        service_name = self._required_text(device, "serviceName", "device")
        node_name = self._node_name(device)
        binding = DeviceSourceBinding(
            device_name=request.device_name,
            resource_name=request.resource_name,
            read_mode=request.read_mode,
            window=request.window,
            limit=request.limit,
            profile_name=profile_name,
            device_service_name=service_name,
            node_name=node_name,
            admin_state=self._required_text(device, "adminState", "device"),
            operating_state=self._required_text(device, "operatingState", "device"),
        )
        expected_type, units = self._resource_contract(resource)

        if request.read_mode == "history":
            return await self._history_sample(
                request,
                binding,
                expected_type=expected_type,
                units=units,
            )
        return await self._local_sample(
            request,
            binding,
            expected_type=expected_type,
            units=units,
        )

    async def _resolve_binding(
        self, request: DeviceSourceBindingRequest
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            device = await self.metadata.get_device(request.device_name)
        except EdgeXManagementError as exc:
            raise DeviceSourceUpstreamError(
                "EdgeX Core Metadata device lookup failed"
            ) from exc
        if device is None:
            raise DeviceSourceNotFoundError(
                f"EdgeX device {request.device_name!r} was not found"
            )

        profile_name = self._required_text(device, "profileName", "device")
        try:
            profile = await self.metadata.get_profile(profile_name)
        except EdgeXManagementError as exc:
            raise DeviceSourceUpstreamError(
                "EdgeX Core Metadata profile lookup failed"
            ) from exc
        if profile is None:
            raise DeviceSourceNotFoundError(
                f"EdgeX Device Profile {profile_name!r} was not found"
            )
        resources = profile.get("deviceResources")
        if not isinstance(resources, list):
            raise DeviceSourceUpstreamError(
                "EdgeX Device Profile deviceResources is not an array"
            )
        matches = [
            resource
            for resource in resources
            if isinstance(resource, dict)
            and resource.get("name") == request.resource_name
        ]
        if not matches:
            raise DeviceSourceNotFoundError(
                f"resource {request.resource_name!r} is not in profile {profile_name!r}"
            )
        if len(matches) != 1:
            raise DeviceSourceUpstreamError(
                "EdgeX Device Profile contains duplicate resource names"
            )
        return device, matches[0]

    async def _history_sample(
        self,
        request: DeviceSourceBindingRequest,
        binding: DeviceSourceBinding,
        *,
        expected_type: str,
        units: str | None,
    ) -> DeviceSourceSampleResponse:
        now_origin = self.now_ns()
        start_origin = now_origin - self._window_seconds(request.window) * 1_000_000_000
        try:
            points = await self.core_data.get_event_history(
                request.device_name,
                limit=request.limit,
                start=start_origin,
                end=now_origin,
            )
        except EdgeXError as exc:
            raise DeviceSourceUpstreamError(
                "EdgeX Core Data history lookup failed"
            ) from exc

        samples: list[DeviceSourceSample] = []
        for point in points:
            if point.resource_name != request.resource_name:
                continue
            if point.value_type != expected_type:
                raise DeviceSourceUpstreamError(
                    "Core Data Reading valueType does not match the current Device Profile"
                )
            samples.append(
                DeviceSourceSample(
                    origin=point.origin,
                    timestamp=point.timestamp,
                    resource_name=point.resource_name,
                    value_type=point.value_type,
                    value=point.value,
                    source_name=point.source_name,
                    event_id=point.event_id,
                    units=point.units or units,
                )
            )
        samples.sort(key=lambda item: item.origin)
        samples = samples[-request.limit :]
        return DeviceSourceSampleResponse(
            sampled_at=datetime.now(timezone.utc),
            source_kind="edgex_core_data",
            durable=True,
            binding=binding,
            samples=samples,
        )

    async def _local_sample(
        self,
        request: DeviceSourceBindingRequest,
        binding: DeviceSourceBinding,
        *,
        expected_type: str,
        units: str | None,
    ) -> DeviceSourceSampleResponse:
        endpoint = self.catalog.endpoint_for(binding.device_service_name)
        if endpoint is None or request.read_mode not in endpoint.read_modes:
            raise DeviceSourceUnavailableError(
                f"Device Service {binding.device_service_name!r} has no verified "
                f"{request.read_mode} Local Data binding"
            )
        if binding.node_name and binding.node_name != endpoint.node_name:
            raise DeviceSourceUnavailableError(
                "Device node identity does not match the verified Local Data endpoint"
            )

        device_name = quote(request.device_name, safe="")
        resource_name = quote(request.resource_name, safe="")
        path = (
            f"/api/v3/localdata/device/name/{device_name}/"
            f"resource/name/{resource_name}"
        )
        params: dict[str, int] | None = None
        if request.read_mode == "local_latest":
            path += "/latest"
        else:
            to_origin = self.now_ns()
            params = {
                "from": to_origin
                - self._window_seconds(request.window) * 1_000_000_000,
                "to": to_origin,
                "limit": request.limit,
            }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    f"{endpoint.base_url.rstrip('/')}{path}",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise DeviceSourceUpstreamError(
                "Device Service Local Data request failed"
            ) from exc

        retention, samples = self._validate_local_response(
            response,
            request,
            expected_type=expected_type,
            units=units,
        )
        return DeviceSourceSampleResponse(
            sampled_at=datetime.now(timezone.utc),
            source_kind="device_service_local_cache",
            durable=False,
            binding=binding,
            retention=retention,
            samples=samples,
        )

    def _validate_local_response(
        self,
        response: httpx.Response,
        request: DeviceSourceBindingRequest,
        *,
        expected_type: str,
        units: str | None,
    ) -> tuple[DeviceSourceRetention, list[DeviceSourceSample]]:
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise DeviceSourceUpstreamError(
                "Device Service Local Data response is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise DeviceSourceUpstreamError(
                "Device Service Local Data response must be an object"
            )
        if payload.get("apiVersion") != "v3":
            raise DeviceSourceUpstreamError(
                "Device Service Local Data apiVersion must be v3"
            )
        status_code = payload.get("statusCode")
        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 200 <= status_code < 300
        ):
            raise DeviceSourceUpstreamError(
                "Device Service Local Data statusCode must be successful"
            )
        if payload.get("deviceName") != request.device_name:
            raise DeviceSourceUpstreamError(
                "Device Service Local Data deviceName does not match the binding"
            )
        if payload.get("resourceName") != request.resource_name:
            raise DeviceSourceUpstreamError(
                "Device Service Local Data resourceName does not match the binding"
            )

        retention_payload = payload.get("retention")
        if not isinstance(retention_payload, dict):
            raise DeviceSourceUpstreamError(
                "Device Service Local Data retention must be an object"
            )
        try:
            retention = DeviceSourceRetention.model_validate(retention_payload)
        except ValidationError as exc:
            raise DeviceSourceUpstreamError(
                "Device Service Local Data retention is invalid"
            ) from exc

        rows = payload.get("samples")
        count = payload.get("count")
        if not isinstance(rows, list):
            raise DeviceSourceUpstreamError(
                "Device Service Local Data samples must be an array"
            )
        if isinstance(count, bool) or not isinstance(count, int) or count != len(rows):
            raise DeviceSourceUpstreamError(
                "Device Service Local Data count must match samples"
            )
        if request.read_mode == "local_latest" and len(rows) > 1:
            raise DeviceSourceUpstreamError(
                "Device Service Local Data latest response must contain at most one sample"
            )

        samples: list[DeviceSourceSample] = []
        previous_origin: int | None = None
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise DeviceSourceUpstreamError(
                    f"Device Service Local Data samples[{index}] must be an object"
                )
            origin = row.get("origin")
            value_type = row.get("valueType")
            value = row.get("value")
            if isinstance(origin, bool) or not isinstance(origin, int) or origin <= 0:
                raise DeviceSourceUpstreamError(
                    f"Device Service Local Data samples[{index}].origin must be positive"
                )
            if value_type != expected_type:
                raise DeviceSourceUpstreamError(
                    "Device Service Local Data valueType does not match the Device Profile"
                )
            self._validate_typed_value(value_type, value, index)
            if previous_origin is not None and origin < previous_origin:
                raise DeviceSourceUpstreamError(
                    "Device Service Local Data samples must be origin ordered"
                )
            samples.append(
                DeviceSourceSample(
                    origin=origin,
                    timestamp=parse_edgex_origin(origin),
                    resource_name=request.resource_name,
                    value_type=value_type,
                    value=value,
                    units=units,
                )
            )
            previous_origin = origin
        return retention, samples

    @staticmethod
    def _resource_contract(resource: dict[str, Any]) -> tuple[str, str | None]:
        properties = resource.get("properties")
        if not isinstance(properties, dict):
            raise DeviceSourceUpstreamError(
                "EdgeX Device Profile resource properties must be an object"
            )
        value_type = properties.get("valueType")
        if not isinstance(value_type, str) or not value_type:
            raise DeviceSourceUpstreamError(
                "EdgeX Device Profile resource valueType is required"
            )
        read_write = properties.get("readWrite", "R")
        if read_write not in {"R", "RW"}:
            raise DeviceSourceUnavailableError(
                "selected Device Profile resource is not readable"
            )
        units = properties.get("units")
        if units is not None and not isinstance(units, str):
            raise DeviceSourceUpstreamError(
                "EdgeX Device Profile resource units must be text"
            )
        return value_type, units or None

    @staticmethod
    def _validate_typed_value(value_type: str, value: Any, index: int) -> None:
        valid = True
        if value_type == "Bool":
            valid = isinstance(value, bool)
        elif value_type.startswith("Int"):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif value_type.startswith("Uint"):
            valid = (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            )
        elif value_type.startswith("Float"):
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            )
        elif value_type == "String":
            valid = isinstance(value, str)
        else:
            valid = False
        if not valid:
            raise DeviceSourceUpstreamError(
                f"Device Service Local Data samples[{index}].value is invalid "
                f"for {value_type}"
            )

    @staticmethod
    def _window_seconds(window: str) -> int:
        match = re.fullmatch(r"-([1-9][0-9]*)([smhdw])", window)
        if match is None:
            raise DeviceSourceUnavailableError(
                "window must be a negative duration such as -10s"
            )
        amount = int(match.group(1))
        return amount * {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }[match.group(2)]

    @staticmethod
    def _required_text(row: dict[str, Any], name: str, context: str) -> str:
        value = row.get(name)
        if not isinstance(value, str) or not value:
            raise DeviceSourceUpstreamError(f"{context}.{name} must be text")
        return value

    @staticmethod
    def _node_name(device: dict[str, Any]) -> str | None:
        for values in (device.get("tags"), device.get("properties")):
            if not isinstance(values, dict):
                continue
            for key in ("nodeName", "node_name", "kubernetesNode"):
                value = values.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            placement = values.get("placement")
            if isinstance(placement, dict):
                value = placement.get("kubernetesNode")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None
