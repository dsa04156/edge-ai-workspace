"""Reconcile arbitrary HTTP services; route changes are request-boundary changes."""
import asyncio
import copy
import time

import httpx

from .contract import ServiceSpec, revision
from .kube import FINALIZER, owned
from .placement import candidates
from . import resident
from .contract import ResidentRuntime


class Controller:
    def __init__(self, kube, journal, transport=None, clock=time.time):
        self.kube, self.journal, self.clock = kube, journal, clock
        self.transport = transport or httpx.AsyncClient(timeout=3, trust_env=False)
        self.states = journal.states()
        self.inflight = {}
        self.pending = {}
        self.pending_ids = {}
        self.last_snapshot = 0
        self.last_error = None
        self.stopping = False
        self.snapshot = None
        self.lifecycle_tasks = {}
        # Never serve a persisted route until the current cluster and service are revalidated.
        for state in self.states.values():
            state["serving"] = False
            state["recovering"] = True

    def save(self, uid, state, event=None):
        self.journal.save(uid, state, event)
        self.states[uid] = copy.deepcopy(state)

    def endpoint(self, target):
        if target.get("resident"):
            return resident.endpoint(target)
        return f"http://{target['name']}.{self.kube.namespace}.svc.cluster.local:{target['spec']['port']}"

    def running_count(self, target):
        if not target.get("resident"):
            return self.inflight.get(target["name"], 0)
        names = {target["name"]}
        for state in self.states.values():
            for item in [state.get("active"), state.get("target"), *state.get("retiring", [])]:
                if item and item.get("resident") and resident.identity(item) == resident.identity(target):
                    names.add(item["name"])
        return sum(self.inflight.get(name, 0) for name in names)

    async def probe(self, target):
        if target.get("resident"):
            return await resident.probe(self.transport, target)
        try:
            response = await self.transport.get(self.endpoint(target) + target["spec"]["readyPath"], timeout=2)
            response.raise_for_status()
            body = response.json()
            if (body.get("ioContract") != target["spec"]["ioContract"] or body.get("ready") is not True
                    or type(body.get("inFlight")) is not int or body["inFlight"] < 0):
                return None
            return body
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    def pod_ready(self, target, uid, snapshot):
        nodes = {n["metadata"]["name"]: n for n in snapshot["nodes"]}
        node = nodes.get(target["node"], {})
        if not any(c["type"] == "Ready" and c["status"] == "True" for c in node.get("status", {}).get("conditions", [])):
            return False
        if target.get("resident"):
            return resident.verify_binding(ResidentRuntime.model_validate(target["resident"]), target["image"],
                                           target["node"], snapshot, target["spec"]["port"]) is None
        deployments = [d for d in snapshot["deployments"] if d["metadata"]["name"] == target["name"] and owned(d, uid)]
        if not deployments or deployments[0]["spec"].get("replicas") != 1:
            return False
        for p in snapshot["pods"]:
            meta, status = p["metadata"], p.get("status", {})
            if (meta.get("namespace") != self.kube.namespace or meta.get("deletionTimestamp")
                    or meta.get("labels", {}).get("platform.jinuk.io/revision") != target["name"]
                    or meta.get("labels", {}).get("platform.jinuk.io/service-uid") != uid
                    or p.get("spec", {}).get("nodeName") != target["node"]):
                continue
            if not any(c["type"] == "Ready" and c["status"] == "True" for c in status.get("conditions", [])):
                continue
            containers = p["spec"].get("containers", [])
            if len(containers) == 1 and containers[0].get("image") == target["image"]:
                return True
        return False

    def target(self, resource, spec, candidate):
        uid = resource["metadata"]["uid"]
        name = "rt-" + uid.replace("-", "")[:12] + "-" + revision(spec, candidate.variant, candidate.node)
        bound_pods = resident.matching_pods(candidate.variant.resident, self.snapshot["pods"]) if candidate.variant.resident and self.snapshot else []
        return {"name": name, "node": candidate.node, "role": candidate.role,
                "variant": candidate.variant.name, "image": candidate.variant.image,
                "resident": candidate.variant.resident.model_dump() if candidate.variant.resident else None,
                "qualifiedRps": candidate.variant.qualifiedRps,
                "runtimePodUid": bound_pods[0]["metadata"]["uid"] if len(bound_pods) == 1 else None,
                "capacity": candidate.variant.maxInFlight, "spec": spec.model_dump(), "created": self.clock()}

    def lifecycle(self, target, action):
        key = (target["name"], action)
        task = self.lifecycle_tasks.get(key)
        if task is not None and task.done():
            self.lifecycle_tasks.pop(key)
            task.result()  # Record failures through the normal reconcile error path.
            return
        if task is None:
            self.lifecycle_tasks[key] = asyncio.create_task(resident.lifecycle(self.transport, target, action))

    async def drain(self, uid, state, snapshot):
        remaining = []
        for target in state.get("retiring", []):
            name = target["name"]
            if self.inflight.get(name, 0):
                remaining.append(target)
                continue
            if target.get("resident"):
                active = state.get("active")
                if active and active.get("resident") and resident.identity(active) == resident.identity(target):
                    # Contract revision on the same runtime: never unload the new active route.
                    continue
                if not self.pod_ready(target, uid, snapshot):
                    remaining.append(target)
                    continue
                health = await self.probe(target)
                target["observation"] = {"at": self.clock(), "health": health}
                activating = self.lifecycle_tasks.get((name, "activate"))
                if activating is not None and not activating.done():
                    remaining.append(target)
                    continue
                if health and health["released"] and health["inFlight"] == 0:
                    target["releasedModelVramMiB"] = health["modelVramMiB"]
                    state["lastRelease"] = {"node": target["node"], "at": self.clock(),
                                            "modelVramMiB": health["modelVramMiB"], "reservationRetained": True}
                    self.save(uid, state, "resident_model_released")
                    continue
                if health and health["inFlight"] == 0:
                    self.lifecycle(target, "release")
                remaining.append(target)
                continue
            # No Pod at all means no remaining process. Terminating Pods still count.
            pods = [p for p in snapshot["pods"] if p["metadata"].get("namespace") == self.kube.namespace
                    and p["metadata"].get("labels", {}).get("platform.jinuk.io/revision") == name
                    and p.get("status", {}).get("phase") not in ("Succeeded", "Failed")]
            if not pods:
                await asyncio.to_thread(self.kube.scale, name, uid, 0)
                continue
            if target.get("scaledDown") or not target.get("everRouted"):
                target["scaledDown"] = True
                self.save(uid, state, "scale_down_intent")
                await asyncio.to_thread(self.kube.scale, name, uid, 0)
                remaining.append(target)
                continue
            health = await self.probe(target)
            if health and health["inFlight"] == 0:
                # Persist intent before side effect; crashes retry the same scale operation.
                target["scaledDown"] = True
                remaining.append(target)
                self.save(uid, state, "drain_complete")
                await asyncio.to_thread(self.kube.scale, name, uid, 0)
            else:
                remaining.append(target)
        state["retiring"] = remaining

    async def reconcile(self, resource, snapshot):
        uid, name = resource["metadata"]["uid"], resource["metadata"]["name"]
        spec = ServiceSpec.model_validate(resource["spec"])
        state = {"name": name, "uid": uid, "active": None, "target": None, "retiring": [],
                 "switchedAt": 0, "highSince": None, "lowSince": None,
                 **copy.deepcopy(self.states.get(uid, {}))}
        state["observedGeneration"] = resource["metadata"].get("generation", 1)
        if FINALIZER not in resource["metadata"].get("finalizers", []):
            if resource["metadata"].get("deletionTimestamp"):
                return
            await asyncio.to_thread(self.kube.finalizer, resource)
            return
        state["serving"] = False
        state["phase"] = "Reconciling"
        if spec.suspended or resource["metadata"].get("deletionTimestamp"):
            had_admission = bool(state.get("active") or state.get("target"))
            for key in ("active", "target"):
                if state.get(key):
                    state["retiring"].append(state.pop(key))
                    state[key] = None
            state["phase"] = "Draining"
            self.save(uid, state, "admission_stopped" if had_admission else None)
            await self.drain(uid, state, snapshot)
            if not state["retiring"]:
                state["phase"] = "Suspended"
                if resource["metadata"].get("deletionTimestamp"):
                    for d in snapshot["deployments"]:
                        if owned(d, uid):
                            await asyncio.to_thread(self.kube.remove, d["metadata"]["name"], uid)
                    await asyncio.to_thread(self.kube.finalizer, resource, False)
                    state["phase"] = "Deleted"
            self.save(uid, state)
            return

        credits = {}
        for node in snapshot["nodes"]:
            for v in spec.variants:
                t = self.target(resource, spec, type("Choice", (), {"node": node["metadata"]["name"], "role": "", "variant": v})())
                if any(d["metadata"]["name"] == t["name"] and owned(d, uid) and d["spec"].get("replicas") == 1
                       for d in snapshot["deployments"]):
                    credits[(t["node"], v.name)] = {"name": t["name"], "uid": uid, "namespace": self.kube.namespace}
        eligible, rejected = candidates(spec, snapshot["nodes"], snapshot["pods"], snapshot["runtimeClasses"], credits, snapshot)
        failed = state.setdefault("failedCandidates", {})
        for candidate in list(eligible):
            candidate_name = self.target(resource, spec, candidate)["name"]
            retiring = any(t["name"] == candidate_name for t in state.get("retiring", []))
            if retiring or failed.get(candidate_name, 0) > self.clock():
                eligible.remove(candidate)
                rejected.append({"node": candidate.node, "variant": candidate.variant.name,
                                 "reasons": ["candidate_still_draining" if retiring else "prepare_failure_backoff"]})
        state["excludedCandidates"] = rejected
        state["eligibleCandidates"] = [{"node": c.node, "variant": c.variant.name, "role": c.role} for c in eligible]
        active = state.get("active")
        health = await self.probe(active) if active and self.pod_ready(active, uid, snapshot) else None
        if active:
            active["observation"] = {"at": self.clock(), "health": health}
        healthy = bool(health and health["ready"])
        if healthy and state.get("recovering") and health["inFlight"]:
            # Process-local counters were lost. Do not admit extra work on top
            # of requests still running from the previous gateway process.
            state.update(serving=False, phase="Recovering", reason="previous_process_requests_still_running")
            self.save(uid, state)
            return
        if healthy:
            state["recovering"] = False
        state["serving"] = healthy
        state["checkedAt"] = self.clock()
        current = next((c for c in eligible if active and self.target(resource, spec, c)["name"] == active["name"]), None)
        load = (self.inflight.get(active["name"], 0) if active else 0) + self.pending.get(uid, 0)
        utilization = load / active["capacity"] if active else 0
        state["load"] = {"inFlightAndPending": load, "utilization": utilization}
        now = self.clock()
        state["highSince"] = (state.get("highSince") or now) if utilization >= spec.policy.highWatermark else None
        state["lowSince"] = (state.get("lowSince") or now) if utilization <= spec.policy.lowWatermark else None
        choice = None
        reason = "healthy_current_placement"
        if not healthy or not current:
            alternatives = [c for c in eligible if not active or self.target(resource, spec, c)["name"] != active["name"]]
            choice = alternatives[0] if alternatives else None
            reason = "initial_or_unhealthy_or_policy_changed"
        elif not state.get("target") and now - state["switchedAt"] >= spec.policy.cooldownSeconds:
            if spec.policy.mode == "automatic" and state["highSince"] is not None and now - state["highSince"] >= spec.policy.pressureSeconds:
                larger = [c for c in eligible if
                          (c.variant.qualifiedRps is not None and active.get("qualifiedRps") is not None
                           and c.variant.qualifiedRps > active["qualifiedRps"])
                          or (c.variant.qualifiedRps is None and active.get("qualifiedRps") is None
                              and c.variant.maxInFlight > active["capacity"])]
                choice = min(larger, key=lambda c: (c.variant.qualifiedRps or c.variant.maxInFlight, c.node)) if larger else None
                reason = "sustained_pressure" if choice else "pressure_no_qualified_capacity"
            elif state["lowSince"] is not None and now - state["lowSince"] >= spec.policy.returnSeconds:
                small = [c for c in eligible if c.role == spec.policy.preferredRole
                         and (c.role != active["role"] or c.variant.maxInFlight < active["capacity"])
                         and load <= c.variant.maxInFlight * spec.policy.highWatermark]
                choice = small[0] if small else None
                reason = "sustained_low_load_return" if choice else "healthy_current_placement"
        if choice and active and self.target(resource, spec, choice)["name"] == active["name"]:
            choice = None
        if not choice and not state.get("target") and active and active.get("resident") and health and not healthy:
            self.lifecycle(active, "activate")
        # Do not reuse a revision until its previous drain and Pod termination finished.
        if choice and any(t["name"] == self.target(resource, spec, choice)["name"] for t in state["retiring"]):
            choice = None
            reason = "candidate_still_draining"
        if choice and not state.get("target") and now >= state.get("retryAfter", 0):
            state["target"] = self.target(resource, spec, choice)
            state["target"]["triggerReason"] = reason
            self.save(uid, state, "prepare")
        target = state.get("target")
        if target:
            candidate = next((c for c in eligible if self.target(resource, spec, c)["name"] == target["name"]), None)
            if candidate is None or now - target["created"] > spec.policy.prepareTimeoutSeconds:
                state["failedCandidates"][target["name"]] = now + max(60, spec.policy.prepareTimeoutSeconds)
                state["retiring"].append(target)
                state["target"] = None
                state["retryAfter"] = now + spec.policy.cooldownSeconds
                reason = "candidate_invalid_or_prepare_timeout"
            else:
                if not target.get("resident"):
                    await asyncio.to_thread(self.kube.ensure, resource, spec, candidate, target["name"])
                target_health = await self.probe(target) if self.pod_ready(target, uid, snapshot) else None
                target["observation"] = {"at": self.clock(), "health": target_health}
                if target.get("resident") and target_health and not target_health["ready"]:
                    self.lifecycle(target, "activate")
                if target_health and target_health["ready"]:
                    state["lastTransition"] = {"fromNode": active["node"] if active else None,
                                               "toNode": target["node"], "at": self.clock(),
                                               "reason": target.get("triggerReason", reason)}
                    if active:
                        state["retiring"].append(active)
                    target["everRouted"] = True
                    state.update(active=target, target=None, serving=True, recovering=False,
                                 switchedAt=now, highSince=None, lowSince=None)
                    self.save(uid, state, "route_switched")
                    reason = "target_ready_route_switched"
                else:
                    reason = "waiting_for_pod_and_application_ready"
        # Refresh in-memory routing before yielding to network drain probes.
        state["reason"] = reason
        state["phase"] = "Preparing" if state.get("target") else "Serving" if state["serving"] else "Blocked"
        self.save(uid, state)
        await self.drain(uid, state, snapshot)
        self.save(uid, state)

    async def tick(self):
        try:
            snapshot = await asyncio.to_thread(self.kube.snapshot)
        except Exception as exc:
            self.last_error = "snapshot_unavailable:" + type(exc).__name__
            return
        self.last_snapshot = self.clock()
        self.snapshot = snapshot
        self.last_error = None
        present = {r["metadata"]["uid"] for r in snapshot["services"]}
        for uid, state in list(self.states.items()):
            if uid not in present and state.get("phase") not in ("Missing", "Deleted"):
                state = copy.deepcopy(state)
                state.update(serving=False, phase="Missing")
                self.save(uid, state, "resource_missing")
        claims = {}
        for resource in snapshot["services"]:
            try:
                declared = ServiceSpec.model_validate(resource["spec"])
                for v in declared.variants:
                    if v.resident:
                        for p in resident.matching_pods(v.resident, snapshot["pods"]):
                            claims.setdefault(p["metadata"]["uid"], []).append(resource["metadata"]["uid"])
            except (ValueError, KeyError):
                continue
        conflicts = set().union(*(set(owners) for owners in claims.values() if len(owners) > 1)) if claims else set()
        for resource in snapshot["services"]:
            uid = resource["metadata"]["uid"]
            try:
                if uid in conflicts:
                    raise ValueError("resident_runtime_claimed_by_multiple_services")
                await self.reconcile(resource, snapshot)
            except Exception as exc:
                state = copy.deepcopy(self.states.get(uid, {"uid": uid, "name": resource["metadata"]["name"]}))
                state.update(serving=False, phase="Blocked", reason="reconcile_error:" + type(exc).__name__)
                self.save(uid, state)
            state = self.states.get(uid)
            if state:
                status = {k: state[k] for k in ("phase", "reason", "observedGeneration", "eligibleCandidates", "excludedCandidates", "load") if k in state}
                status.update(active={k: state["active"][k] for k in ("name", "node", "variant")} if state.get("active") else {},
                              retiring=[t["name"] for t in state.get("retiring", [])])
                try:
                    await asyncio.to_thread(self.kube.status, resource, status)
                except Exception:
                    # A status conflict cannot roll back an already durable route change.
                    self.last_error = "status_write_failed"

    async def run(self):
        while not self.stopping:
            await self.tick()
            await asyncio.sleep(2)
