from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from .adapter_runtime_models import (
    RuntimeActionRequest,
    RuntimeCreateRequest,
    RuntimeObservation,
    RuntimePlan,
    RuntimePlanRequest,
)
from .device_discovery_models import (
    CandidateDecommissionUpdate,
    CandidateDecisionUpdate,
    CandidateDeleteRequest,
    CandidateView,
    DiscoveryInventory,
    ManualCandidateCreate,
)


class AdapterControllerClientError(RuntimeError):
    pass


class AdapterControllerBackendError(AdapterControllerClientError):
    pass


class AdapterControllerResponseError(AdapterControllerClientError):
    pass


class AdapterControllerNotFoundError(AdapterControllerClientError):
    pass


class AdapterControllerConflictError(AdapterControllerClientError):
    pass


class AdapterControllerValidationError(AdapterControllerClientError):
    pass


class AdapterControllerClient:
    def __init__(
        self,
        base_url: str,
        hmac_key: str,
        timeout_seconds: float = 5.0,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not hmac_key:
            raise ValueError("Adapter Controller HMAC key must not be empty")
        self.base_url = base_url.rstrip("/")
        self._hmac_key = hmac_key.encode("utf-8")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def list_runtimes(self) -> list[RuntimeObservation]:
        payload = await self._request("GET", "/internal/v1/runtimes")
        try:
            return TypeAdapter(list[RuntimeObservation]).validate_python(payload)
        except ValidationError as exc:
            raise AdapterControllerResponseError(
                "Adapter Controller runtime response contract is invalid"
            ) from exc

    async def plan_runtime(self, request: RuntimePlanRequest) -> RuntimePlan:
        body = request.model_dump(by_alias=True, exclude_none=True)
        if not request.settings:
            body.pop("settings", None)
        payload = await self._request(
            "POST",
            "/internal/v1/runtimes/plan",
            body=body,
        )
        return self._parse_model(RuntimePlan, payload, "runtime plan")

    async def apply_runtime(
        self,
        name: str,
        request: RuntimeCreateRequest,
    ) -> RuntimeObservation:
        body = request.model_dump(by_alias=True, exclude_none=True)
        if not request.plan.settings:
            body.get("plan", {}).pop("settings", None)
        payload = await self._request(
            "PUT",
            f"/internal/v1/runtimes/{quote(name, safe='')}",
            body=body,
        )
        return self._parse_model(RuntimeObservation, payload, "runtime apply")

    async def restart_runtime(
        self,
        name: str,
        request: RuntimeActionRequest,
    ) -> RuntimeObservation:
        payload = await self._request(
            "POST",
            f"/internal/v1/runtimes/{quote(name, safe='')}/restart",
            body=request.model_dump(by_alias=True, exclude_none=True),
        )
        return self._parse_model(RuntimeObservation, payload, "runtime restart")

    async def retire_runtime(
        self,
        name: str,
        request: RuntimeActionRequest,
    ) -> RuntimeObservation:
        payload = await self._request(
            "DELETE",
            f"/internal/v1/runtimes/{quote(name, safe='')}",
            body=request.model_dump(by_alias=True, exclude_none=True),
            extra_headers={"X-Confirm-Runtime": name},
        )
        return self._parse_model(RuntimeObservation, payload, "runtime retire")

    async def list_discovery_inventory(self) -> DiscoveryInventory:
        payload = await self._request("GET", "/internal/v1/discovery")
        return self._parse_model(
            DiscoveryInventory,
            payload,
            "device discovery inventory",
        )

    async def create_manual_candidate(
        self,
        request: ManualCandidateCreate,
    ) -> CandidateView:
        payload = await self._request(
            "POST",
            "/internal/v1/discovery/manual",
            body=request.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        return self._parse_model(CandidateView, payload, "manual candidate")

    async def update_candidate_decision(
        self,
        candidate_id: str,
        request: CandidateDecisionUpdate,
    ) -> CandidateView:
        payload = await self._request(
            "PATCH",
            f"/internal/v1/discovery/{quote(candidate_id, safe='')}",
            body=request.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        return self._parse_model(CandidateView, payload, "candidate decision")

    async def delete_candidate(
        self,
        candidate_id: str,
        request: CandidateDeleteRequest,
    ) -> CandidateView:
        payload = await self._request(
            "DELETE",
            f"/internal/v1/discovery/{quote(candidate_id, safe='')}",
            body=request.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        return self._parse_model(CandidateView, payload, "candidate delete")

    async def decommission_candidate(
        self,
        candidate_id: str,
        request: CandidateDecommissionUpdate,
    ) -> CandidateView:
        payload = await self._request(
            "POST",
            (
                f"/internal/v1/discovery/"
                f"{quote(candidate_id, safe='')}/decommission"
            ),
            body=request.model_dump(
                by_alias=True,
                mode="json",
                exclude_none=True,
            ),
            extra_headers={"X-Confirm-Candidate": candidate_id},
        )
        return self._parse_model(
            CandidateView,
            payload,
            "candidate decommission",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        content = (
            json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if body is not None
            else b""
        )
        timestamp = str(int(time.time()))
        body_hash = hashlib.sha256(content).hexdigest()
        canonical = (
            f"{timestamp}\n{method.upper()}\n{path}\n{body_hash}"
        ).encode("utf-8")
        signature = hmac.new(
            self._hmac_key,
            canonical,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-Controller-Timestamp": timestamp,
            "X-Controller-Signature": signature,
            **(extra_headers or {}),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    content=content,
                    headers=headers,
                )
                if response.status_code == 404:
                    raise AdapterControllerNotFoundError(
                        "Adapter Controller resource was not found"
                    )
                if response.status_code == 409:
                    raise AdapterControllerConflictError(
                        "Adapter Controller rejected a conflicting request"
                    )
                if response.status_code == 422:
                    raise AdapterControllerValidationError(
                        "Adapter Controller rejected request validation"
                    )
                response.raise_for_status()
        except AdapterControllerClientError:
            raise
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise AdapterControllerBackendError(
                "Adapter Controller request failed"
            ) from exc
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise AdapterControllerResponseError(
                "Adapter Controller returned invalid JSON"
            ) from exc

    @staticmethod
    def _parse_model(model: Any, payload: Any, context: str) -> Any:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise AdapterControllerResponseError(
                f"Adapter Controller {context} response contract is invalid"
            ) from exc
