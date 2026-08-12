from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from .models import (
    EdgeXDevice,
    EdgeXDeviceProfile,
    EdgeXDeviceResource,
    EventHistoryPage,
    TelemetryPoint,
)

MAX_EVENT_QUERY_PAGE_SIZE = 100
MAX_EVENT_QUERY_PAGES = 10
MAX_EVENTS_PER_DEVICE = 1000
MAX_PRIOR_PROBE_EVENTS_PER_DEVICE = 200



class EdgeXError(RuntimeError):
    """Base error for the authoritative EdgeX source boundary."""

    def __init__(
        self,
        message: str,
        *,
        operation: str = "unknown",
        identity: str | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.identity = identity
        self.status_code = status_code
        self.retryable = retryable


class EdgeXNotFoundError(EdgeXError):
    """The requested authoritative entity is absent for this operation."""


class EdgeXHTTPStatusError(EdgeXError):
    """EdgeX returned a non-success HTTP status."""


class EdgeXTransportError(EdgeXError):
    """EdgeX could not be reached."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, retryable=True, **kwargs)


class EdgeXBackendError(EdgeXTransportError):
    """Backward-compatible transport error alias."""


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
        payload = await self._get(
            self.core_metadata_url,
            "/api/v3/device/all",
            operation="inventory",
        )
        rows, _ = self._envelope_list(payload, "devices", operation="inventory")
        devices: list[EdgeXDevice] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EdgeXResponseError(
                    f"devices[{index}] must be an object",
                    operation="inventory",
                )
            protocols = row.get("protocols")
            if not isinstance(protocols, dict):
                raise EdgeXResponseError(
                    f"devices[{index}].protocols must be an object",
                    operation="inventory",
                    identity=self._optional_string(
                        row, "name", f"devices[{index}]"
                    ),
                )
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
                    f"devices[{index}] failed validation: {exc}",
                    operation="inventory",
                    identity=row.get("name") if isinstance(row.get("name"), str) else None,
                ) from exc
        return devices
    async def get_device_profile(self, profile_name: str) -> EdgeXDeviceProfile:
        encoded_name = quote(profile_name, safe="")
        payload = await self._get(
            self.core_metadata_url,
            f"/api/v3/deviceprofile/name/{encoded_name}",
            operation="profile",
            identity=profile_name,
        )
        profile = self._envelope_object(
            payload, "profile", operation="profile", identity=profile_name
        )
        resources = profile.get("deviceResources")
        if not isinstance(resources, list):
            raise EdgeXResponseError(
                "EdgeX profile deviceResources must be a list",
                operation="profile",
                identity=profile_name,
            )
        parsed_resources: list[EdgeXDeviceResource] = []
        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                raise EdgeXResponseError(
                    f"deviceResources[{index}] must be an object",
                    operation="profile",
                    identity=profile_name,
                )
            parsed_resources.append(
                EdgeXDeviceResource(
                    name=self._required_string(
                        resource,
                        "name",
                        f"deviceResources[{index}]",
                        operation="profile",
                        identity=profile_name,
                    )
                )
            )
        try:
            parsed_profile = EdgeXDeviceProfile(
                name=self._required_string(
                    profile,
                    "name",
                    "profile",
                    operation="profile",
                    identity=profile_name,
                ),
                device_resources=parsed_resources,
            )
            if parsed_profile.name != profile_name:
                raise EdgeXResponseError(
                    "EdgeX profile name does not match the requested identity",
                    operation="profile",
                    identity=profile_name,
                )
            return parsed_profile
        except ValidationError as exc:
            raise EdgeXResponseError(
                "EdgeX profile failed validation",
                operation="profile",
                identity=profile_name,
            ) from exc

    async def get_bounded_event_history(
        self,
        device_name: str,
        *,
        observation_time: int | datetime,
        freshness_seconds: int,
        page_size: int,
        max_pages: int,
        max_events_per_device: int,
        max_prior_probe_events_per_device: int,
    ) -> EventHistoryPage:
        if freshness_seconds <= 0 or page_size < 1 or page_size > MAX_EVENT_QUERY_PAGE_SIZE:
            raise ValueError("freshness and page size must be within hard bounds")
        if max_pages < 1 or max_pages > MAX_EVENT_QUERY_PAGES:
            raise ValueError("max_pages must be within hard bounds")
        if max_events_per_device < 1 or max_events_per_device > MAX_EVENTS_PER_DEVICE:
            raise ValueError("max_events_per_device must be within hard bounds")
        if (
            max_prior_probe_events_per_device < 1
            or max_prior_probe_events_per_device > MAX_PRIOR_PROBE_EVENTS_PER_DEVICE
        ):
            raise ValueError(
                "max_prior_probe_events_per_device must be within hard bounds"
            )
        end = self._origin_parameter(observation_time)
        start = end - freshness_seconds * 1_000_000_000
        points: list[TelemetryPoint] = []
        pages_scanned = 0
        events_scanned = 0
        total_count: int | None = None
        history_truncated = False
        for page in range(max_pages):
            offset = page * page_size
            events, page_total = await self._get_events_page(
                device_name,
                params={"offset": offset, "limit": page_size, "start": start, "end": end},
            )
            if total_count is None:
                total_count = page_total
            elif total_count != page_total:
                history_truncated = True
            if len(events) > page_size or offset + len(events) > page_total:
                history_truncated = True
            pages_scanned += 1
            remaining = max_events_per_device - events_scanned
            if remaining <= 0:
                history_truncated = True
                break
            accepted = events[:remaining]
            events_scanned += len(accepted)
            for index, event in enumerate(accepted):
                points.extend(
                    self._flatten_history_event(event, index, device_name)
                )
            if len(events) > remaining or events_scanned < page_total and page + 1 >= max_pages:
                history_truncated = True
            if len(events) < page_size or events_scanned >= page_total:
                break
        if total_count is None:
            total_count = 0
        if events_scanned < total_count:
            history_truncated = True

        prior_probe_events: list[TelemetryPoint] = []
        points.sort(
            key=lambda point: (
                -(point.reading_origin or point.origin),
                -(point.event_origin or point.origin),
                point.event_id or "",
            )
        )
        return EventHistoryPage(
            total_count=total_count,
            events=points,
            history_truncated=history_truncated,
            pages_scanned=pages_scanned,
            events_scanned=events_scanned,
            prior_probe_events=prior_probe_events,
        )

    async def get_prior_event_history(
        self,
        device_name: str,
        *,
        before: int | datetime,
        limit: int,
    ) -> EventHistoryPage:
        if limit < 1 or limit > MAX_PRIOR_PROBE_EVENTS_PER_DEVICE:
            raise ValueError("prior probe limit must be within hard bounds")
        events, total_count = await self._get_events_page(
            device_name,
            params={"offset": 0, "limit": limit, "end": self._origin_parameter(before)},
        )
        over_limit = len(events) > limit
        accepted_events = events[:limit]
        points = [
            point
            for index, event in enumerate(accepted_events)
            for point in self._flatten_history_event(event, index, device_name)
        ]
        sorted_points = sorted(
            points,
            key=lambda point: (
                -(point.reading_origin or point.origin),
                -(point.event_origin or point.origin),
                point.event_id or "",
            ),
        )
        return EventHistoryPage(
            total_count=total_count,
            events=sorted_points,
            events_scanned=len(accepted_events),
            history_truncated=over_limit or len(events) != total_count,
        )

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
        events, _ = await self._get_events_page(device_name, params=params)
        return events

    async def _get_events_page(
        self, device_name: str, *, params: dict[str, int]
    ) -> tuple[list[dict[str, Any]], int]:
        encoded_name = quote(device_name, safe="")
        payload = await self._get(
            self.core_data_url,
            f"/api/v3/event/device/name/{encoded_name}",
            params=params,
            operation="events",
            identity=device_name,
        )
        rows, total_count = self._envelope_list(
            payload, "events", operation="events", identity=device_name
        )
        events: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EdgeXResponseError(
                    f"events[{index}] must be an object",
                    operation="events",
                    identity=device_name,
                )
            events.append(row)
        return events, total_count

    async def _get(
        self,
        base_url: str,
        path: str,
        *,
        params: dict[str, int] | None = None,
        operation: str,
        identity: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(f"{base_url}{path}", params=params)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            error_class = EdgeXNotFoundError if status_code == 404 else EdgeXHTTPStatusError
            raise error_class(
                f"EdgeX HTTP {status_code} for {operation}",
                operation=operation,
                identity=identity,
                status_code=status_code,
                retryable=status_code == 429 or status_code >= 500,
            ) from exc
        except httpx.RequestError as exc:
            raise EdgeXBackendError(
                f"EdgeX request failed for {operation}: {exc}",
                operation=operation,
                identity=identity,
            ) from exc
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise EdgeXResponseError(
                f"EdgeX returned invalid JSON for {operation}",
                operation=operation,
                identity=identity,
            ) from exc
        if not isinstance(payload, dict):
            raise EdgeXResponseError(
                f"EdgeX response for {operation} must be an object",
                operation=operation,
                identity=identity,
            )
        return payload

    @staticmethod
    def _envelope_list(
        payload: dict[str, Any],
        field: str,
        *,
        operation: str = "unknown",
        identity: str | None = None,
    ) -> tuple[list[Any], int]:
        if payload.get("apiVersion") != "v3":
            raise EdgeXResponseError(
                "EdgeX response apiVersion must be v3",
                operation=operation,
                identity=identity,
            )
        status_code = payload.get("statusCode")
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise EdgeXResponseError(
                "EdgeX response statusCode must be an integer",
                operation=operation,
                identity=identity,
            )
        if status_code < 200 or status_code >= 300:
            error_class = EdgeXNotFoundError if status_code == 404 else EdgeXHTTPStatusError
            raise error_class(
                f"EdgeX statusCode {status_code}",
                operation=operation,
                identity=identity,
                status_code=status_code,
                retryable=status_code == 429 or status_code >= 500,
            )
        value = payload.get(field)
        if not isinstance(value, list):
            raise EdgeXResponseError(
                f"EdgeX response {field} must be a list",
                operation=operation,
                identity=identity,
            )
        total_count = payload.get("totalCount", len(value))
        if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
            raise EdgeXResponseError(
                "EdgeX response totalCount must be a non-negative integer",
                operation=operation,
                identity=identity,
            )
        return value, total_count

    @staticmethod
    def _envelope_object(
        payload: dict[str, Any],
        field: str,
        *,
        operation: str,
        identity: str | None,
    ) -> dict[str, Any]:
        values, _ = EdgeXClient._envelope_list(
            {**payload, field: [payload.get(field)]},
            field,
            operation=operation,
            identity=identity,
        )
        if len(values) != 1 or not isinstance(values[0], dict):
            raise EdgeXResponseError(
                f"EdgeX response {field} must be an object",
                operation=operation,
                identity=identity,
            )
        return values[0]

    def _flatten_history_event(
        self,
        event: dict[str, Any],
        event_index: int,
        device_name: str,
    ) -> list[TelemetryPoint]:
        try:
            return self._flatten_event(
                event,
                event_index,
                allow_incomplete_provenance=True,
            )
        except EdgeXResponseError as exc:
            if exc.operation != "unknown":
                raise
            raise EdgeXResponseError(
                str(exc),
                operation="events",
                identity=device_name,
            ) from exc

    def _flatten_event(
        self,
        event: dict[str, Any],
        event_index: int,
        *,
        allow_incomplete_provenance: bool = False,
    ) -> list[TelemetryPoint]:
        context = f"events[{event_index}]"
        if allow_incomplete_provenance:
            def incomplete_string(field: str) -> str:
                value = event.get(field)
                return value if isinstance(value, str) and value else ""

            device_name = incomplete_string("deviceName")
            source_name = incomplete_string("sourceName")
            profile_name = incomplete_string("profileName")
            try:
                event_origin = self._event_origin(event)
            except EdgeXResponseError:
                event_origin = None
        else:
            device_name = self._required_string(event, "deviceName", context)
            source_name = self._required_string(event, "sourceName", context)
            profile_name = self._required_string(event, "profileName", context)
            event_origin = self._event_origin(event)
        readings = event.get("readings")
        if not isinstance(readings, list):
            raise EdgeXResponseError(f"{context}.readings must be a list")
        if allow_incomplete_provenance:
            raw_event_id = event.get("id")
            event_id = raw_event_id if isinstance(raw_event_id, str) else None
        else:
            event_id = self._optional_string(event, "id", context)
        points: list[TelemetryPoint] = []
        for reading_index, reading in enumerate(readings):
            reading_context = f"{context}.readings[{reading_index}]"
            if not isinstance(reading, dict):
                raise EdgeXResponseError(f"{reading_context} must be an object")
            value_type = self._required_string(reading, "valueType", reading_context)
            raw_value = (
                reading.get("objectValue")
                if value_type == "Object"
                else reading.get("value")
            )
            if value_type != "Object" and "value" not in reading:
                raise EdgeXResponseError(f"{reading_context}.value is required")
            raw_origin = reading.get("origin")
            try:
                if raw_origin is None:
                    if event_origin is None and not allow_incomplete_provenance:
                        raise ValueError("missing origin")
                    origin_nanoseconds = event_origin or 0
                    reading_origin = None
                else:
                    try:
                        origin_nanoseconds = _origin_as_int(raw_origin)
                        reading_origin = origin_nanoseconds
                    except (TypeError, ValueError):
                        if not allow_incomplete_provenance:
                            raise
                        origin_nanoseconds = event_origin or 0
                        reading_origin = None
                if allow_incomplete_provenance:
                    resource_value = reading.get("resourceName")
                    resource_name = (
                        resource_value
                        if isinstance(resource_value, str) and resource_value
                        else ""
                    )
                else:
                    resource_name = self._required_string(
                        reading, "resourceName", reading_context
                    )
                points.append(
                    TelemetryPoint(
                        device_name=device_name,
                        source_name=source_name,
                        resource_name=resource_name,
                        value_type=value_type,
                        value=self._typed_value(raw_value, value_type, reading_context),
                        timestamp=parse_edgex_origin(origin_nanoseconds),
                        origin=origin_nanoseconds,
                        event_origin=event_origin,
                        reading_origin=reading_origin,
                        profile_name=profile_name,
                        event_id=event_id,
                        units=self._optional_string(reading, "units", reading_context),
                    )
                )
            except ValidationError as exc:
                raise EdgeXResponseError(
                    f"{reading_context} failed validation: {exc}"
                ) from exc
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
    def _required_string(
        row: dict[str, Any],
        field: str,
        context: str,
        *,
        operation: str | None = None,
        identity: str | None = None,
    ) -> str:
        value = row.get(field)
        if not isinstance(value, str) or not value:
            inferred_operation = (
                operation
                or ("inventory" if context.startswith("devices[") else "unknown")
            )
            raise EdgeXResponseError(
                f"{context}.{field} must be a non-empty string",
                operation=inferred_operation,
                identity=identity,
            )
        return value

    @staticmethod
    def _optional_string(
        row: dict[str, Any],
        field: str,
        context: str,
    ) -> str | None:
        value = row.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            operation = (
                "inventory" if context.startswith("devices[") else "unknown"
            )
            raise EdgeXResponseError(
                f"{context}.{field} must be a string",
                operation=operation,
            )
        return value

    @staticmethod
    def _object_field(
        row: dict[str, Any], field: str, index: int, *, default: dict[str, Any]
    ) -> dict[str, Any]:
        value = row.get(field, default)
        if value is None:
            return default
        if not isinstance(value, dict):
            raise EdgeXResponseError(
                f"devices[{index}].{field} must be an object",
                operation="inventory",
            )
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
