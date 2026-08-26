from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .models import SchedulingModel


MANAGED_BY = "runtime-execution-controller.edge-ai.io"
MANAGED_BY_LABEL = "edge-ai.io/managed-by"


class TrafficRoutingError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class TrafficSourceContract(SchedulingModel):
    workload: str
    selector: dict[str, str] = Field(min_length=1)


class TrafficSwitchPolicy(SchedulingModel):
    require_candidate_validation: Literal[True] = True
    post_switch_observation_seconds: float = Field(ge=1, le=600)
    poll_interval_seconds: float = Field(gt=0, le=60)
    timeout_seconds: float = Field(gt=0, le=600)
    required_consecutive_successes: int = Field(ge=1, le=1000)
    counter_pointer: str | None = None

    @field_validator("counter_pointer")
    @classmethod
    def validate_counter_pointer(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("counter pointer must be a JSON Pointer")
        return value


class TrafficRollbackPolicy(SchedulingModel):
    enabled: Literal[True] = True
    target: Literal["source"] = "source"


class TrafficRoutingContract(SchedulingModel):
    service_id: str
    contract_version: str
    mode: Literal["runtime-endpointslice"]
    compatibility_status: Literal["verified", "blocked"]
    compatibility_reason_codes: list[str] = Field(default_factory=list)
    service_name: str
    namespace: str
    endpoint_slice_name: str
    port_name: str
    port: int = Field(ge=1, le=65535)
    protocol: Literal["TCP", "UDP", "SCTP"] = "TCP"
    source: TrafficSourceContract
    switch_policy: TrafficSwitchPolicy
    rollback_policy: TrafficRollbackPolicy

    @model_validator(mode="after")
    def validate_compatibility(self) -> "TrafficRoutingContract":
        if self.compatibility_status == "blocked" and not self.compatibility_reason_codes:
            raise ValueError("blocked routing contracts require a reason")
        return self


class TrafficRoutingContractCatalog(SchedulingModel):
    api_version: Literal["edge-ai.io/v1alpha1"]
    kind: Literal["TrafficRoutingContractCatalog"]
    contracts: list[TrafficRoutingContract]


class RoutingContractCatalog:
    def __init__(self, contracts: dict[str, TrafficRoutingContract], errors: dict[str, str] | None = None) -> None:
        self.contracts = contracts
        self.errors = errors or {}

    @classmethod
    def load(cls, path: Path) -> "RoutingContractCatalog":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls({}, {"*": "routing_contract_invalid"})
        contracts: dict[str, TrafficRoutingContract] = {}
        errors: dict[str, str] = {}
        for raw in payload.get("contracts", []) if isinstance(payload, dict) else []:
            service_id = raw.get("serviceId") if isinstance(raw, dict) else None
            try:
                contract = TrafficRoutingContract.model_validate(raw)
            except Exception:
                errors[str(service_id or "*")] = "routing_contract_invalid"
                continue
            if contract.service_id in contracts:
                errors[contract.service_id] = "routing_contract_invalid"
                contracts.pop(contract.service_id, None)
            else:
                contracts[contract.service_id] = contract
        try:
            TrafficRoutingContractCatalog.model_validate({**payload, "contracts": [item.model_dump(by_alias=True) for item in contracts.values()]})
        except Exception:
            return cls({}, {"*": "routing_contract_invalid"})
        return cls(contracts, errors)

    def resolve(self, service_id: str) -> tuple[TrafficRoutingContract | None, str | None]:
        if service_id in self.errors or "*" in self.errors:
            return None, "routing_contract_invalid"
        contract = self.contracts.get(service_id)
        return (contract, None) if contract else (None, "routing_contract_not_found")


class RoutingSnapshot(SchedulingModel):
    endpoint_slice_name: str
    resource_version: str
    active_target: Literal["source", "candidate", "unknown"]
    address_type: str
    addresses: list[str]
    endpoints: list[dict[str, Any]]
    ports: list[dict[str, Any]]
    labels: dict[str, str]
    observed_at: datetime


class RuntimeExecutionRouting(SchedulingModel):
    service_id: str
    namespace: str
    service: str
    mode: str
    active_target: Literal["source", "candidate", "unknown"] = "source"
    source_node: str | None = None
    candidate_node: str | None = None
    switched_at: datetime | None = None
    rolled_back_at: datetime | None = None
    rollback_available: bool = False
    before: RoutingSnapshot | None = None
    after: RoutingSnapshot | None = None
    rollback: RoutingSnapshot | None = None
    reason_codes: list[str] = Field(default_factory=list)


class TrafficRoutingEngine:
    def __init__(self, kube: Any) -> None:
        self.kube = kube

    async def observe(self, contract: TrafficRoutingContract) -> RoutingSnapshot:
        value = _object_dict(
            await self.kube.read_endpoint_slice(
                contract.namespace,
                contract.endpoint_slice_name,
            )
        )
        self._verify_owned(value, contract)
        return _snapshot(value)

    async def switch(
        self,
        *,
        contract: TrafficRoutingContract,
        plan_id: str,
        candidate_namespace: str,
        candidate_name: str,
        candidate_node: str,
        snapshot_observer: Callable[[RuntimeExecutionRouting], Awaitable[None] | None] | None = None,
    ) -> RuntimeExecutionRouting:
        if contract.compatibility_status != "verified":
            raise TrafficRoutingError(contract.compatibility_reason_codes[0] or "routing_mode_unsupported")
        service = _object_dict(await self.kube.read_service(contract.namespace, contract.service_name))
        if (_get(service, "spec", "selector") or {}):
            raise TrafficRoutingError("routing_precondition_failed")
        ports = _get(service, "spec", "ports") or []
        if not any(item.get("name") == contract.port_name and item.get("port") == contract.port for item in ports):
            raise TrafficRoutingError("routing_contract_invalid")

        slices = await self.kube.list_endpoint_slices(contract.namespace, contract.service_name)
        if len(slices) != 1:
            raise TrafficRoutingError("endpointslice_ownership_conflict" if slices else "source_endpoint_unavailable")
        current = _object_dict(slices[0])
        self._verify_owned(current, contract)
        before = _snapshot(current)
        if before.active_target != "source":
            raise TrafficRoutingError("routing_state_conflict")

        source_pod = await self._ready_pod(contract.namespace, contract.source.selector, None, None)
        if source_pod is None:
            raise TrafficRoutingError("source_endpoint_unavailable")
        candidate_pod = await self._ready_pod(candidate_namespace, {"edge-ai.io/deployment": candidate_name}, candidate_node, plan_id)
        if candidate_pod is None:
            raise TrafficRoutingError("candidate_endpoint_unavailable")
        source_ip = _pod_ip(source_pod)
        candidate_ip = _pod_ip(candidate_pod)
        if not source_ip or source_ip not in before.addresses:
            raise TrafficRoutingError("routing_state_conflict")
        if not candidate_ip:
            raise TrafficRoutingError("candidate_endpoint_unavailable")

        pending = RuntimeExecutionRouting(
            service_id=contract.service_id,
            namespace=contract.namespace,
            service=contract.service_name,
            mode=contract.mode,
            active_target="source",
            source_node=_pod_node(source_pod),
            candidate_node=_pod_node(candidate_pod),
            rollback_available=True,
            before=before,
        )
        if snapshot_observer is not None:
            observed = snapshot_observer(pending.model_copy(deep=True))
            if isinstance(observed, Awaitable):
                await observed

        body = _replacement_body(
            current,
            contract=contract,
            plan_id=plan_id,
            target="candidate",
            pod=candidate_pod,
            address=candidate_ip,
        )
        changed = await self.kube.replace_endpoint_slice(contract.namespace, contract.endpoint_slice_name, body)
        after = _snapshot(_object_dict(changed))
        if after.addresses != [candidate_ip] or after.active_target != "candidate":
            raise TrafficRoutingError("routing_state_conflict")
        now = _utc_now()
        pending.active_target = "candidate"
        pending.switched_at = now
        pending.after = after
        return pending

    async def rollback(self, *, contract: TrafficRoutingContract, plan_id: str, routing: RuntimeExecutionRouting) -> RuntimeExecutionRouting:
        if not routing.rollback_available or routing.before is None:
            raise TrafficRoutingError("traffic_rollback_failed")
        current = _object_dict(await self.kube.read_endpoint_slice(contract.namespace, contract.endpoint_slice_name))
        self._verify_owned(current, contract)
        snapshot = _snapshot(current)
        if routing.after is None:
            if snapshot.addresses != routing.before.addresses or snapshot.active_target != "source":
                raise TrafficRoutingError("routing_recovery_required")
            routing.active_target = "source"
            routing.rollback = snapshot
            routing.rolled_back_at = _utc_now()
            routing.reason_codes = ["traffic_rollback_succeeded"]
            return routing
        if snapshot.addresses != routing.after.addresses or snapshot.active_target != "candidate":
            raise TrafficRoutingError("routing_state_conflict")
        body = {
            "apiVersion": "discovery.k8s.io/v1",
            "kind": "EndpointSlice",
            "metadata": {
                "name": contract.endpoint_slice_name,
                "namespace": contract.namespace,
                "resourceVersion": snapshot.resource_version,
                "labels": {**routing.before.labels, "edge-ai.io/execution-plan-id": plan_id, "edge-ai.io/active-target": "source"},
            },
            "addressType": routing.before.address_type,
            "ports": routing.before.ports,
            "endpoints": routing.before.endpoints,
        }
        restored = await self.kube.replace_endpoint_slice(contract.namespace, contract.endpoint_slice_name, body)
        restored_snapshot = _snapshot(_object_dict(restored))
        if restored_snapshot.addresses != routing.before.addresses:
            raise TrafficRoutingError("traffic_rollback_failed")
        routing.active_target = "source"
        routing.rolled_back_at = _utc_now()
        routing.rollback = restored_snapshot
        routing.reason_codes = ["traffic_rollback_succeeded"]
        return routing

    async def _ready_pod(self, namespace: str, selector: dict[str, str], node: str | None, plan_id: str | None) -> Any | None:
        pods = await self.kube.list_pods(namespace, _label_selector(selector))
        for pod in pods:
            if not _pod_ready(pod) or not _pod_ip(pod):
                continue
            if node is not None and _pod_node(pod) != node:
                continue
            labels = _pod_labels(pod)
            if plan_id is not None and labels.get("edge-ai.io/execution-plan-id") != plan_id:
                continue
            return pod
        return None

    @staticmethod
    def _verify_owned(value: dict[str, Any], contract: TrafficRoutingContract) -> None:
        labels = _get(value, "metadata", "labels") or {}
        if (
            _get(value, "metadata", "name") != contract.endpoint_slice_name
            or labels.get("kubernetes.io/service-name") != contract.service_name
            or labels.get("endpointslice.kubernetes.io/managed-by") != MANAGED_BY
            or labels.get(MANAGED_BY_LABEL) != "runtime-execution-controller"
            or labels.get("edge-ai.io/service-id") != contract.service_id
            or _get(value, "metadata", "ownerReferences")
        ):
            raise TrafficRoutingError("endpointslice_ownership_conflict")


def _replacement_body(current: dict[str, Any], *, contract: TrafficRoutingContract, plan_id: str, target: str, pod: Any, address: str) -> dict[str, Any]:
    labels = dict(_get(current, "metadata", "labels") or {})
    labels.update({
        "kubernetes.io/service-name": contract.service_name,
        "endpointslice.kubernetes.io/managed-by": MANAGED_BY,
        MANAGED_BY_LABEL: "runtime-execution-controller",
        "edge-ai.io/service-id": contract.service_id,
        "edge-ai.io/execution-plan-id": plan_id,
        "edge-ai.io/routing-role": "active",
        "edge-ai.io/active-target": target,
    })
    return {
        "apiVersion": "discovery.k8s.io/v1",
        "kind": "EndpointSlice",
        "metadata": {
            "name": contract.endpoint_slice_name,
            "namespace": contract.namespace,
            "resourceVersion": str(_get(current, "metadata", "resourceVersion") or ""),
            "labels": labels,
        },
        "addressType": current.get("addressType", "IPv4"),
        "ports": [{"name": contract.port_name, "protocol": contract.protocol, "port": contract.port}],
        "endpoints": [{
            "addresses": [address],
            "conditions": {"ready": True, "serving": True, "terminating": False},
            "nodeName": _pod_node(pod),
            "targetRef": {"kind": "Pod", "namespace": _pod_namespace(pod), "name": _pod_name(pod)},
        }],
    }


def _snapshot(value: dict[str, Any]) -> RoutingSnapshot:
    endpoints = value.get("endpoints") or []
    labels = _get(value, "metadata", "labels") or {}
    target = labels.get("edge-ai.io/active-target", "unknown")
    if target not in {"source", "candidate"}:
        target = "unknown"
    return RoutingSnapshot(
        endpoint_slice_name=str(_get(value, "metadata", "name") or ""),
        resource_version=str(_get(value, "metadata", "resourceVersion") or ""),
        active_target=target,
        address_type=str(value.get("addressType") or "IPv4"),
        addresses=[address for endpoint in endpoints for address in endpoint.get("addresses", [])],
        endpoints=endpoints,
        ports=value.get("ports") or [],
        labels={str(key): str(item) for key, item in labels.items()},
        observed_at=_utc_now(),
    )


def _object_dict(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {_camel(str(key)): _object_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_object_dict(item) for item in value]
    if hasattr(value, "to_dict"):
        return _object_dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return {_camel(key): _object_dict(item) for key, item in vars(value).items() if not key.startswith("_")}
    return value


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


def _get(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _label_selector(labels: dict[str, str]) -> str:
    return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))


def _pod_ready(pod: Any) -> bool:
    status = getattr(pod, "status", None)
    return any(getattr(item, "type", None) == "Ready" and str(getattr(item, "status", "")).lower() == "true" for item in getattr(status, "conditions", None) or [])


def _pod_ip(pod: Any) -> str | None:
    return getattr(getattr(pod, "status", None), "pod_ip", None)


def _pod_node(pod: Any) -> str | None:
    return getattr(getattr(pod, "spec", None), "node_name", None)


def _pod_name(pod: Any) -> str | None:
    return getattr(getattr(pod, "metadata", None), "name", None)


def _pod_namespace(pod: Any) -> str | None:
    return getattr(getattr(pod, "metadata", None), "namespace", None)


def _pod_labels(pod: Any) -> dict[str, str]:
    return getattr(getattr(pod, "metadata", None), "labels", None) or {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
