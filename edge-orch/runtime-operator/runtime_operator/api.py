"""Cluster-internal gateway; provisioning authorization is Kubernetes RBAC."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

from .controller import Controller
from .journal import Journal
from .kube import Kube
from . import resident


def create_app(controller=None):
    @asynccontextmanager
    async def lifespan(app):
        if app.state.controller is None:
            app.state.controller = Controller(Kube(os.environ.get("RUNTIME_NAMESPACE", "platform-runtime")),
                Journal(os.environ.get("JOURNAL_PATH", "/data/runtime.sqlite3")))
        c = app.state.controller
        task = asyncio.create_task(c.run())
        try:
            yield
        finally:
            c.stopping = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for action in c.lifecycle_tasks.values():
                action.cancel()
            await asyncio.gather(*c.lifecycle_tasks.values(), return_exceptions=True)
            await c.transport.aclose()
            c.journal.close()

    app = FastAPI(title="Common Service Runtime", lifespan=lifespan)
    app.state.controller = controller

    @app.get("/health")
    async def health():
        c = app.state.controller
        ok = c is not None and c.clock() - c.last_snapshot < 30 and not c.stopping
        return JSONResponse({"ready": ok}, status_code=200 if ok else 503)

    @app.get("/services")
    async def services():
        c = app.state.controller
        return {"services": list(c.states.values()), "lastError": c.last_error,
                "snapshotAgeSeconds": c.clock() - c.last_snapshot}

    @app.get("/services/{name}/requests/{request_id}")
    async def request_status(name: str, request_id: str):
        c = app.state.controller
        # Include suspended/deleted UIDs for durable outcome inspection.
        matches = [(s, c.journal.request(uid, request_id)) for uid, s in c.states.items() if s["name"] == name]
        matches = [(s, r) for s, r in matches if r]
        if len(matches) != 1:
            return JSONResponse({"reason": "request_not_found_or_ambiguous"}, status_code=404 if not matches else 409)
        state, record = matches[0]
        return {"serviceUid": state["uid"], "requestId": request_id, "target": record["target"],
                "state": record["state"], "status": record["status"],
                "result": json.loads(record["body"]) if record["body"] else None}

    @app.post("/services/{name}/invoke")
    async def invoke(name: str, request: Request):
        c = app.state.controller
        request_id = request.headers.get("X-Request-ID", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request_id):
            return JSONResponse({"reason": "valid_X_Request_ID_required"}, status_code=400)
        matching = [s for s in c.states.values() if s["name"] == name and s.get("phase") not in ("Deleted", "Missing")]
        if len(matching) != 1:
            return JSONResponse({"reason": "service_not_registered"}, status_code=404)
        state = matching[0]
        uid = state["uid"]
        if not state.get("active"):
            return JSONResponse({"reason": "no_ready_target", "accepted": False}, status_code=503)
        spec = state["active"]["spec"]
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > spec["maxBodyBytes"]:
                return JSONResponse({"reason": "body_too_large"}, status_code=413)
        try:
            body = json.loads(data)
            if not isinstance(body, dict):
                raise ValueError()
            canonical = json.dumps(body, sort_keys=True, allow_nan=False, separators=(",", ":"))
            if state["active"].get("resident"):
                resident.request_body(spec, body, request_id)
        except (ValueError, TypeError):
            return JSONResponse({"reason": "JSON_object_required"}, status_code=400)
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()

        def replay(existing):
            if existing["fingerprint"] != fingerprint:
                return JSONResponse({"reason": "request_id_payload_conflict"}, status_code=409)
            if existing["state"] == "dispatched":
                return JSONResponse({"reason": "request_in_progress"}, status_code=409)
            return JSONResponse(json.loads(existing["body"]), status_code=existing["status"],
                                headers={"X-Request-State": existing["state"], "X-Runtime-Target": existing["target"]})

        existing = c.journal.request(uid, request_id)
        if existing:
            return replay(existing)
        key = (uid, request_id)
        if key in c.pending_ids:
            return JSONResponse({"reason": "request_id_pending"}, status_code=409)
        if c.pending.get(uid, 0) >= 128:
            return JSONResponse({"reason": "queue_full", "accepted": False}, status_code=429)
        c.pending_ids[key] = fingerprint
        c.pending[uid] = c.pending.get(uid, 0) + 1
        deadline = time.monotonic() + spec["timeoutSeconds"]
        target = None
        try:
            while time.monotonic() < deadline:
                state = c.states[uid]
                active = state.get("active")
                if (c.stopping or not state.get("serving") or not active
                        or c.clock() - state.get("checkedAt", 0) > 15 or c.clock() - c.last_snapshot > 15):
                    return JSONResponse({"reason": "route_unavailable", "accepted": False}, status_code=503)
                if active["spec"]["ioContract"] != spec["ioContract"]:
                    return JSONResponse({"reason": "io_contract_changed", "accepted": False}, status_code=409)
                # One event loop: no await between selecting route, journaling and counting.
                if c.running_count(active) < active["capacity"]:
                    if active.get("resident"):
                        try:
                            resident.request_body(active["spec"], body, request_id)
                        except ValueError:
                            return JSONResponse({"reason": "inference_contract_changed", "accepted": False}, status_code=409)
                    target = active
                    c.journal.dispatch(uid, request_id, fingerprint, target["name"])
                    c.inflight[target["name"]] = c.inflight.get(target["name"], 0) + 1
                    break
                await asyncio.sleep(0.05)
        finally:
            c.pending_ids.pop(key, None)
            c.pending[uid] -= 1
        if target is None:
            return JSONResponse({"reason": "admission_timeout", "accepted": False}, status_code=503)
        status, result, outcome = 503, {"reason": "worker_outcome_unknown", "accepted": True}, "unknown"
        try:
            # No redirect following, transport retries or cross-worker retry after dispatch.
            async with asyncio.timeout(max(0.1, deadline - time.monotonic())):
                path = "/generate" if target.get("resident") else target["spec"]["requestPath"]
                payload = resident.request_body(target["spec"], body, request_id) if target.get("resident") else body
                async with c.transport.stream("POST", c.endpoint(target) + path,
                        json=payload, headers={"X-Request-ID": request_id},
                        timeout=max(0.1, deadline - time.monotonic())) as response:
                    response_bytes = bytearray()
                    async for chunk in response.aiter_bytes():
                        response_bytes.extend(chunk)
                        if len(response_bytes) > 4 * 1024 * 1024:
                            raise ValueError("response_too_large")
                    decoded = json.loads(response_bytes)
                    json.dumps(decoded, allow_nan=False)
                    if target.get("resident"):
                        response.raise_for_status()
                        resident.validate_result(target, request_id, decoded)
                    result, status, outcome = decoded, response.status_code, "completed"
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError):
            pass
        except asyncio.CancelledError:
            c.journal.finish(uid, request_id, outcome, status, result)
            raise
        finally:
            c.inflight[target["name"]] -= 1
        c.journal.finish(uid, request_id, outcome, status, result)
        return JSONResponse(result, status_code=status, headers={"X-Runtime-Target": target["name"], "X-Request-State": outcome})

    return app


app = create_app()
