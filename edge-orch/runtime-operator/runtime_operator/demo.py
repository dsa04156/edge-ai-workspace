"""Opt-in bounded demo traffic, owned by the same durable runtime controller."""
import asyncio
import hashlib
import json
import math
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from .contract import ServiceSpec


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    mode: Literal["single", "round-trip", "load"]


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")


def signature(spec):
    value = {"demo": spec.demo.model_dump() if spec.demo else None, "ioContract": spec.ioContract,
             "inference": spec.inference.model_dump() if spec.inference else None}
    if spec.policy.stages:
        value["stages"] = [stage.model_dump() for stage in spec.policy.stages]
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def public(run):
    # Full child request receipts remain in the existing gateway journal.
    return {k: v for k, v in run.items() if k not in {"contract", "signature", "requests"}} | {"recentRequests": run["requests"][-5:]}


class DemoRunner:
    def __init__(self, app):
        self.app = app
        self.tasks = {}
        self.runs = {}

    @property
    def controller(self):
        return self.app.state.controller

    def definition(self, name, uid):
        c = self.controller
        if c.stopping or not c.snapshot or c.clock() - c.last_snapshot >= 15:
            raise HTTPException(503, "runtime_snapshot_unavailable")
        matches = [r for r in c.snapshot["services"] if r["metadata"]["name"] == name and r["metadata"]["uid"] == uid
                   and not r["metadata"].get("deletionTimestamp")]
        if len(matches) != 1:
            raise HTTPException(409, "service_identity_changed")
        spec = ServiceSpec.model_validate(matches[0]["spec"])
        if spec.suspended or not spec.demo:
            raise HTTPException(403, "demo_not_enabled")
        return spec

    def start(self, name, run_id, body):
        c = self.controller
        existing = c.journal.demo_get(body.serviceUid, run_id)
        if existing:
            if existing["name"] != name or existing["mode"] != body.mode:
                raise HTTPException(409, "run_id_conflict")
            return public(existing)
        spec = self.definition(name, body.serviceUid)
        if body.mode == "load" and (not spec.inference or not spec.policy.approvalRequired):
            raise HTTPException(403, "load_requires_approval_enabled_AI_service")
        state = c.states.get(body.serviceUid, {})
        if not state.get("serving") or not state.get("active") or state.get("target") or state.get("retiring"):
            raise HTTPException(409, "service_not_stable_for_demo")
        if c.journal.demo_list(body.serviceUid, active=True) or len(c.journal.demo_list(active=True)) >= 2:
            raise HTTPException(409, "demo_already_running")
        recent = c.journal.demo_list(body.serviceUid, limit=1)
        if recent and c.clock() - recent[0].get("finishedAt", recent[0]["createdAt"]) < 10:
            raise HTTPException(429, "demo_cooldown_10_seconds")
        active = state["active"]
        run = {"id": run_id, "uid": body.serviceUid, "name": name, "mode": body.mode,
               "phase": "Running", "stage": "single" if body.mode == "single" else "pressure",
               "createdAt": c.clock(), "label": spec.demo.label, "contract": spec.demo.model_dump(),
               "signature": signature(spec), "stopRequested": False, "sent": 0, "succeeded": 0,
               "failed": 0, "unknown": 0, "requests": [], "routeHistory": [], "lastResult": None,
               "startNode": active["node"], "startRole": active["role"], "leftStartRole": False,
               "baselineVariant": spec.policy.stages[0].variant if spec.policy.stages else None, "leftBaseline": False,
               "returned": False, "retiring": 0}
        c.journal.demo_save(run)  # Durable identity before the first request task exists.
        key = (body.serviceUid, run_id)
        self.runs[key] = run
        self.tasks[key] = asyncio.create_task(self.execute(run))
        return public(run)

    def observe(self, run):
        c = self.controller
        state = c.states.get(run["uid"], {})
        active = state.get("active")
        if c.clock() - c.last_snapshot >= 15 or not state.get("serving") or not active:
            return
        history = run["routeHistory"]
        if not history or history[-1]["node"] != active["node"]:
            history.append({"at": c.clock(), "node": active["node"], "role": active["role"],
                            "reason": state.get("lastTransition", {}).get("reason", state.get("reason"))})
        run["currentNode"] = active["node"]
        run["retiring"] = len(state.get("retiring", []))
        run["leftStartRole"] |= active["role"] != run["startRole"]
        if run.get("baselineVariant"):
            run["leftBaseline"] |= active["variant"] != run["baselineVariant"]
            run["returned"] = bool(run["leftBaseline"] and active["variant"] == run["baselineVariant"]
                                   and not state.get("target") and not state.get("retiring"))
            return
        run["returned"] = bool(run["leftStartRole"] and active["role"] == run["startRole"]
                               and not state.get("target") and not state.get("retiring"))

    async def execute(self, run):
        c = self.controller
        config = run["contract"]
        key = (run["uid"], run["id"])
        prefix = "demo-" + hashlib.sha256((run["uid"] + ":" + run["id"]).encode()).hexdigest()[:24]
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://runtime") as client:
                async def invoke():
                    if run["stopRequested"] or run["sent"] >= config["maxRequests"]:
                        return False
                    spec = self.definition(run["name"], run["uid"])
                    if signature(spec) != run["signature"]:
                        raise HTTPException(409, "demo_contract_changed")
                    request_id = prefix + "-" + str(run["sent"])
                    run["sent"] += 1
                    item = {"id": request_id, "state": "pending"}
                    run["requests"].append(item)
                    c.journal.demo_save(run)
                    started = time.monotonic()
                    try:
                        response = await client.post("/services/" + run["name"] + "/invoke",
                            json=config["payload"], headers={"X-Request-ID": request_id, "X-Runtime-Service-Uid": run["uid"]})
                        result = response.json()
                        outcome = response.headers.get("X-Request-State", "rejected")
                        good = 200 <= response.status_code < 300 and outcome == "completed"
                        item.update(state=outcome, status=response.status_code, target=response.headers.get("X-Runtime-Target"))
                        run["succeeded" if good else "unknown" if outcome == "unknown" else "failed"] += 1
                        run["lastResult"] = json.dumps(result, ensure_ascii=False)[:12000]
                    except (httpx.HTTPError, ValueError, TimeoutError):
                        item["state"] = "unknown"
                        run["unknown"] += 1
                    finally:
                        item["elapsedMilliseconds"] = (time.monotonic() - started) * 1000
                        self.observe(run)
                        c.journal.demo_save(run)
                    return True

                self.observe(run)
                if run["mode"] == "single":
                    await invoke()
                else:
                    if run["mode"] == "load":
                        # Low-rate baseline lets an already remote service return
                        # by its normal policy before applying pressure.
                        run["stage"] = "baseline"
                        until = time.monotonic() + config["recoverySeconds"]
                        while time.monotonic() < until and not run["stopRequested"]:
                            state = c.states.get(run["uid"], {})
                            spec = self.definition(run["name"], run["uid"])
                            if ((state.get("active", {}).get("variant") == spec.policy.stages[0].variant if spec.policy.stages else
                                 state.get("active", {}).get("role") == spec.policy.preferredRole)
                                    and not state.get("target") and not state.get("retiring")):
                                break
                            if not await invoke():
                                break
                            await asyncio.sleep(config["recoveryIntervalSeconds"])
                        run["stage"] = "pressure"
                    until = time.monotonic() + config["pressureSeconds"]
                    async def pressure():
                        while time.monotonic() < until:
                            if not await invoke():
                                break
                    # Wait every child, including failure paths, before closing the run.
                    results = await asyncio.gather(*(pressure() for _ in range(config["concurrency"])), return_exceptions=True)
                    for result in results:
                        if isinstance(result, BaseException):
                            raise result
                    run["stage"] = "recovery"
                    until = time.monotonic() + config["recoverySeconds"]
                    while time.monotonic() < until and not run["stopRequested"]:
                        if not await invoke():
                            break
                        if run["returned"]:
                            break
                        await asyncio.sleep(config["recoveryIntervalSeconds"])
                self.observe(run)
                run["phase"] = ("Stopped" if run["stopRequested"] else "Completed"
                    if run["sent"] == run["succeeded"] and (run["mode"] in {"single", "load"} or run["returned"])
                    else "Incomplete")
                run["reason"] = ("operator_stopped_demo" if run["stopRequested"] else "requests_and_route_verified"
                    if run["phase"] == "Completed" and run["mode"] != "load"
                    else "bounded_load_completed" if run["phase"] == "Completed" else "request_or_round_trip_gate_not_met")
        except asyncio.CancelledError:
            run.update(phase="Interrupted", reason="controller_shutdown_no_automatic_replay")
        except Exception as exc:
            run.update(phase="Interrupted", reason=exc.detail if isinstance(exc, HTTPException) else "demo_execution_error")
        finally:
            for item in run["requests"]:
                if item["state"] == "pending":
                    item["state"] = "unknown"
                    run["unknown"] += 1
            run["finishedAt"] = c.clock()
            c.journal.demo_save(run)
            self.tasks.pop(key, None)
            self.runs.pop(key, None)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Tasks cancelled before their first scheduling never enter execute's finally.
        for run in self.runs.values():
            run.update(phase="Interrupted", reason="controller_shutdown_no_automatic_replay", finishedAt=self.controller.clock())
            self.controller.journal.demo_save(run)
        self.runs.clear()
        self.tasks.clear()


def router(app):
    routes = APIRouter(prefix="/demos")
    runner = DemoRunner(app)
    app.state.demo_runner = runner

    @routes.get("")
    async def catalog():
        c = runner.controller
        items = []
        for resource in (c.snapshot or {}).get("services", []):
            name, uid = resource["metadata"]["name"], resource["metadata"]["uid"]
            try:
                spec = runner.definition(name, uid)
            except HTTPException:
                continue
            state = c.states.get(uid, {})
            latest = c.journal.demo_list(uid, limit=1)
            cooldown = max(0, math.ceil(10 - (c.clock() - latest[0]["finishedAt"]))) if latest and latest[0].get("finishedAt") else 0
            items.append({"name": name, "uid": uid, "label": spec.demo.label,
                          "inputPreview": json.dumps(spec.demo.payload, ensure_ascii=False),
                          "maxRequests": spec.demo.maxRequests, "pressureSeconds": spec.demo.pressureSeconds,
                          "recoverySeconds": spec.demo.recoverySeconds, "concurrency": spec.demo.concurrency,
                          "retryAfterSeconds": cooldown,
                          "available": bool(state.get("serving") and not state.get("target") and not state.get("retiring")
                                            and not cooldown and not c.journal.demo_list(uid, active=True))})
        return {"items": items, "runs": [public(r) for r in c.journal.demo_list()], "observedAt": c.clock(),
                "observation_error": "runtime_snapshot_unavailable" if c.clock() - c.last_snapshot >= 15 else None}

    @routes.get("/{name}/runs/{run_id}")
    async def get_run(name: str, run_id: str, serviceUid: str):
        value = runner.controller.journal.demo_get(serviceUid, run_id)
        if value is None or value["name"] != name:
            raise HTTPException(404, "demo_run_not_found")
        return public(value)

    @routes.post("/{name}/runs/{run_id}", status_code=202)
    async def start(name: str, run_id: str, body: StartRequest):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", run_id):
            raise HTTPException(400, "invalid_demo_run_id")
        return runner.start(name, run_id, body)

    @routes.post("/{name}/runs/{run_id}/stop")
    async def stop(name: str, run_id: str, body: StopRequest):
        value = runner.controller.journal.demo_get(body.serviceUid, run_id)
        if value is None or value["name"] != name:
            raise HTTPException(404, "demo_run_not_found")
        run = runner.runs.get((body.serviceUid, run_id))
        if run:
            run.update(stopRequested=True, phase="Stopping")
            runner.controller.journal.demo_save(run)
        return public(run or value)

    return routes
