from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .discovery_models import StoredCandidate


@dataclass(frozen=True)
class AuthDecision:
    approved: bool
    state: str
    reason: str
    error_code: str | None = None


class AuthProvider(Protocol):
    def approve(
        self,
        candidate: StoredCandidate,
        *,
        actor: str,
        reason: str,
    ) -> AuthDecision: ...


class AllowAllMockProvider:
    """Development-only provider. Production manifests must not select it."""

    def approve(
        self,
        candidate: StoredCandidate,
        *,
        actor: str,
        reason: str,
    ) -> AuthDecision:
        del candidate, actor, reason
        return AuthDecision(
            approved=True,
            state="approved",
            reason="development AllowAllMockProvider approved the candidate",
        )


class ExternalSecurityApprovalClient:
    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not endpoint:
            raise ValueError("external auth endpoint is required")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(
                "external auth endpoint must use HTTPS"
            )
        self.endpoint = endpoint
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def approve(
        self,
        candidate: StoredCandidate,
        *,
        actor: str,
        reason: str,
    ) -> AuthDecision:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {
            "candidateId": candidate.candidate_id,
            "nodeId": candidate.node_name,
            "protocol": candidate.protocol,
            "hardwareId": candidate.hardware_id,
            "vendor": candidate.vendor,
            "model": candidate.model,
            "profile": candidate.recommended_profile,
            "actor": actor,
            "reason": reason,
        }
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException:
            return AuthDecision(
                approved=False,
                state="unavailable",
                reason="external approval timed out",
                error_code="AUTH_TIMEOUT",
            )
        except httpx.HTTPError:
            return AuthDecision(
                approved=False,
                state="unavailable",
                reason="external approval service is unavailable",
                error_code="AUTH_UNAVAILABLE",
            )
        if response.status_code >= 500:
            return AuthDecision(
                approved=False,
                state="unavailable",
                reason="external approval service returned a server error",
                error_code="AUTH_UNAVAILABLE",
            )
        if response.status_code in {401, 403}:
            return AuthDecision(
                approved=False,
                state="denied",
                reason="external approval denied the candidate",
                error_code="AUTH_DENIED",
            )
        if response.status_code != 200:
            return AuthDecision(
                approved=False,
                state="error",
                reason="external approval returned an invalid response",
                error_code="AUTH_INVALID_RESPONSE",
            )
        try:
            body = response.json()
        except ValueError:
            return AuthDecision(
                approved=False,
                state="error",
                reason="external approval response was not JSON",
                error_code="AUTH_INVALID_RESPONSE",
            )
        approved = body.get("approved")
        if not isinstance(approved, bool):
            return AuthDecision(
                approved=False,
                state="error",
                reason="external approval response omitted approved",
                error_code="AUTH_INVALID_RESPONSE",
            )
        return AuthDecision(
            approved=approved,
            state="approved" if approved else "denied",
            reason=str(body.get("reason") or "external approval decision"),
            error_code=None if approved else "AUTH_DENIED",
        )


def build_auth_provider(
    *,
    mode: str,
    endpoint: str | None,
    token: str | None,
    timeout_seconds: float,
) -> AuthProvider:
    if mode == "development-mock":
        return AllowAllMockProvider()
    if mode == "external":
        if not endpoint:
            raise ValueError(
                "ADAPTER_AUTH_ENDPOINT is required when ADAPTER_AUTH_MODE=external"
            )
        return ExternalSecurityApprovalClient(
            endpoint,
            token=token,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"unknown auth provider mode {mode!r}")
