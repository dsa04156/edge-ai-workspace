from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from .models import EdgeXDevice, TelemetryPoint


class EdgeXError(RuntimeError):
    """Base error for the authoritative EdgeX source boundary."""


class EdgeXBackendError(EdgeXError):
    """EdgeX could not be reached or returned an HTTP failure."""


class EdgeXResponseError(EdgeXError):
    """EdgeX returned a response that does not satisfy its v3 contract."""


class EdgeXClient:
    def __init__(
        self,
        core_metadata_url: str,
        core_data_url: str,
        timeout_seconds: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.core_metadata_url = core_metadata_url.rstrip("/")
        self.core_data_url = core_data_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def get_devices(self) -> list[EdgeXDevice]:
        payload = await self._get(self.core_metadata_url, "/api/v3/device/all")
        rows = self._envelope_list(payload, "devices")
        devices: list[EdgeXDevice] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EdgeXResponseError(f"devices[{index}] must be an object")
            protocols = row.get("protocols")
            if not isinstance(protocols, dict):
                raise EdgeXResponseError(f"devices[{index}].protocols must be an object")
            tags = self._object_field(row, "tags", index, default={})
            properties = self._object_field(row, "properties", index, default={})
            try:
                devices.append(
                    EdgeXDevice(
                        name=self._required_string(row, "name", f"devices[{index}]"),
                        description=self._optional_string(row, "description", f"devices[{index}]"),
                        profile_name=self._required_string(
                            row, "profileName", f"devices[{index}]"
                        ),
                        device_service_name=self._required_string(
                            row, "serviceName", f"devices[{index}]"
                        ),
                        protocol_names=sorted(protocols),
                        admin_state=self._required_string(
                            row, "adminState", f"devices[{index}]"
                        ),
                        operating_state=self._required_string(
                            row, "operatingState", f"devices[{index}]"
                        ),
                        tags=tags,
                        properties=properties,
                        node_name=self._node_name(tags, properties),
                    )
                )
            except ValidationError as exc:
                raise EdgeXResponseError(
                    f"devices[{index}] failed validation: {exc}"
                ) from exc
        return devices

    async def list_devices(self) -> list[EdgeXDevice]:
        return await self.get_devices()

    async def get_latest_event(self, device_name: str) -> list[TelemetryPoint]:
        events = await self._get_events(device_name, params={"offset": 0, "limit": 1})
        if not events:
            return []
        latest = max(events, key=self._event_origin)
        return self._flatten_event(latest, 0)

    async def get_latest_source_readings(
        self, device_name: str, *, event_limit: int = 20
    ) -> list[TelemetryPoint]:
        if event_limit <= 0:
            raise ValueError("event_limit must be positive")
        events = await self._get_events(
            device_name, params={"offset": 0, "limit": event_limit}
        )
        events.sort(key=self._event_origin, reverse=True)
        seen_sources: set[str] = set()
        points: list[TelemetryPoint] = []
        for index, event in enumerate(events):
            source_name = self._required_string(event, "sourceName", f"events[{index}]")
            if source_name in seen_sources:
                continue
            seen_sources.add(source_name)
            points.extend(self._flatten_event(event, index))
        return points

    async def get_event_history(
        self,
        device_name: str,
        *,
        offset: int = 0,
        limit: int = 100,
        start: int | datetime | None = None,
        end: int | datetime | None = None,
    ) -> list[TelemetryPoint]:
        if offset < 0 or limit <= 0:
            raise ValueError("offset must be non-negative and limit must be positive")
        params: dict[str, int] = {"offset": offset, "limit": limit}
        if start is not None:
            params["start"] = self._origin_parameter(start)
        if end is not None:
            params["end"] = self._origin_parameter(end)
        events = await self._get_events(device_name, params=params)
        events.sort(key=self._event_origin, reverse=True)
        points: list[TelemetryPoint] = []
        for index, event in enumerate(events):
            points.extend(self._flatten_event(event, index))
        return points

    async def get_history(
        self,
        device_name: str,
        *,
        offset: int = 0,
        limit: int = 100,
        start: int | datetime | None = None,
        end: int | datetime | None = None,
    ) -> list[TelemetryPoint]:
        return await self.get_event_history(
            device_name, offset=offset, limit=limit, start=start, end=end
        )

    async def _get_events(
        self, device_name: str, *, params: dict[str, int]
    ) -> list[dict[str, Any]]:
        encoded_name = quote(device_name, safe="")
        payload = await self._get(
            self.core_data_url,
            f"/api/v3/event/device/name/{encoded_name}",
            params=params,
        )
        rows = self._envelope_list(payload, "events")
        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EdgeXResponseError(f"events[{index}] must be an object")
            events.append(row)
        return events

    async def _get(
        self,
        base_url: str,
        path: str,
        *,
        params: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(f"{base_url}{path}", params=params)
                response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise EdgeXBackendError(f"EdgeX request failed for {path}: {exc}") from exc
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise EdgeXResponseError(f"EdgeX returned invalid JSON for {path}") from exc
        if not isinstance(payload, dict):
            raise EdgeXResponseError(f"EdgeX response for {path} must be an object")
        return payload

    @staticmethod
    def _envelope_list(payload: dict[str, Any], field: str) -> list[Any]:
        if payload.get("apiVersion") != "v3":
            raise EdgeXResponseError("EdgeX response apiVersion must be v3")
        status_code = payload.get("statusCode")
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise EdgeXResponseError("EdgeX response statusCode must be an integer")
        if status_code < 200 or status_code >= 300:
            message = payload.get("message") or "unknown EdgeX error"
            raise EdgeXResponseError(f"EdgeX statusCode {status_code}: {message}")
        value = payload.get(field)
        if not isinstance(value, list):
            raise EdgeXResponseError(f"EdgeX response {field} must be a list")
        total_count = payload.get("totalCount")
        if total_count is not None and (
            isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0
        ):
            raise EdgeXResponseError("EdgeX response totalCount must be a non-negative integer")
        return value

    def _flatten_event(self, event: dict[str, Any], event_index: int) -> list[TelemetryPoint]:
        context = f"events[{event_index}]"
        device_name = self._required_string(event, "deviceName", context)
        source_name = self._required_string(event, "sourceName", context)
        event_origin = self._event_origin(event)
        readings = event.get("readings")
        if not isinstance(readings, list):
            raise EdgeXResponseError(f"{context}.readings must be a list")
        event_id = self._optional_string(event, "id", context)
        points: list[TelemetryPoint] = []
        for reading_index, reading in enumerate(readings):
            reading_context = f"{context}.readings[{reading_index}]"
            if not isinstance(reading, dict):
                raise EdgeXResponseError(f"{reading_context} must be an object")
            value_type = self._required_string(reading, "valueType", reading_context)
            raw_value = reading.get("objectValue") if value_type == "Object" else reading.get("value")
            if value_type != "Object" and "value" not in reading:
                raise EdgeXResponseError(f"{reading_context}.value is required")
            origin = reading.get("origin", event_origin)
            try:
                origin_nanoseconds = _origin_as_int(origin)
                points.append(
                    TelemetryPoint(
                        device_name=device_name,
                        source_name=source_name,
                        resource_name=self._required_string(
                            reading, "resourceName", reading_context
                        ),
                        value_type=value_type,
                        value=self._typed_value(raw_value, value_type, reading_context),
                        timestamp=parse_edgex_origin(origin_nanoseconds),
                        origin=origin_nanoseconds,
                        event_id=event_id,
                        units=self._optional_string(reading, "units", reading_context),
                    )
                )
            except ValidationError as exc:
                raise EdgeXResponseError(f"{reading_context} failed validation: {exc}") from exc
            except (TypeError, ValueError) as exc:
                raise EdgeXResponseError(
                    f"{reading_context}.origin must be an integer nanosecond timestamp"
                ) from exc
        return points

    @staticmethod
    def _event_origin(event: dict[str, Any]) -> int:
        origin = event.get("origin")
        try:
            return _origin_as_int(origin)
        except (TypeError, ValueError) as exc:
            raise EdgeXResponseError("event origin must be an integer nanosecond timestamp") from exc

    @staticmethod
    def _typed_value(value: Any, value_type: str, context: str) -> Any:
        try:
            if value_type == "Bool":
                if isinstance(value, bool):
                    return value
                normalized = str(value).lower()
                if normalized not in {"true", "false"}:
                    raise ValueError("invalid Bool")
                return normalized == "true"
            if value_type.startswith("Int") or value_type.startswith("Uint"):
                return int(value)
            if value_type.startswith("Float"):
                return float(value)
            if value_type == "Object":
                return json.loads(value) if isinstance(value, str) else value
            if value is None:
                return None
            return str(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EdgeXResponseError(
                f"{context}.value is invalid for valueType {value_type}"
            ) from exc

    @classmethod
    def _node_name(cls, tags: dict[str, Any], properties: dict[str, Any]) -> str | None:
        for values in (tags, properties):
            found = cls._find_node_name(values)
            if found is not None:
                return found
        return None

    @classmethod
    def _find_node_name(cls, values: dict[str, Any]) -> str | None:
        for key, value in values.items():
            normalized = key.replace("_", "").replace("-", "").lower()
            if normalized in {"nodename", "kubernetesnode", "kubeedgenode"}:
                if isinstance(value, str) and value.strip():
                    return value.strip()
            if isinstance(value, dict):
                nested = cls._find_node_name(value)
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _required_string(row: dict[str, Any], field: str, context: str) -> str:
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise EdgeXResponseError(f"{context}.{field} must be a non-empty string")
        return value

    @staticmethod
    def _optional_string(row: dict[str, Any], field: str, context: str) -> str | None:
        value = row.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise EdgeXResponseError(f"{context}.{field} must be a string")
        return value

    @staticmethod
    def _object_field(
        row: dict[str, Any], field: str, index: int, *, default: dict[str, Any]
    ) -> dict[str, Any]:
        value = row.get(field, default)
        if value is None:
            return default
        if not isinstance(value, dict):
            raise EdgeXResponseError(f"devices[{index}].{field} must be an object")
        return value

    @staticmethod
    def _origin_parameter(value: int | datetime) -> int:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("history datetime bounds must be timezone-aware")
            utc_value = value.astimezone(timezone.utc)
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            delta = utc_value - epoch
            return (
                (delta.days * 86_400 + delta.seconds) * 1_000_000_000
                + delta.microseconds * 1_000
            )
        return _origin_as_int(value)


def _origin_as_int(origin: Any) -> int:
    if isinstance(origin, bool):
        raise TypeError("boolean is not an origin")
    if isinstance(origin, int):
        return origin
    if isinstance(origin, str) and origin.strip():
        return int(origin)
    raise TypeError("origin must be an integer or integer string")


def parse_edgex_origin(origin: int | str) -> datetime:
    """Convert an EdgeX nanosecond Unix origin to a timezone-aware UTC datetime."""
    nanoseconds = _origin_as_int(origin)
    seconds, remainder = divmod(nanoseconds, 1_000_000_000)
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=seconds, microseconds=remainder // 1_000
    )
