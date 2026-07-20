"""Fail-closed, synchronous command forwarding for explicitly allowlisted edges."""

from __future__ import annotations

import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlparse

import httpx

from .clients import client_ssl_context
from .config import (MAX_COMMAND_DEDUPE_CAPACITY, MAX_COMMAND_TIMEOUT_SECONDS, MAX_COMMAND_TTL_SECONDS,
                     TLSSettings)


MAX_COMMAND_BODY_BYTES = 16 * 1024
MAX_COMMAND_ENVELOPE_BYTES = 16 * 1024
MAX_COMMAND_IDENTIFIER_BYTES = 256
COMMAND_ENVELOPE_KEYS = frozenset({
    "edge_id",
    "device_name",
    "command_id",
    "issued_at",
    "expires_at",
    "operation",
    "command",
    "authorization_version",
    "policy_version",
    "idempotency_classification",
})
POLICY_AUTHORIZATION_VERSION = "authz-v1"
POLICY_VERSION = "policy-v1"
READ_ONLY_OPERATION_POLICIES = {
    "read_status": (POLICY_AUTHORIZATION_VERSION, POLICY_VERSION, "idempotent"),
}
READ_ONLY_OPERATION_COMMANDS = {
    "read_status": {},
}

class CommandError(ValueError):
    """A command violates the fail-closed command contract."""


class CommandExpiredError(CommandError):
    """A command cannot be sent or executed within its validity window."""


class CommandUnavailableError(CommandError):
    """The synchronous edge request was unavailable and was not queued or retried."""


@dataclass(frozen=True)
class CommandRequest:
    edge_id: str
    device_name: str
    command_id: str
    issued_at: float
    expires_at: float
    operation: str
    command: dict[str, Any]
    authorization_version: str
    policy_version: str
    idempotency_classification: Literal["idempotent"]


    def payload(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "device_name": self.device_name,
            "command_id": self.command_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "operation": self.operation,
            "command": self.command,
            "authorization_version": self.authorization_version,
            "policy_version": self.policy_version,
            "idempotency_classification": self.idempotency_classification,
        }


class CommandBridge(Protocol):
    async def request(self, request: CommandRequest) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TerminalCommandResult:
    fingerprint: bytes
    status_code: int
    body: dict[str, Any]


class TerminalCommandCache:
    """Bounded process-local cache of request-bound terminal edge outcomes."""

    def __init__(self, capacity: int) -> None:
        if not 1 <= capacity <= MAX_COMMAND_DEDUPE_CAPACITY:
            raise ValueError("command deduplication capacity must be positive and bounded")
        self.capacity = capacity
        self._results: OrderedDict[str, TerminalCommandResult] = OrderedDict()

    def get(self, command_id: str) -> TerminalCommandResult | None:
        result = self._results.get(command_id)
        if result is not None:
            self._results.move_to_end(command_id)
        return result

    def put(self, command_id: str, terminal_result: TerminalCommandResult) -> None:
        body = terminal_result.body
        if not isinstance(body, dict):
            raise ValueError("terminal result body must be an object")
        _strict_json_bytes(body)
        if body.get("command_id") != command_id:
            raise ValueError("terminal result command_id must match cache key")
        status_code = terminal_result.status_code
        if isinstance(status_code, bool) or not isinstance(status_code, int) or not 100 <= status_code <= 599:
            raise ValueError("terminal result must have a valid HTTP status")
        status = body.get("status")
        error = body.get("error")
        succeeded = status == "succeeded" and "result" in body and "error" not in body
        failed = (
            status == "failed" and "result" not in body and isinstance(error, dict)
            and isinstance(error.get("code"), str) and bool(error["code"])
            and isinstance(error.get("message"), str) and bool(error["message"])
        )
        if not succeeded and not failed:
            raise ValueError("only mutually exclusive terminal command results may be cached")
        if (succeeded and not 200 <= status_code < 300) or (failed and 200 <= status_code < 300):
            raise ValueError("terminal result status is inconsistent with its HTTP status")
        self._results[command_id] = terminal_result
        self._results.move_to_end(command_id)
        while len(self._results) > self.capacity:
            self._results.popitem(last=False)


def _https_endpoint(edge_id: str, endpoint: str) -> str:
    parsed = urlparse(endpoint)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"command endpoint for {edge_id} has an invalid port") from error
    if (not edge_id or parsed.scheme != "https" or not parsed.hostname or port is None or not 1 <= port <= 65535
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("edge command endpoints must be non-empty HTTPS URLs with explicit valid ports")
    return endpoint.rstrip("/")


class HTTPSCommandBridge:
    """Makes exactly one synchronous mTLS request and validates its terminal result."""

    def __init__(self, endpoints: dict[str, str], tls: TLSSettings,
                 client: httpx.AsyncClient | None = None, *, command_timeout_seconds: float = 10,
                 max_ttl_seconds: float = MAX_COMMAND_TTL_SECONDS) -> None:
        if not endpoints:
            raise ValueError("edge command endpoints must be non-empty HTTPS URLs with explicit valid ports")
        if not 0 < command_timeout_seconds <= MAX_COMMAND_TIMEOUT_SECONDS:
            raise ValueError("command timeout must be positive and bounded")
        if not 0 < max_ttl_seconds <= MAX_COMMAND_TTL_SECONDS:
            raise ValueError("command maximum TTL must be positive and bounded")
        self.endpoints = {edge_id: _https_endpoint(edge_id, url) for edge_id, url in endpoints.items()}
        self.command_timeout_seconds = command_timeout_seconds
        self.max_ttl_seconds = max_ttl_seconds
        self.client = client or httpx.AsyncClient(verify=client_ssl_context(tls), timeout=command_timeout_seconds)

    async def request(self, request: CommandRequest) -> dict[str, Any]:
        now = time.time()
        if request.expires_at <= now:
            raise CommandExpiredError("command TTL has expired")
        if request.expires_at - now > self.max_ttl_seconds:
            raise CommandExpiredError("command TTL exceeds the configured maximum")
        endpoint = self.endpoints.get(request.edge_id)
        if endpoint is None:
            raise CommandError("edge is not allowlisted for commands")
        timeout = min(self.command_timeout_seconds, request.expires_at - now)
        try:
            response = await self.client.post(
                f"{endpoint}/v1/commands/{quote(request.device_name, safe='')}", json=request.payload(), timeout=timeout
            )
        except httpx.TimeoutException as error:
            raise CommandUnavailableError("edge command timed out and was not queued") from error
        except httpx.HTTPError as error:
            raise CommandUnavailableError("edge command is unavailable and was not queued") from error
        try:
            body = response.json()
        except ValueError as error:
            raise CommandError("edge command response is not JSON") from error
        self._validate_terminal_response(request, body)
        if 200 <= response.status_code < 300:
            if body["status"] != "succeeded":
                raise CommandError("edge command response status is inconsistent with its HTTP status")
            return body
        if body["status"] != "failed":
            raise CommandError("edge command response status is inconsistent with its HTTP status")
        error = body["error"]
        message = error["message"]
        if error["code"] == "command_expired":
            raise CommandExpiredError(message)
        if response.status_code in (408, 425, 429) or response.status_code >= 500:
            raise CommandUnavailableError(f"edge command failed with HTTP {response.status_code} and was not queued")
        raise CommandError(message)

    @staticmethod
    def _validate_terminal_response(request: CommandRequest, body: Any) -> None:
        if not isinstance(body, dict):
            raise CommandError("edge command response is not an object")
        _strict_json_bytes(body)
        if body.get("edge_id") != request.edge_id or body.get("command_id") != request.command_id:
            raise CommandError("edge command response does not match request")
        status = body.get("status")
        if status == "succeeded" and "result" in body and "error" not in body:
            return
        error = body.get("error")
        if (status == "failed" and "result" not in body and isinstance(error, dict)
                and isinstance(error.get("code"), str) and error["code"]
                and isinstance(error.get("message"), str) and error["message"]):
            return
        raise CommandError("edge command response is not a mutually exclusive terminal result")

    async def close(self) -> None:
        await self.client.aclose()


def _string_field(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{name} must be a non-empty string")
    if len(value.encode()) > MAX_COMMAND_IDENTIFIER_BYTES:
        raise CommandError(f"{name} exceeds the maximum size")
    return value


def _timestamp(payload: dict[str, Any], name: str) -> float:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError(f"{name} must be a Unix timestamp")
    try:
        value = float(value)
    except (ValueError, OverflowError) as error:
        raise CommandError(f"{name} must be a Unix timestamp") from error
    if not math.isfinite(value):
        raise CommandError(f"{name} must be a finite Unix timestamp")
    return value


def _strict_json_bytes(value: Any) -> bytes:
    def validate(item: Any) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if math.isfinite(item):
                return
            raise CommandError("command JSON values must be finite")
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise CommandError("command JSON object keys must be strings")
                validate(child)
            return
        raise CommandError("command must contain only JSON values")

    validate(value)
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise CommandError("command must be strict JSON serializable") from error


def command_fingerprint(request: CommandRequest) -> bytes:
    """Canonical strict-JSON identity used to bind a command ID to one request."""
    return _strict_json_bytes(request.payload())


def _authorize_command_execution(request: CommandRequest, *, max_ttl_seconds: float, now: float | None = None) -> None:
    current_time = time.time() if now is None else now
    if request.issued_at > current_time + max_ttl_seconds:
        raise CommandExpiredError("command issued_at is implausibly in the future")
    if request.expires_at <= current_time:
        raise CommandExpiredError("command TTL has expired")
    if request.expires_at - current_time > max_ttl_seconds:
        raise CommandExpiredError("command TTL exceeds the configured maximum")


def command_from_payload(edge_id: str, device_name: str, payload: dict[str, Any], *,
                         max_ttl_seconds: float = 30, now: float | None = None,
                         authorize: bool = True) -> CommandRequest:
    """Canonicalize a complete envelope and, unless disabled, authorize its execution time."""
    if not isinstance(payload, dict):
        raise CommandError("command payload must be an object")
    issued_at = _timestamp(payload, "issued_at")
    expires_at = _timestamp(payload, "expires_at")
    envelope_bytes = _strict_json_bytes(payload)
    if len(envelope_bytes) > MAX_COMMAND_ENVELOPE_BYTES:
        raise CommandError("command envelope exceeds the maximum size")
    if set(payload) != COMMAND_ENVELOPE_KEYS:
        raise CommandError("command payload must contain exactly the supported envelope keys")
    if payload["edge_id"] != edge_id:
        raise CommandError("command edge_id does not match URL")
    if payload["device_name"] != device_name:
        raise CommandError("command device_name does not match URL")
    _string_field(payload, "edge_id")
    _string_field(payload, "device_name")
    command_id = _string_field(payload, "command_id")
    if not 0 < max_ttl_seconds <= MAX_COMMAND_TTL_SECONDS:
        raise CommandError("command maximum TTL must be positive and bounded")
    if expires_at <= issued_at or expires_at - issued_at > max_ttl_seconds:
        raise CommandExpiredError("command TTL exceeds the configured maximum")
    operation = _string_field(payload, "operation")
    policy = READ_ONLY_OPERATION_POLICIES.get(operation)
    if policy is None:
        raise CommandError("operation is not supported")
    authorization_version = _string_field(payload, "authorization_version")
    policy_version = _string_field(payload, "policy_version")
    classification = _string_field(payload, "idempotency_classification")
    if (authorization_version, policy_version, classification) != policy:
        raise CommandError("command policy metadata does not match the server-owned operation policy")
    command = payload.get("command")
    if not isinstance(command, dict):
        raise CommandError("command must be an object")
    command_bytes = _strict_json_bytes(command)
    if len(command_bytes) > MAX_COMMAND_BODY_BYTES:
        raise CommandError("command body exceeds the maximum size")
    server_command = READ_ONLY_OPERATION_COMMANDS[operation]
    if command != server_command:
        raise CommandError("command payload does not match the server-owned operation schema")
    request = CommandRequest(edge_id, device_name, command_id, issued_at, expires_at, operation, server_command,
                             authorization_version, policy_version, classification)
    if authorize:
        _authorize_command_execution(request, max_ttl_seconds=max_ttl_seconds, now=now)
    return request
