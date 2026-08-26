from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .kube import KubeDeploymentError
from .models import SchedulingModel


class ExecutionOwnershipError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ExecutionOwnershipSource(SchedulingModel):
    namespace: str
    workload: str
    holder_identity: str


class ExecutionOwnershipContract(SchedulingModel):
    service_id: str
    contract_version: str
    mode: Literal["runtime-lease"]
    namespace: str
    lease_name: str
    lease_duration_seconds: int = Field(ge=5, le=300)
    managed_by: Literal["runtime-execution-controller"]
    source: ExecutionOwnershipSource
    candidate_holder_pattern: Literal["{candidateName}"] = "{candidateName}"

    @model_validator(mode="after")
    def validate_source(self) -> "ExecutionOwnershipContract":
        if self.source.namespace != self.namespace:
            raise ValueError("source and Lease namespace must match")
        return self

    def candidate_holder(self, candidate_name: str) -> str:
        return self.candidate_holder_pattern.format(candidateName=candidate_name)


class ExecutionOwnershipContractCatalog(SchedulingModel):
    api_version: Literal["edge-ai.io/v1alpha1"]
    kind: Literal["ExecutionOwnershipContractCatalog"]
    contracts: list[ExecutionOwnershipContract]


class OwnershipContractCatalog:
    def __init__(
        self,
        contracts: dict[str, ExecutionOwnershipContract],
        errors: dict[str, str] | None = None,
    ) -> None:
        self.contracts = contracts
        self.errors = errors or {}

    @classmethod
    def load(cls, path: Path) -> "OwnershipContractCatalog":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls({}, {"*": "execution_ownership_contract_invalid"})
        if not isinstance(payload, dict) or not isinstance(payload.get("contracts"), list):
            return cls({}, {"*": "execution_ownership_contract_invalid"})
        contracts: dict[str, ExecutionOwnershipContract] = {}
        errors: dict[str, str] = {}
        for raw in payload["contracts"]:
            service_id = raw.get("serviceId") if isinstance(raw, dict) else None
            try:
                contract = ExecutionOwnershipContract.model_validate(raw)
            except Exception:
                errors[str(service_id or "*")] = "execution_ownership_contract_invalid"
                continue
            if contract.service_id in contracts:
                errors[contract.service_id] = "execution_ownership_contract_invalid"
                contracts.pop(contract.service_id, None)
                continue
            contracts[contract.service_id] = contract
        try:
            ExecutionOwnershipContractCatalog.model_validate(
                {
                    **payload,
                    "contracts": [
                        item.model_dump(by_alias=True) for item in contracts.values()
                    ],
                }
            )
        except Exception:
            return cls({}, {"*": "execution_ownership_contract_invalid"})
        return cls(contracts, errors)

    def resolve(
        self,
        service_id: str,
    ) -> tuple[ExecutionOwnershipContract | None, str | None]:
        if service_id in self.errors or "*" in self.errors:
            return None, "execution_ownership_contract_invalid"
        contract = self.contracts.get(service_id)
        if contract is None:
            return None, "execution_ownership_contract_not_found"
        return contract, None


class LeaseSnapshot(SchedulingModel):
    namespace: str
    name: str
    holder_identity: str
    lease_duration_seconds: int
    acquire_time: datetime | None = None
    renew_time: datetime | None = None
    lease_transitions: int = Field(default=0, ge=0)
    resource_version: str
    observed_at: datetime


class RuntimeExecutionOwnership(SchedulingModel):
    lease_namespace: str
    lease_name: str
    source_holder: str
    candidate_holder: str
    active_owner: Literal["source", "candidate"]
    before: LeaseSnapshot
    after: LeaseSnapshot | None = None
    handed_off_at: datetime | None = None
    rolled_back_at: datetime | None = None
    rollback_available: bool = True


OwnershipObserver = Callable[[RuntimeExecutionOwnership], Awaitable[None] | None]


class ExecutionOwnershipEngine:
    def __init__(
        self,
        kube: Any,
        *,
        now: Callable[[], datetime] | None = None,
        cas_attempts: int = 3,
    ) -> None:
        self.kube = kube
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.cas_attempts = cas_attempts

    async def handoff(
        self,
        *,
        contract: ExecutionOwnershipContract,
        candidate_name: str,
        observer: OwnershipObserver | None = None,
    ) -> RuntimeExecutionOwnership:
        candidate_holder = contract.candidate_holder(candidate_name)
        last_error = "execution_ownership_state_conflict"
        for _ in range(self.cas_attempts):
            lease = await self._read(contract)
            before = self._snapshot(contract, lease)
            self._validate_managed(contract, lease)
            if before.holder_identity == candidate_holder:
                if not _valid(before, self.now()):
                    raise ExecutionOwnershipError("execution_lease_expired")
                return RuntimeExecutionOwnership(
                    lease_namespace=contract.namespace,
                    lease_name=contract.lease_name,
                    source_holder=contract.source.holder_identity,
                    candidate_holder=candidate_holder,
                    active_owner="candidate",
                    before=before,
                    after=before,
                    handed_off_at=before.observed_at,
                )
            if before.holder_identity != contract.source.holder_identity:
                raise ExecutionOwnershipError("execution_ownership_state_conflict")
            if not _valid(before, self.now()):
                raise ExecutionOwnershipError("execution_lease_expired")
            ownership = RuntimeExecutionOwnership(
                lease_namespace=contract.namespace,
                lease_name=contract.lease_name,
                source_holder=contract.source.holder_identity,
                candidate_holder=candidate_holder,
                active_owner="source",
                before=before,
            )
            if observer is not None:
                observed = observer(ownership)
                if observed is not None:
                    await observed
            now = self.now()
            body = _replacement_body(
                contract,
                before,
                holder=candidate_holder,
                now=now,
                transitions=before.lease_transitions + 1,
            )
            try:
                replaced = await self.kube.replace_lease(
                    contract.namespace,
                    contract.lease_name,
                    body,
                )
            except KubeDeploymentError as exc:
                last_error = exc.reason_code
                if exc.reason_code == "execution_lease_cas_conflict":
                    continue
                raise ExecutionOwnershipError(exc.reason_code) from exc
            after = self._snapshot(contract, replaced)
            if after.holder_identity != candidate_holder:
                raise ExecutionOwnershipError("execution_ownership_state_conflict")
            ownership.active_owner = "candidate"
            ownership.after = after
            ownership.handed_off_at = now
            return ownership
        raise ExecutionOwnershipError(last_error)

    async def rollback(
        self,
        *,
        contract: ExecutionOwnershipContract,
        ownership: RuntimeExecutionOwnership,
    ) -> RuntimeExecutionOwnership:
        for _ in range(self.cas_attempts):
            lease = await self._read(contract)
            current = self._snapshot(contract, lease)
            self._validate_managed(contract, lease)
            if current.holder_identity == ownership.source_holder:
                ownership.active_owner = "source"
                ownership.after = current
                ownership.rolled_back_at = self.now()
                return ownership
            if current.holder_identity != ownership.candidate_holder:
                raise ExecutionOwnershipError("execution_ownership_state_conflict")
            now = self.now()
            body = _replacement_body(
                contract,
                current,
                holder=ownership.source_holder,
                now=now,
                transitions=current.lease_transitions + 1,
            )
            try:
                replaced = await self.kube.replace_lease(
                    contract.namespace,
                    contract.lease_name,
                    body,
                )
            except KubeDeploymentError as exc:
                if exc.reason_code == "execution_lease_cas_conflict":
                    continue
                raise ExecutionOwnershipError(exc.reason_code) from exc
            after = self._snapshot(contract, replaced)
            if after.holder_identity != ownership.source_holder:
                raise ExecutionOwnershipError("execution_ownership_rollback_failed")
            ownership.active_owner = "source"
            ownership.after = after
            ownership.rolled_back_at = now
            return ownership
        raise ExecutionOwnershipError("execution_ownership_rollback_failed")

    async def _read(self, contract: ExecutionOwnershipContract) -> Any:
        try:
            return await self.kube.read_lease(contract.namespace, contract.lease_name)
        except KubeDeploymentError as exc:
            raise ExecutionOwnershipError(exc.reason_code) from exc

    def _snapshot(
        self,
        contract: ExecutionOwnershipContract,
        lease: Any,
    ) -> LeaseSnapshot:
        data = _object_dict(lease)
        metadata = data.get("metadata") or {}
        spec = data.get("spec") or {}
        holder = spec.get("holderIdentity")
        duration = spec.get("leaseDurationSeconds")
        resource_version = metadata.get("resourceVersion")
        if (
            not isinstance(holder, str)
            or not holder
            or isinstance(duration, bool)
            or not isinstance(duration, int)
            or duration != contract.lease_duration_seconds
            or not isinstance(resource_version, str)
            or not resource_version
        ):
            raise ExecutionOwnershipError("execution_ownership_contract_invalid")
        return LeaseSnapshot(
            namespace=contract.namespace,
            name=contract.lease_name,
            holder_identity=holder,
            lease_duration_seconds=duration,
            acquire_time=_parse_time(spec.get("acquireTime")),
            renew_time=_parse_time(spec.get("renewTime")),
            lease_transitions=int(spec.get("leaseTransitions") or 0),
            resource_version=resource_version,
            observed_at=self.now(),
        )

    @staticmethod
    def _validate_managed(
        contract: ExecutionOwnershipContract,
        lease: Any,
    ) -> None:
        data = _object_dict(lease)
        labels = (data.get("metadata") or {}).get("labels") or {}
        if (
            labels.get("edge-ai.io/managed-by") != contract.managed_by
            or labels.get("edge-ai.io/service-id") != contract.service_id
        ):
            raise ExecutionOwnershipError("execution_lease_ownership_conflict")


def _replacement_body(
    contract: ExecutionOwnershipContract,
    current: LeaseSnapshot,
    *,
    holder: str,
    now: datetime,
    transitions: int,
) -> dict[str, Any]:
    instant = _format_time(now)
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": {
            "name": contract.lease_name,
            "namespace": contract.namespace,
            "resourceVersion": current.resource_version,
            "labels": {
                "edge-ai.io/managed-by": contract.managed_by,
                "edge-ai.io/service-id": contract.service_id,
            },
        },
        "spec": {
            "holderIdentity": holder,
            "leaseDurationSeconds": contract.lease_duration_seconds,
            "acquireTime": instant,
            "renewTime": instant,
            "leaseTransitions": transitions,
        },
    }


def _valid(snapshot: LeaseSnapshot, now: datetime) -> bool:
    return snapshot.renew_time is not None and now < snapshot.renew_time + timedelta(
        seconds=snapshot.lease_duration_seconds
    )


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _object_dict(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {_camel_key(str(key)): _object_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_object_dict(item) for item in value]
    if hasattr(value, "to_dict"):
        return _object_dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            _camel_key(key): _object_dict(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _camel_key(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)
