"""Read-only virtual-device observation, with no workload mutations."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import ipaddress
import time
from typing import Any

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from kubernetes.client.exceptions import ApiException

from .virtual_resource_registry import ID_LABEL, VirtualDeviceRegistry

MAX_AGE_SECONDS = 30


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def fresh(timestamp: str | None, now: datetime | None = None) -> bool:
    try:
        age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()
        return -5 <= age <= MAX_AGE_SECONDS
    except (TypeError, ValueError, AttributeError):
        return False


def owned_by(metadata: Any, kind: str, uid: str) -> bool:
    return any(owner.kind == kind and owner.uid == uid and owner.controller is True
               for owner in (metadata.owner_references or []))


class KubernetesVirtualDeviceReader:
    def __init__(self, kube):
        self.kube = kube

    async def read(self, function, **kwargs):
        if not self.kube.enabled:
            raise RuntimeError("kubernetes_client_unavailable")
        return await asyncio.to_thread(function, **kwargs, _request_timeout=(2, 4))

    async def nodes(self):
        response = await self.read(self.kube.v1.list_node)
        return [{"name": node.metadata.name,
                 "ready": any(c.type == "Ready" and c.status == "True" for c in (node.status.conditions or []))}
                for node in response.items]

    async def workload(self, definition):
        ref = definition.spec.runtimeRef
        logical_id = definition.metadata.name
        if ref.workloadRef is None or ref.podSelector.get(ID_LABEL) != logical_id:
            raise ValueError("explicit_identity_contract_missing")
        # Namespace must exist: a missing namespace is not proof of a completed stop.
        try:
            deployment = await self.read(self.kube.apps.read_namespaced_deployment,
                                         namespace=ref.namespace, name=ref.workloadRef.name)
        except ApiException as exc:
            if exc.status != 404:
                raise
            deployment = None
        selector = f"{ID_LABEL}={logical_id}"
        pods = (await self.read(self.kube.v1.list_namespaced_pod,
                                namespace=ref.namespace, label_selector=selector)).items
        replicasets = (await self.read(self.kube.apps.list_namespaced_replica_set,
                                      namespace=ref.namespace, label_selector=selector)).items
        if deployment is None:
            if pods:
                raise ValueError("orphan_identity_pods_without_workload")
            return {"desiredReplicas": None, "workloadExists": False,
                    "plannedNodeSelector": definition.spec.nodeSelector, "instances": [], "terminalPods": []}
        if (deployment.metadata.labels or {}).get(ID_LABEL) != logical_id:
            raise ValueError("workload_identity_label_mismatch")
        rs_uids = {rs.metadata.uid for rs in replicasets
                   if (rs.metadata.labels or {}).get(ID_LABEL) == logical_id
                   and owned_by(rs.metadata, "Deployment", deployment.metadata.uid)}
        instances, terminal = [], []
        for pod in pods:
            if (pod.metadata.labels or {}).get(ID_LABEL) != logical_id:
                continue
            if not any(owned_by(pod.metadata, "ReplicaSet", uid) for uid in rs_uids):
                # Explicitly labelled orphan/wrong-owner Pods cannot be counted or probed.
                raise ValueError("pod_owner_identity_mismatch")
            if pod.status.phase in ("Succeeded", "Failed"):
                terminal.append({"podUid": pod.metadata.uid, "name": pod.metadata.name, "phase": pod.status.phase})
                continue
            conditions = pod.status.conditions or []
            containers = pod.status.container_statuses or []
            reasons = [c.reason for c in conditions if c.status != "True" and c.reason]
            for c in containers:
                state = c.state
                waiting = getattr(state, "waiting", None)
                terminated = getattr(state, "terminated", None)
                if waiting and waiting.reason:
                    reasons.append(waiting.reason)
                if terminated and terminated.reason:
                    reasons.append(terminated.reason)
            instances.append({
                "podUid": pod.metadata.uid, "name": pod.metadata.name, "namespace": ref.namespace,
                "node": pod.spec.node_name, "podIp": pod.status.pod_ip,
                "phase": pod.status.phase, "terminating": bool(pod.metadata.deletion_timestamp),
                "podReady": any(c.type == "Ready" and c.status == "True" for c in conditions),
                "restartCount": sum(c.restart_count or 0 for c in containers),
                "resources": [{"container": c.name,
                               "requests": (c.resources.requests or {}) if c.resources else {},
                               "limits": (c.resources.limits or {}) if c.resources else {}}
                              for c in pod.spec.containers],
                "podReasons": reasons,
            })
        return {"desiredReplicas": deployment.spec.replicas, "workloadExists": True,
                "workloadUid": deployment.metadata.uid,
                "plannedNodeSelector": deployment.spec.template.spec.node_selector or {},
                "instances": instances, "terminalPods": terminal}


class RuntimeStatusProbe:
    async def __call__(self, pod, definition):
        address = ipaddress.ip_address(pod["podIp"])  # Only an observed Pod IP; no registry URL/proxy.
        host = f"[{address}]" if address.version == 6 else str(address)
        async with httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False) as client:
            response = await client.get(f"http://{host}:{definition.spec.runtimeRef.port}/status")
            response.raise_for_status()
            return response.json()


def validate_status(status, pod, definition):
    if status["virtualDeviceId"] != definition.metadata.name or status["podUid"] != pod["podUid"]:
        raise ValueError("runtime_identity_mismatch")
    if not fresh(status.get("observedAt")):
        raise ValueError("runtime_observation_stale")
    if not isinstance(status.get("bootId"), str) or not status["bootId"]:
        raise ValueError("runtime_boot_identity_missing")
    if any(type(status.get(k)) is not bool for k in ("modelReady", "draining")):
        raise ValueError("invalid_runtime_readiness")
    if any(type(status.get(k)) is not int or status[k] < 0 for k in ("succeeded", "failed", "inFlight")):
        raise ValueError("invalid_runtime_counters")
    expected = definition.spec.model
    if status["modelReady"] and any(status["model"].get(k) != v for k, v in expected.items()):
        raise ValueError("runtime_model_identity_mismatch")
    evidence = status.get("lastSuccess")
    if evidence and (
        evidence.get("virtualDeviceId") != definition.metadata.name
        or evidence.get("podUid") != pod["podUid"] or evidence.get("bootId") != status["bootId"]
        or evidence.get("model") != status["model"] or not evidence.get("requestId")
        or not evidence.get("clientId") or "result" not in evidence or status["succeeded"] < 1
    ):
        raise ValueError("invalid_request_evidence")
    return status


class VirtualDeviceObserver:
    def __init__(self, reader, probe=None):
        self.reader = reader
        self.probe = probe or RuntimeStatusProbe()
        self.lock = asyncio.Lock()
        self.cached = None
        self.cached_at = 0.0

    async def snapshot(self, registry):
        async with self.lock:
            # Coalesce dashboard clients without serving an expired or failed observation.
            if self.cached is not None and time.monotonic() - self.cached_at < 2:
                return self.cached
            nodes, node_error = None, None
            try:
                nodes = await self.reader.nodes()
            except Exception as exc:
                node_error = f"node_query_failed: {type(exc).__name__}"
            resources = [await self.observe_one(item, registry.connections) for item in registry.resources]
            complete = all(item["observedInstances"] is not None for item in resources)
            result = {
                "observedAt": utcnow(), "maxAgeSeconds": MAX_AGE_SECONDS, "mode": "read_only",
                "scope": "container_function_prototype", "nodes": nodes, "nodeError": node_error,
                "summary": {"physicalNodes": len(nodes) if nodes is not None else None,
                            "definitions": len(resources),
                            "observedInstances": sum(item["observedInstances"] for item in resources) if complete else None},
                "resources": resources,
            }
            self.cached, self.cached_at = result, time.monotonic()
            return result

    async def observe_one(self, definition, connections):
        bindings = [c.model_dump() for c in connections if definition.metadata.name in c.spec.bindings.values()]
        row = {"id": definition.metadata.name, "definition": definition.model_dump(),
               "connections": bindings, "executionState": "unknown", "connectionState": "unknown",
               "observedInstances": None, "instances": [], "observationError": None,
               "observedAt": None, "attemptedAt": utcnow()}
        try:
            workload = await self.reader.workload(definition)
        except Exception as exc:
            row["observationError"] = f"workload_query_failed: {type(exc).__name__}: {str(exc)[:160]}"
            return row
        row.update(workload)
        row["observedAt"] = utcnow()
        row["observedInstances"] = len(row["instances"])
        row["executionState"] = "no_instance" if not row["instances"] else "observed"
        row["connectionState"] = "configured_unverified" if bindings else "not_configured"
        clients = {c["spec"]["targetDevice"]["name"] for c in bindings}
        for pod in row["instances"]:
            pod.update({"runtime": None, "modelReady": None, "apiError": None,
                        "observedAt": utcnow(), "apiObservedAt": None,
                        "usage": {"scope": "main_process", "cpuCores": None, "memoryBytes": None}})
            try:
                status = validate_status(await self.probe(pod, definition), pod, definition)
                pod["runtime"] = status
                pod["apiObservedAt"] = utcnow()
                pod["modelReady"] = status["modelReady"]
                usage = status.get("usage") or {}
                if fresh(usage.get("observedAt")):
                    pod["usage"] = dict(usage)
                    if not fresh(usage.get("cpuObservedAt")):
                        pod["usage"]["cpuCores"] = None
                evidence = status.get("lastSuccess")
                if evidence and evidence.get("clientId") in clients:
                    row["connectionState"] = "request_observed" if fresh(evidence.get("completedAt")) else "historical_request"
                pod["executionState"] = (
                    "terminating" if pod["terminating"] or status["draining"] else
                    "not_ready" if not pod["podReady"] or not status["modelReady"] or status.get("error") else
                    "processing" if status["inFlight"] > 0 else "ready")
            except Exception as exc:
                pod["apiError"] = f"runtime_query_failed: {type(exc).__name__}: {str(exc)[:160]}"
                pod["executionState"] = "unknown"
                row["connectionState"] = "unknown"
        if row["instances"]:
            states = [pod["executionState"] for pod in row["instances"]]
            row["executionState"] = next((s for s in ("unknown", "terminating", "not_ready", "processing") if s in states), "ready")
        return row


def create_virtual_device_router(kube):
    router = APIRouter()
    observer = VirtualDeviceObserver(KubernetesVirtualDeviceReader(kube))

    @router.get("/api/virtual-devices")
    async def virtual_devices():
        try:
            registry = VirtualDeviceRegistry.load()
        except Exception as exc:
            return JSONResponse(status_code=503, content={"error": f"registry_unavailable: {type(exc).__name__}",
                                                        "observedAt": utcnow()})
        return JSONResponse(content=await observer.snapshot(registry), headers={"Cache-Control": "no-store"})

    return router
