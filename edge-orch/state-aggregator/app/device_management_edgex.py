from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx


class EdgeXManagementError(RuntimeError):
    """Base error for the isolated EdgeX Metadata management boundary."""


class EdgeXManagementBackendError(EdgeXManagementError):
    """Core Metadata could not be reached or returned an HTTP failure."""


class EdgeXManagementResponseError(EdgeXManagementError):
    """Core Metadata returned a response outside the EdgeX v3 contract."""


class EdgeXManagementClient:
    def __init__(
        self,
        core_metadata_url: str,
        timeout_seconds: float = 10.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.core_metadata_url = core_metadata_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def list_device_services(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/api/v3/deviceservice/all",
            params={"offset": 0, "limit": 1000},
        )
        return self._envelope_list(payload, "services")

    async def get_device(self, name: str) -> dict[str, Any] | None:
        payload = await self._request(
            "GET",
            f"/api/v3/device/name/{quote(name, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        return self._envelope_object(payload, "device")

    async def get_profile(self, name: str) -> dict[str, Any] | None:
        payload = await self._request(
            "GET",
            f"/api/v3/deviceprofile/name/{quote(name, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        return self._envelope_object(payload, "profile")

    async def list_devices_by_profile(self, name: str) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            f"/api/v3/device/profile/name/{quote(name, safe='')}",
            params={"offset": 0, "limit": 1000},
        )
        return self._envelope_list(payload, "devices")

    async def add_profile(self, profile: dict[str, Any]) -> str:
        payload = await self._request(
            "POST",
            "/api/v3/deviceprofile",
            json_body=[self._request_dto("profile", profile)],
        )
        return self._mutation_id(payload)

    async def add_device(self, device: dict[str, Any]) -> str:
        payload = await self._request(
            "POST",
            "/api/v3/device",
            json_body=[self._request_dto("device", device)],
        )
        return self._mutation_id(payload)

    async def patch_device(self, name: str, patch: dict[str, Any]) -> None:
        device_patch = {"name": name, **patch}
        payload = await self._request(
            "PATCH",
            "/api/v3/device",
            json_body=[self._request_dto("device", device_patch)],
        )
        self._mutation_responses(payload, require_id=False)

    async def delete_profile(self, name: str) -> None:
        payload = await self._request(
            "DELETE",
            f"/api/v3/deviceprofile/name/{quote(name, safe='')}",
        )
        self._validate_base(payload, "profile delete response")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, int] | None = None,
        json_body: Any | None = None,
        allow_not_found: bool = False,
    ) -> Any | None:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.core_metadata_url}{path}",
                    params=params,
                    json=json_body,
                )
                if allow_not_found and response.status_code == 404:
                    return None
                response.raise_for_status()
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise EdgeXManagementBackendError(
                f"EdgeX Metadata request failed for {path}: {exc}"
            ) from exc
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise EdgeXManagementResponseError(
                f"EdgeX Metadata returned invalid JSON for {path}"
            ) from exc

    @staticmethod
    def _request_dto(field: str, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "apiVersion": "v3",
            "requestId": str(uuid4()),
            field: value,
        }

    @classmethod
    def _validate_base(cls, payload: Any, context: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise EdgeXManagementResponseError(f"{context} must be an object")
        if payload.get("apiVersion") != "v3":
            raise EdgeXManagementResponseError(f"{context} apiVersion must be v3")
        status_code = payload.get("statusCode")
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise EdgeXManagementResponseError(f"{context} statusCode must be an integer")
        if not 200 <= status_code < 300:
            message = payload.get("message") or "unknown EdgeX error"
            raise EdgeXManagementResponseError(
                f"{context} statusCode {status_code}: {message}"
            )
        return payload

    @classmethod
    def _envelope_list(cls, payload: Any, field: str) -> list[dict[str, Any]]:
        envelope = cls._validate_base(payload, f"{field} response")
        rows = envelope.get(field)
        if not isinstance(rows, list):
            raise EdgeXManagementResponseError(f"{field} response must contain an array")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EdgeXManagementResponseError(f"{field}[{index}] must be an object")
        return rows

    @classmethod
    def _envelope_object(cls, payload: Any, field: str) -> dict[str, Any]:
        envelope = cls._validate_base(payload, f"{field} response")
        value = envelope.get(field)
        if not isinstance(value, dict):
            raise EdgeXManagementResponseError(f"{field} response must contain an object")
        return value

    @classmethod
    def _mutation_responses(
        cls, payload: Any, *, require_id: bool
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, list) or not payload:
            raise EdgeXManagementResponseError("EdgeX mutation response must be a non-empty array")
        responses: list[dict[str, Any]] = []
        for index, item in enumerate(payload):
            response = cls._validate_base(item, f"mutation response[{index}]")
            if require_id and not isinstance(response.get("id"), str):
                raise EdgeXManagementResponseError(
                    f"mutation response[{index}].id must be a string"
                )
            responses.append(response)
        return responses

    @classmethod
    def _mutation_id(cls, payload: Any) -> str:
        return cls._mutation_responses(payload, require_id=True)[0]["id"]
