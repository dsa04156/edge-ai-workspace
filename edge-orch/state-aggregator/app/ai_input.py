"""Read-only adapter from the existing EdgeX reader to a protocol-neutral input."""
from datetime import datetime, timezone
import asyncio
import hashlib
import json
import math
import os
import time

import httpx

from .models import EdgeXDevice, TelemetryPoint


def common_ai_request(device: EdgeXDevice, point: TelemetryPoint, *, service_id: str,
                      request_id: str, now: datetime | None = None, max_age_seconds: float = 120) -> dict:
    now = now or datetime.now(timezone.utc)
    if device.name != point.device_name or not point.event_id or point.origin is None:
        raise ValueError("source_identity_missing_or_mismatched")
    if device.admin_state != "UNLOCKED" or device.operating_state != "UP":
        raise ValueError("edgex_device_not_available")
    if not -5 <= (now - point.timestamp).total_seconds() <= max_age_seconds:
        raise ValueError("reading_not_fresh")
    if type(point.value) not in (int, float) or not math.isfinite(point.value):
        raise ValueError("numeric_reading_required")
    if not point.units:
        raise ValueError("reading_unit_required_no_inferred_calibration")
    return {"schema_version": "edgeai.execution/v1", "request_id": request_id, "service_id": service_id,
            "source": {"type": "edgex", "device_id": device.name, "event_id": point.event_id,
                       "profile_id": device.profile_name, "origin_ns": str(point.origin)},
            "timestamp": point.timestamp.isoformat(),
            "input": {"type": "sensor", "data": {"measurements": [
                {"name": point.resource_name, "value": point.value, "unit": point.units}]}}}


class EdgeXAIConsumer:
    """Latest-reading consumer. RuntimeService owns bindings; gateway owns dispatch and replay."""

    def __init__(self, edgex, gateway, base_url, *, clock=time.time):
        self.edgex, self.gateway = edgex, gateway
        self.base_url, self.clock = base_url.rstrip("/"), clock
        self.last, self.next_poll = {}, {}

    async def consume(self, state, devices):
        uid, name, config = state["uid"], state["name"], state["commonAI"]
        binding = config["input"]
        device = next((d for d in devices if d.name == binding["device_id"]), None)
        if device is None or device.profile_name != binding["profile_id"]:
            return {"service": name, "status": "blocked", "reason": "device_profile_unavailable"}
        points = await self.edgex.get_latest_event(device.name)
        selected = [p for p in points if p.resource_name == binding["resource_name"]]
        if len(selected) != 1:
            return {"service": name, "status": "blocked", "reason": "reading_missing_or_ambiguous"}
        point = selected[0]
        identity = [uid, config["service"]["version"], config["max_tokens"], binding,
                    point.event_id, point.resource_name, str(point.origin)]
        request_id = "edgex-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        if self.last.get(uid) == request_id:
            return None
        body = common_ai_request(device, point, service_id=name, request_id=request_id,
                                 now=datetime.fromtimestamp(self.clock(), timezone.utc))
        # Check the prior outcome after a consumer restart. Unknown dispatches
        # are inspected, never retried against a different worker.
        path = f"{self.base_url}/services/{name}"
        saved = await self.gateway.get(path + "/requests/" + request_id)
        if saved.status_code == 200:
            self.last[uid] = request_id
            return {"service": name, "request_id": request_id, "status": "already_recorded"}
        saved.raise_for_status() if saved.status_code != 404 else None
        self.last[uid] = request_id
        try:
            response = await self.gateway.post(path + "/invoke", json=body,
                headers={"X-Request-ID": request_id, "X-Runtime-Service-Uid": uid})
            result = response.json()
            return {"service": name, "request_id": request_id, "http_status": response.status_code,
                    "status": result.get("result", {}).get("status", "rejected"),
                    "execution": result.get("execution"), "reason": result.get("reason")}
        except (httpx.HTTPError, ValueError):
            return {"service": name, "request_id": request_id, "status": "unknown", "reason": "gateway_response_unavailable"}

    async def tick(self):
        response = await self.gateway.get(self.base_url + "/services")
        response.raise_for_status()
        payload, now = response.json(), self.clock()
        if payload.get("lastError") or not 0 <= payload.get("snapshotAgeSeconds", 999) < 15:
            return []
        services = [s for s in payload["services"] if s.get("serving")
            and 0 <= now - s.get("checkedAt", 0) < 15
            and (s.get("commonAI") or {}).get("offload", {}).get("enabled")]
        present = {s["uid"] for s in services}
        self.last = {k: v for k, v in self.last.items() if k in present}
        self.next_poll = {k: v for k, v in self.next_poll.items() if k in present}
        due = [s for s in services if now >= self.next_poll.get(s["uid"], 0)]
        if not due:
            return []
        devices = await self.edgex.get_devices()
        outcomes = []
        for state in due:
            self.next_poll[state["uid"]] = now + state["commonAI"]["input"]["poll_seconds"]
            try:
                result = await self.consume(state, devices)
                if result:
                    outcomes.append(result)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                outcomes.append({"service": state["name"], "status": "blocked", "reason": type(exc).__name__})
        return outcomes


async def run_consumer():
    from .edgex import EdgeXClient
    edgex = EdgeXClient(os.environ["EDGEX_CORE_METADATA_URL"], os.environ["EDGEX_CORE_DATA_URL"])
    async with httpx.AsyncClient(timeout=35, trust_env=False) as gateway:
        consumer = EdgeXAIConsumer(edgex, gateway, os.environ["COMMON_RUNTIME_URL"])
        while True:
            try:
                for outcome in await consumer.tick():
                    print(json.dumps(outcome, ensure_ascii=False), flush=True)
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                print(json.dumps({"status": "blocked", "reason": type(exc).__name__}), flush=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_consumer())
