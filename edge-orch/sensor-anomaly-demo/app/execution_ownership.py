from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx

from .config import Settings


ExecutionMode = Literal["ACTIVE", "STANDBY", "SHADOW"]


class LeaseAccessError(RuntimeError):
    pass


class LeaseConflictError(LeaseAccessError):
    pass


class LeaseClient(Protocol):
    async def read(self, namespace: str, name: str) -> dict[str, Any]: ...

    async def replace(
        self,
        namespace: str,
        name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class OwnershipState:
    configured_mode: ExecutionMode
    effective_mode: ExecutionMode
    enabled: bool
    lease_namespace: str | None
    lease_name: str | None
    holder_identity: str | None
    owner_identity: str | None
    lease_valid: bool
    renew_time: datetime | None
    lease_duration_seconds: int | None
    resource_version: str | None
    reason_code: str | None
    observed_at: datetime


class KubernetesLeaseClient:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_url: str | None = None,
        token_path: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token"),
        ca_path: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"),
    ) -> None:
        host = os.getenv("KUBERNETES_SERVICE_HOST")
        port = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        base_url = api_url or (f"https://{host}:{port}" if host else None)
        if client is None:
            if not base_url or not token_path.exists() or not ca_path.exists():
                raise LeaseAccessError("in-cluster Kubernetes credentials are unavailable")
            token = token_path.read_text(encoding="utf-8").strip()
            client = httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {token}"},
                verify=str(ca_path),
                timeout=2.0,
            )
        self._client = client

    @staticmethod
    def _path(namespace: str, name: str) -> str:
        return (
            "/apis/coordination.k8s.io/v1/namespaces/"
            f"{quote(namespace, safe='')}/leases/{quote(name, safe='')}"
        )

    async def read(self, namespace: str, name: str) -> dict[str, Any]:
        try:
            response = await self._client.get(self._path(namespace, name))
        except httpx.HTTPError as exc:
            raise LeaseAccessError("execution ownership Lease is unreachable") from exc
        if response.status_code != 200:
            raise LeaseAccessError(
                f"execution ownership Lease read failed with HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise LeaseAccessError("execution ownership Lease response is invalid")
        return payload

    async def replace(
        self,
        namespace: str,
        name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await self._client.put(self._path(namespace, name), json=body)
        except httpx.HTTPError as exc:
            raise LeaseAccessError("execution ownership Lease update is unreachable") from exc
        if response.status_code == 409:
            raise LeaseConflictError("execution ownership Lease CAS conflict")
        if response.status_code != 200:
            raise LeaseAccessError(
                f"execution ownership Lease update failed with HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise LeaseAccessError("execution ownership Lease response is invalid")
        return payload

    async def close(self) -> None:
        await self._client.aclose()


class ExecutionOwnershipGuard:
    def __init__(
        self,
        settings: Settings,
        client: LeaseClient,
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep or asyncio.sleep
        observed_at = self.now()
        self._state = OwnershipState(
            configured_mode=settings.execution_mode,
            effective_mode="STANDBY",
            enabled=True,
            lease_namespace=settings.execution_lease_namespace,
            lease_name=settings.execution_lease_name,
            holder_identity=None,
            owner_identity=settings.execution_owner_id,
            lease_valid=False,
            renew_time=None,
            lease_duration_seconds=None,
            resource_version=None,
            reason_code="execution_lease_not_observed",
            observed_at=observed_at,
        )
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        await self.refresh_once()
        self._task = asyncio.create_task(self._run(), name="execution-lease-guard")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        await self.client.close()

    def state(self) -> OwnershipState:
        return self._state

    async def confirm_active(self) -> bool:
        state = await self.refresh_once()
        return state.effective_mode == "ACTIVE" and state.lease_valid

    async def refresh_once(self) -> OwnershipState:
        async with self._lock:
            observed_at = self.now()
            namespace = self.settings.execution_lease_namespace
            name = self.settings.execution_lease_name
            owner = self.settings.execution_owner_id
            try:
                lease = await self.client.read(namespace, name)
                state = await self._evaluate_and_renew(lease, observed_at)
            except LeaseConflictError:
                state = self._blocked(
                    observed_at,
                    "execution_lease_cas_conflict",
                    holder=self._state.holder_identity,
                )
            except Exception:
                state = self._blocked(
                    observed_at,
                    "execution_lease_unavailable",
                    holder=self._state.holder_identity,
                )
            if not owner:
                state = self._blocked(observed_at, "execution_owner_identity_missing")
            self._state = state
            return state

    async def _evaluate_and_renew(
        self,
        lease: dict[str, Any],
        observed_at: datetime,
    ) -> OwnershipState:
        metadata = lease.get("metadata") or {}
        spec = lease.get("spec") or {}
        holder = spec.get("holderIdentity")
        resource_version = metadata.get("resourceVersion")
        duration = spec.get("leaseDurationSeconds")
        renew_time = _parse_time(spec.get("renewTime"))
        owner = self.settings.execution_owner_id
        if (
            not isinstance(holder, str)
            or not holder
            or not isinstance(resource_version, str)
            or not resource_version
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration != self.settings.execution_lease_duration_seconds
        ):
            return self._blocked(
                observed_at,
                "execution_lease_contract_invalid",
                holder=holder if isinstance(holder, str) else None,
                renew_time=renew_time,
                duration=duration if isinstance(duration, int) else None,
                resource_version=resource_version,
            )

        uninitialized = renew_time is None
        expired = (
            renew_time is not None
            and observed_at >= renew_time + timedelta(seconds=duration)
        )
        if holder != owner:
            lease_valid = not uninitialized and not expired
            return OwnershipState(
                configured_mode=self.settings.execution_mode,
                effective_mode=(
                    "SHADOW"
                    if lease_valid and self.settings.execution_mode == "SHADOW"
                    else "STANDBY"
                ),
                enabled=True,
                lease_namespace=self.settings.execution_lease_namespace,
                lease_name=self.settings.execution_lease_name,
                holder_identity=holder,
                owner_identity=owner,
                lease_valid=lease_valid,
                renew_time=renew_time,
                lease_duration_seconds=duration,
                resource_version=resource_version,
                reason_code=(
                    "execution_lease_uninitialized"
                    if uninitialized
                    else "execution_lease_expired"
                    if expired
                    else "execution_owner_not_holder"
                ),
                observed_at=observed_at,
            )
        if expired:
            return self._blocked(
                observed_at,
                "execution_lease_expired",
                holder=holder,
                renew_time=renew_time,
                duration=duration,
                resource_version=resource_version,
            )

        # An uninitialized Git-owned Lease can be activated only by its exact
        # predeclared holder. Expired holders are never resurrected here.
        renewed_spec = dict(spec)
        renewed_spec["renewTime"] = _format_time(observed_at)
        if uninitialized:
            renewed_spec["acquireTime"] = _format_time(observed_at)
        body = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": self.settings.execution_lease_name,
                "namespace": self.settings.execution_lease_namespace,
                "resourceVersion": resource_version,
                **(
                    {"labels": dict(metadata["labels"])}
                    if isinstance(metadata.get("labels"), dict)
                    else {}
                ),
                **(
                    {"annotations": dict(metadata["annotations"])}
                    if isinstance(metadata.get("annotations"), dict)
                    else {}
                ),
            },
            "spec": renewed_spec,
        }
        renewed = await self.client.replace(
            self.settings.execution_lease_namespace,
            self.settings.execution_lease_name,
            body,
        )
        renewed_metadata = renewed.get("metadata") or {}
        renewed_spec = renewed.get("spec") or {}
        confirmed_holder = renewed_spec.get("holderIdentity")
        confirmed_renew = _parse_time(renewed_spec.get("renewTime"))
        if confirmed_holder != owner or confirmed_renew is None:
            return self._blocked(
                observed_at,
                "execution_lease_cas_conflict",
                holder=confirmed_holder,
                renew_time=confirmed_renew,
                duration=duration,
                resource_version=renewed_metadata.get("resourceVersion"),
            )
        return OwnershipState(
            configured_mode=self.settings.execution_mode,
            effective_mode="ACTIVE",
            enabled=True,
            lease_namespace=self.settings.execution_lease_namespace,
            lease_name=self.settings.execution_lease_name,
            holder_identity=confirmed_holder,
            owner_identity=owner,
            lease_valid=True,
            renew_time=confirmed_renew,
            lease_duration_seconds=duration,
            resource_version=renewed_metadata.get("resourceVersion"),
            reason_code=None,
            observed_at=observed_at,
        )

    def _blocked(
        self,
        observed_at: datetime,
        reason: str,
        *,
        holder: str | None = None,
        renew_time: datetime | None = None,
        duration: int | None = None,
        resource_version: str | None = None,
    ) -> OwnershipState:
        return OwnershipState(
            configured_mode=self.settings.execution_mode,
            effective_mode="STANDBY",
            enabled=True,
            lease_namespace=self.settings.execution_lease_namespace,
            lease_name=self.settings.execution_lease_name,
            holder_identity=holder,
            owner_identity=self.settings.execution_owner_id,
            lease_valid=False,
            renew_time=renew_time,
            lease_duration_seconds=duration,
            resource_version=resource_version,
            reason_code=reason,
            observed_at=observed_at,
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.execution_lease_poll_interval_seconds,
                )
            except TimeoutError:
                await self.refresh_once()


def build_execution_ownership_guard(settings: Settings) -> ExecutionOwnershipGuard | None:
    if not settings.execution_ownership_enabled:
        return None
    return ExecutionOwnershipGuard(
        settings,
        KubernetesLeaseClient(api_url=settings.execution_kubernetes_api_url),
    )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
