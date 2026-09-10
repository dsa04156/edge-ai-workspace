"""Pure placement filtering. Kubernetes scheduler is the final reservation authority."""
from dataclasses import dataclass
from decimal import Decimal

from kubernetes.utils.quantity import parse_quantity

from .contract import ServiceSpec, Variant


@dataclass(frozen=True)
class Candidate:
    node: str
    role: str
    variant: Variant


def quantities(values):
    return {k: parse_quantity(v) for k, v in values.items()}


def pod_requests(pod):
    """Scheduling requests include init containers, restartable init sidecars and overhead."""
    spec = pod.get("spec", {})
    steady, init_peak = {}, {}

    def add(dst, src):
        for k, v in src.items():
            dst[k] = dst.get(k, Decimal(0)) + v

    for c in spec.get("containers", []):
        add(steady, quantities(c.get("resources", {}).get("requests", {})))
    sidecars = {}
    for c in spec.get("initContainers", []):
        q = quantities(c.get("resources", {}).get("requests", {}))
        if c.get("restartPolicy") == "Always":
            add(sidecars, q)
            current = dict(sidecars)
        else:
            current = dict(sidecars)
            add(current, q)
        for k, v in current.items():
            init_peak[k] = max(init_peak.get(k, 0), v)
    add(steady, sidecars)
    for k, v in init_peak.items():
        steady[k] = max(steady.get(k, 0), v)
    add(steady, quantities(spec.get("overhead", {})))
    steady["pods"] = Decimal(1)
    return steady


def candidates(spec: ServiceSpec, nodes: list[dict], pods: list[dict], runtime_classes: list[dict],
               existing_revisions: dict | None = None, snapshot: dict | None = None):
    """existing_revisions maps (node, variant) to owned revision identity.

    Its own reservations are credited only for that same revision; never credit
    a different service, retiring revision or a different accelerator backend.
    """
    classes = {c["metadata"]["name"]: c for c in runtime_classes}
    accepted, rejected = [], []
    for node in nodes:
        name = node["metadata"]["name"]
        labels = node["metadata"].get("labels", {})
        # Explicit role labels, never hostname prefix inference.
        role = ("edge" if "node-role.kubernetes.io/edge" in labels else "server"
                if any(k in labels for k in ("node-role.kubernetes.io/worker",
                       "node-role.kubernetes.io/control-plane")) else labels.get("platform.jinuk.io/role"))
        conditions = {c["type"]: c["status"] for c in node.get("status", {}).get("conditions", [])}
        base = []
        if conditions.get("Ready") != "True":
            base.append("node_not_ready")
        if any(conditions.get(k) != "False" for k in ("MemoryPressure", "DiskPressure", "PIDPressure")):
            base.append("node_pressure_or_unknown")
        if node.get("spec", {}).get("unschedulable"):
            base.append("node_cordoned")
        if role not in spec.policy.allowedRoles:
            base.append("role_not_allowed")
        if any(t.get("effect") in ("NoSchedule", "NoExecute") for t in node.get("spec", {}).get("taints", [])):
            base.append("untolerated_taint")
        for variant in spec.variants:
            reasons = list(base)
            selectors = [spec.policy.nodeSelector, variant.nodeSelector,
                         {"kubernetes.io/arch": variant.architecture, "kubernetes.io/os": "linux"}]
            runtime = classes.get(variant.runtimeClassName)
            overhead = {}
            if variant.runtimeClassName:
                if runtime is None:
                    reasons.append("runtime_class_missing")
                else:
                    selectors.append(runtime.get("scheduling", {}).get("nodeSelector", {}))
                    overhead = quantities(runtime.get("overhead", {}).get("podFixed", {}))
            if any(labels.get(k) != v for s in selectors for k, v in s.items()):
                reasons.append("selector_or_architecture_mismatch")
            if variant.resident:
                from .resident import verify_binding, matching_pods
                reason = verify_binding(variant.resident, variant.image, name, snapshot or {"pods": pods, "deployments": []}, spec.port)
                if reason:
                    reasons.append(reason)
                else:
                    bound = matching_pods(variant.resident, pods)[0]
                    container = next(c for c in bound["spec"]["containers"] if c["name"] == variant.resident.container)
                    reserved = quantities(container.get("resources", {}).get("requests", {}))
                    if any(reserved.get(k, 0) < v for k, v in quantities(variant.requests).items()):
                        reasons.append("resident_reservation_below_contract")
                    if bound["spec"].get("runtimeClassName") != variant.runtimeClassName:
                        reasons.append("resident_runtime_class_mismatch")
                if reasons:
                    rejected.append({"node": name, "variant": variant.name, "reasons": sorted(set(reasons))})
                else:
                    accepted.append(Candidate(name, role, variant))
                continue  # Existing Pod already owns its reservation; no second GPU request.
            available = quantities(node.get("status", {}).get("allocatable", {}))
            credited = (existing_revisions or {}).get((name, variant.name))
            credited_one = False
            for pod in pods:
                if pod.get("spec", {}).get("nodeName") != name or pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
                    continue
                meta = pod["metadata"]
                if (credited and not credited_one and not meta.get("deletionTimestamp")
                        and meta.get("namespace") == credited["namespace"]
                        and meta.get("labels", {}).get("platform.jinuk.io/revision") == credited["name"]
                        and meta.get("labels", {}).get("platform.jinuk.io/service-uid") == credited["uid"]):
                    credited_one = True
                    continue
                for k, v in pod_requests(pod).items():
                    available[k] = available.get(k, 0) - v
            required = quantities(variant.requests)
            required["pods"] = Decimal(1)
            for k, v in overhead.items():
                required[k] = required.get(k, 0) + v
            for k, v in required.items():
                if available.get(k, 0) < v:
                    reasons.append("insufficient:" + k)
            if reasons:
                rejected.append({"node": name, "variant": variant.name, "reasons": sorted(set(reasons))})
            else:
                accepted.append(Candidate(name, role, variant))
    accepted.sort(key=lambda c: (c.role != spec.policy.preferredRole, c.variant.maxInFlight, c.node, c.variant.name))
    return accepted, rejected
