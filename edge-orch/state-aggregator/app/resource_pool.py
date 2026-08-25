from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from kubernetes.utils.quantity import parse_quantity

from .models import (
    NodeResourceUtilization,
    NodeSchedulingResource,
    NodeState,
    SchedulingResourceAmounts,
)


@dataclass(frozen=True)
class KubernetesNodeResourceSnapshot:
    node: str
    ready: bool
    unschedulable: bool
    architecture: str | None
    node_type: str | None
    labels: dict[str, str]
    allocatable: SchedulingResourceAmounts
    requested: SchedulingResourceAmounts


def build_kubernetes_resource_snapshots(
    nodes: list[Any],
    pods: list[Any],
    node_type_for: Callable[[Any], str],
) -> list[KubernetesNodeResourceSnapshot]:
    requested_by_node: dict[str, SchedulingResourceAmounts] = {}
    for pod in pods:
        spec = getattr(pod, "spec", None)
        status = getattr(pod, "status", None)
        node_name = getattr(spec, "node_name", None)
        phase = getattr(status, "phase", None)
        if not node_name or phase in {"Succeeded", "Failed"}:
            continue
        requested_by_node[node_name] = _add_amounts(
            requested_by_node.get(node_name, _empty_amounts()),
            _pod_requests(pod),
        )

    snapshots: list[KubernetesNodeResourceSnapshot] = []
    for node in nodes:
        metadata = getattr(node, "metadata", None)
        spec = getattr(node, "spec", None)
        status = getattr(node, "status", None)
        node_name = getattr(metadata, "name", None)
        if not node_name:
            continue
        labels = dict(getattr(metadata, "labels", None) or {})
        snapshots.append(
            KubernetesNodeResourceSnapshot(
                node=node_name,
                ready=_node_ready(status),
                unschedulable=bool(getattr(spec, "unschedulable", False)),
                architecture=labels.get("kubernetes.io/arch"),
                node_type=node_type_for(node),
                labels=labels,
                allocatable=_resource_amounts(getattr(status, "allocatable", None) or {}),
                requested=requested_by_node.get(node_name, _empty_amounts()),
            )
        )
    return sorted(snapshots, key=lambda item: item.node)


def build_node_scheduling_resources(
    snapshots: list[KubernetesNodeResourceSnapshot],
    node_states: list[NodeState],
) -> list[NodeSchedulingResource]:
    state_by_node = {state.hostname: state for state in node_states}
    resources: list[NodeSchedulingResource] = []
    for snapshot in snapshots:
        node_state = state_by_node.get(snapshot.node)
        available = _subtract_amounts(snapshot.allocatable, snapshot.requested)
        health = (
            node_state.node_health
            if snapshot.ready and node_state is not None
            else "unavailable"
        )
        reason_codes = _reason_codes(snapshot, node_state, available)
        resources.append(
            NodeSchedulingResource(
                node=snapshot.node,
                cpu_available=available.cpu_cores,
                memory_available_gb=round(available.memory_bytes / 1_000_000_000, 3),
                accelerator=_accelerator_identity(snapshot),
                health=health,
                schedulable=bool(
                    snapshot.ready
                    and not snapshot.unschedulable
                    and node_state is not None
                    and health != "unavailable"
                ),
                reason_codes=reason_codes,
                architecture=snapshot.architecture,
                node_type=snapshot.node_type,
                allocatable=snapshot.allocatable,
                requested=snapshot.requested,
                available=available,
                utilization=_utilization(node_state),
            )
        )
    return resources


def _pod_requests(pod: Any) -> SchedulingResourceAmounts:
    spec = getattr(pod, "spec", None)
    return pod_spec_requests(spec)


def pod_spec_requests(spec: Any) -> SchedulingResourceAmounts:
    """Calculate the scheduler-effective requests for a Pod spec/template."""
    regular = _empty_amounts()
    for container in getattr(spec, "containers", None) or []:
        regular = _add_amounts(regular, _container_resources(container, "requests"))

    effective = regular
    for container in getattr(spec, "init_containers", None) or []:
        effective = _max_amounts(
            effective,
            _container_resources(container, "requests"),
        )

    overhead = _resource_amounts(getattr(spec, "overhead", None) or {})
    return _add_amounts(effective, overhead)


def pod_spec_limits(spec: Any) -> SchedulingResourceAmounts:
    """Calculate effective declared limits for one Pod template."""
    regular = _empty_amounts()
    for container in getattr(spec, "containers", None) or []:
        regular = _add_amounts(regular, _container_resources(container, "limits"))
    effective = regular
    for container in getattr(spec, "init_containers", None) or []:
        effective = _max_amounts(
            effective,
            _container_resources(container, "limits"),
        )
    return effective


def _container_resources(
    container: Any,
    field_name: str,
) -> SchedulingResourceAmounts:
    resources = getattr(container, "resources", None)
    return _resource_amounts(getattr(resources, field_name, None) or {})


def _resource_amounts(values: dict[str, Any]) -> SchedulingResourceAmounts:
    accelerator_units = {
        name: _quantity(value)
        for name, value in values.items()
        if _is_accelerator_resource(name)
    }
    return SchedulingResourceAmounts(
        cpu_cores=round(_quantity(values.get("cpu")), 6),
        memory_bytes=max(0, int(_quantity(values.get("memory")))),
        accelerator_units={
            name: round(amount, 6)
            for name, amount in sorted(accelerator_units.items())
        },
    )


def _empty_amounts() -> SchedulingResourceAmounts:
    return SchedulingResourceAmounts(cpu_cores=0, memory_bytes=0)


def _add_amounts(
    left: SchedulingResourceAmounts,
    right: SchedulingResourceAmounts,
) -> SchedulingResourceAmounts:
    accelerator_names = set(left.accelerator_units) | set(right.accelerator_units)
    return SchedulingResourceAmounts(
        cpu_cores=round(left.cpu_cores + right.cpu_cores, 6),
        memory_bytes=left.memory_bytes + right.memory_bytes,
        accelerator_units={
            name: round(
                left.accelerator_units.get(name, 0)
                + right.accelerator_units.get(name, 0),
                6,
            )
            for name in sorted(accelerator_names)
        },
    )


def _max_amounts(
    left: SchedulingResourceAmounts,
    right: SchedulingResourceAmounts,
) -> SchedulingResourceAmounts:
    accelerator_names = set(left.accelerator_units) | set(right.accelerator_units)
    return SchedulingResourceAmounts(
        cpu_cores=max(left.cpu_cores, right.cpu_cores),
        memory_bytes=max(left.memory_bytes, right.memory_bytes),
        accelerator_units={
            name: max(
                left.accelerator_units.get(name, 0),
                right.accelerator_units.get(name, 0),
            )
            for name in sorted(accelerator_names)
        },
    )


def _subtract_amounts(
    allocatable: SchedulingResourceAmounts,
    requested: SchedulingResourceAmounts,
) -> SchedulingResourceAmounts:
    accelerator_names = set(allocatable.accelerator_units)
    return SchedulingResourceAmounts(
        cpu_cores=round(max(0, allocatable.cpu_cores - requested.cpu_cores), 6),
        memory_bytes=max(0, allocatable.memory_bytes - requested.memory_bytes),
        accelerator_units={
            name: round(
                max(
                    0,
                    allocatable.accelerator_units.get(name, 0)
                    - requested.accelerator_units.get(name, 0),
                ),
                6,
            )
            for name in sorted(accelerator_names)
        },
    )


def _node_ready(status: Any) -> bool:
    for condition in getattr(status, "conditions", None) or []:
        if getattr(condition, "type", None) == "Ready":
            return getattr(condition, "status", None) == "True"
    return False


def _is_accelerator_resource(name: str) -> bool:
    lowered = name.lower()
    return "/" in lowered and any(
        token in lowered for token in ("gpu", "npu", "tpu", "accelerator")
    )


def _quantity(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(parse_quantity(str(value)))
    except (TypeError, ValueError):
        return 0.0


def _accelerator_identity(snapshot: KubernetesNodeResourceSnapshot) -> str | None:
    for key in (
        "nvidia.com/gpu.product",
        "accelerator",
        "accelerator-type",
        "gpu.product",
    ):
        if snapshot.labels.get(key):
            return snapshot.labels[key]
    if snapshot.labels.get("edge.device/class") == "jetson":
        return "JetsonGPU"
    if any(
        amount > 0 and "nvidia" in name.lower()
        for name, amount in snapshot.allocatable.accelerator_units.items()
    ):
        return "nvidia-gpu"
    return None


def _utilization(node_state: NodeState | None) -> NodeResourceUtilization | None:
    if node_state is None:
        return None
    metrics = node_state.raw_metrics
    return NodeResourceUtilization(
        cpu_ratio=_optional_number(metrics.get("cpu_utilization")),
        memory_ratio=_optional_number(metrics.get("memory_usage_ratio")),
        gpu_ratio=_optional_number(metrics.get("gpu_utilization")),
        gpu_memory_ratio=_optional_number(metrics.get("gpu_memory_usage_ratio")),
        load_average=_optional_number(metrics.get("load_average")),
        network_rx_bytes_per_second=_optional_number(metrics.get("network_rx_rate")),
        network_tx_bytes_per_second=_optional_number(metrics.get("network_tx_rate")),
        observed_at=node_state.collected_at,
    )


def _reason_codes(
    snapshot: KubernetesNodeResourceSnapshot,
    node_state: NodeState | None,
    available: SchedulingResourceAmounts,
) -> list[str]:
    reasons: list[str] = []
    if not snapshot.ready:
        reasons.append("node_not_ready")
    if snapshot.unschedulable:
        reasons.append("node_unschedulable")
    if node_state is None:
        reasons.append("prometheus_metrics_unavailable")
    elif node_state.node_health == "degraded":
        reasons.append("node_health_degraded")
    elif node_state.node_health == "unavailable":
        reasons.append("node_health_unavailable")
    if available.cpu_cores <= 0:
        reasons.append("cpu_requests_exhaust_allocatable")
    if available.memory_bytes <= 0:
        reasons.append("memory_requests_exhaust_allocatable")
    if set(snapshot.requested.accelerator_units) - set(
        snapshot.allocatable.accelerator_units
    ):
        reasons.append("accelerator_capacity_unreported")
    return reasons or ["ready"]


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
