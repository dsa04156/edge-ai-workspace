from __future__ import annotations

from urllib.parse import quote

import httpx


class EdgeXProbeError(RuntimeError):
    """EdgeX dependency state cannot be established safely."""


class EdgeXServiceProbe:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def service_ready(self, service_name: str) -> bool:
        try:
            payload = self._get(
                f"/api/v3/deviceservice/name/{quote(service_name, safe='')}"
            )
        except EdgeXProbeError:
            return False
        if not isinstance(payload, dict) or payload.get("statusCode") != 200:
            return False
        service = payload.get("service")
        return (
            isinstance(service, dict)
            and service.get("name") == service_name
            and service.get("adminState") == "UNLOCKED"
        )

    def consumer_count(self, service_name: str) -> int:
        payload = self._get(
            f"/api/v3/device/service/name/{quote(service_name, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return 0
        if not isinstance(payload, dict) or payload.get("statusCode") != 200:
            raise EdgeXProbeError("invalid EdgeX Device service response")
        devices = payload.get("devices")
        if not isinstance(devices, list):
            raise EdgeXProbeError(
                "EdgeX Device service response has no devices array"
            )
        return len(devices)

    def _get(
        self,
        path: str,
        *,
        allow_not_found: bool = False,
    ) -> dict | None:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(f"{self.base_url}{path}")
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EdgeXProbeError(
                "EdgeX Core Metadata probe failed"
            ) from exc
        return payload if isinstance(payload, dict) else None
