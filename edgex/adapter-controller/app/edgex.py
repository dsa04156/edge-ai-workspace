from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import quote
from uuid import uuid4

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
    ) -> Any | None:
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


class EdgeXRegistrationClient:
    def __init__(
        self,
        metadata_url: str,
        core_data_url: str,
        timeout_seconds: float = 5,
        *,
        metadata_transport: httpx.BaseTransport | None = None,
        data_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.metadata_url = metadata_url.rstrip("/")
        self.core_data_url = core_data_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.metadata_transport = metadata_transport
        self.data_transport = data_transport

    def ensure_profile(self, profile: dict) -> bool:
        name = str(profile.get("name") or "")
        if not name:
            raise EdgeXProbeError("Device Profile name is required")
        current = self.get_profile(name)
        if current is not None:
            if not self._profile_matches(current, profile):
                raise EdgeXProbeError(
                    "existing EdgeX Device Profile differs from the Catalog"
                )
            return False
        response = self._request(
            "POST",
            self.metadata_url,
            "/api/v3/deviceprofile",
            json_body=[
                {
                    "apiVersion": "v3",
                    "requestId": str(uuid4()),
                    "profile": profile,
                }
            ],
            expected={200, 201, 207},
        )
        self._validate_mutation_response(response)
        readback = self.get_profile(name)
        if readback is None or not self._profile_matches(readback, profile):
            raise EdgeXProbeError("Device Profile readback verification failed")
        return True

    def verify_existing_profile(self, profile: dict) -> None:
        name = str(profile.get("name") or "")
        if not name:
            raise EdgeXProbeError("Device Profile name is required")
        current = self.get_profile(name)
        if current is None:
            raise EdgeXProbeError(
                "required existing EdgeX Device Profile was not found"
            )
        if not self._profile_matches(current, profile):
            raise EdgeXProbeError(
                "existing EdgeX Device Profile differs from the Catalog"
            )

    def ensure_device(self, device: dict) -> bool:
        name = str(device.get("name") or "")
        if not name:
            raise EdgeXProbeError("Device name is required")
        current = self.get_device(name)
        if current is not None:
            if not self._device_matches(current, device):
                raise EdgeXProbeError(
                    "existing EdgeX Device differs from the registration request"
                )
            return False
        response = self._request(
            "POST",
            self.metadata_url,
            "/api/v3/device",
            json_body=[
                {
                    "apiVersion": "v3",
                    "requestId": str(uuid4()),
                    "device": device,
                }
            ],
            expected={200, 201, 207},
        )
        self._validate_mutation_response(response)
        readback = self.get_device(name)
        if readback is None or not self._device_matches(readback, device):
            raise EdgeXProbeError("Device readback verification failed")
        return True

    def verify_existing_device(self, device: dict) -> None:
        name = str(device.get("name") or "")
        if not name:
            raise EdgeXProbeError("Device name is required")
        current = self.get_device(name)
        if current is None:
            raise EdgeXProbeError(
                "required existing EdgeX Device was not found"
            )
        fields = (
            "name",
            "serviceName",
            "profileName",
            "adminState",
            "protocols",
            "tags",
        )
        if not all(
            self._matches_expected_shape(
                deepcopy(current.get(field)),
                deepcopy(device.get(field)),
            )
            for field in fields
        ):
            raise EdgeXProbeError(
                "existing EdgeX Device differs from the Catalog binding"
            )

    def get_profile(self, name: str) -> dict | None:
        payload = self._request(
            "GET",
            self.metadata_url,
            f"/api/v3/deviceprofile/name/{quote(name, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        profile = payload.get("profile")
        if not isinstance(profile, dict):
            raise EdgeXProbeError("invalid EdgeX Device Profile response")
        return profile

    def get_device(self, name: str) -> dict | None:
        payload = self._request(
            "GET",
            self.metadata_url,
            f"/api/v3/device/name/{quote(name, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None
        device = payload.get("device")
        if not isinstance(device, dict):
            raise EdgeXProbeError("invalid EdgeX Device response")
        return device

    def first_event_received(
        self,
        device_name: str,
        *,
        not_before_ns: int | None = None,
    ) -> bool:
        payload = self._request(
            "GET",
            self.core_data_url,
            (
                "/api/v3/event/device/name/"
                f"{quote(device_name, safe='')}?limit=1"
            ),
            allow_not_found=True,
            data_plane=True,
        )
        if payload is None:
            return False
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            return False
        if not_before_ns is None:
            return True
        for event in events:
            if not isinstance(event, dict):
                continue
            origin = event.get("origin")
            if isinstance(origin, bool):
                continue
            try:
                if int(origin) >= not_before_ns:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def ensure_device_operating_up(self, device_name: str) -> bool:
        current = self.get_device(device_name)
        if current is None:
            raise EdgeXProbeError(
                "cannot update operating state for a missing EdgeX Device"
            )
        if current.get("operatingState") == "UP":
            return False
        response = self._request(
            "PATCH",
            self.metadata_url,
            "/api/v3/device",
            json_body=[
                {
                    "apiVersion": "v3",
                    "requestId": str(uuid4()),
                    "device": {
                        "name": device_name,
                        "operatingState": "UP",
                    },
                }
            ],
            expected={200, 207},
        )
        self._validate_mutation_response(response)
        readback = self.get_device(device_name)
        if readback is None or readback.get("operatingState") != "UP":
            raise EdgeXProbeError(
                "Device operating state readback verification failed"
            )
        return True

    def delete_owned_device(
        self,
        name: str,
        *,
        candidate_id: str,
    ) -> None:
        current = self.get_device(name)
        if current is None:
            return
        tags = current.get("tags") or {}
        if tags.get("controllerCandidateId") != candidate_id:
            raise EdgeXProbeError(
                "refusing to delete an EdgeX Device not owned by this Saga"
            )
        self._request(
            "DELETE",
            self.metadata_url,
            f"/api/v3/device/name/{quote(name, safe='')}",
            expected={200, 202, 204},
        )

    def delete_unused_profile(self, name: str) -> None:
        payload = self._request(
            "GET",
            self.metadata_url,
            f"/api/v3/device/profile/name/{quote(name, safe='')}",
            allow_not_found=True,
        )
        if payload is not None:
            devices = payload.get("devices")
            if isinstance(devices, list) and devices:
                return
        self._request(
            "DELETE",
            self.metadata_url,
            f"/api/v3/deviceprofile/name/{quote(name, safe='')}",
            expected={200, 202, 204},
            allow_not_found=True,
        )

    def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        json_body: object | None = None,
        expected: set[int] | None = None,
        allow_not_found: bool = False,
        data_plane: bool = False,
    ) -> Any | None:
        transport = (
            self.data_transport if data_plane else self.metadata_transport
        )
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=transport,
            ) as client:
                response = client.request(
                    method,
                    f"{base_url}{path}",
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            raise EdgeXProbeError("EdgeX registration request failed") from exc
        if response.status_code == 404 and allow_not_found:
            return None
        accepted = expected or {200}
        if response.status_code not in accepted:
            raise EdgeXProbeError(
                f"EdgeX registration returned HTTP {response.status_code}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise EdgeXProbeError("EdgeX response was not JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise EdgeXProbeError(
                "EdgeX response must be an object or mutation response array"
            )
        if method.upper() == "GET" and not isinstance(payload, dict):
            raise EdgeXProbeError("EdgeX read response must be an object")
        return payload

    @staticmethod
    def _profile_matches(current: dict, expected: dict) -> bool:
        fields = (
            "name",
            "manufacturer",
            "model",
            "deviceResources",
            "deviceCommands",
        )
        return all(
            EdgeXRegistrationClient._matches_expected_shape(
                deepcopy(current.get(field)),
                deepcopy(expected.get(field)),
            )
            for field in fields
        )

    @staticmethod
    def _matches_expected_shape(current: Any, expected: Any) -> bool:
        """Compare Catalog fields while allowing EdgeX server defaults.

        Core Metadata enriches nested Device Profile resources and commands
        with fields such as ``isHidden: false`` during persistence.  Those
        server-owned defaults must not make an otherwise identical Catalog
        profile fail readback.  Extra list entries remain a mismatch so a
        profile name cannot silently alias a profile with other resources.
        """
        if isinstance(expected, dict):
            return isinstance(current, dict) and all(
                key in current
                and EdgeXRegistrationClient._matches_expected_shape(
                    current[key],
                    value,
                )
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            return (
                isinstance(current, list)
                and len(current) == len(expected)
                and all(
                    EdgeXRegistrationClient._matches_expected_shape(
                        current_item,
                        expected_item,
                    )
                    for current_item, expected_item in zip(
                        current,
                        expected,
                        strict=True,
                    )
                )
            )
        return current == expected

    @staticmethod
    def _validate_mutation_response(payload: Any) -> None:
        # EdgeX v3 batch mutations normally return HTTP 207 with one response
        # object per request. Some compatible test deployments return a single
        # object for HTTP 200/201, so both envelopes are accepted but every
        # embedded status is still checked.
        responses = payload if isinstance(payload, list) else [payload]
        if not responses or any(not isinstance(item, dict) for item in responses):
            raise EdgeXProbeError("invalid EdgeX mutation response")
        for item in responses:
            embedded = item.get("statusCode")
            if (
                isinstance(embedded, bool)
                or not isinstance(embedded, int)
                or not (200 <= embedded < 300 or embedded == 409)
            ):
                raise EdgeXProbeError(
                    f"EdgeX mutation failed with status {embedded!r}"
                )

    @staticmethod
    def _device_matches(current: dict, expected: dict) -> bool:
        fields = (
            "name",
            "serviceName",
            "profileName",
            "adminState",
            "protocols",
            "tags",
        )
        return all(
            deepcopy(current.get(field)) == deepcopy(expected.get(field))
            for field in fields
        )
