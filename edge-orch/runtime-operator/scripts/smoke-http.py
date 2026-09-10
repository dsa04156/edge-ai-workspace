#!/usr/bin/env python3
"""Explicit opt-in bounded synthetic traffic; never patches nodes or workloads."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid

import httpx


async def run(base, output):
    evidence = {"startedAt": time.time(), "synthetic": True, "requests": [], "snapshots": []}
    prefix = str(uuid.uuid4())[:8]
    stop = asyncio.Event()
    async with httpx.AsyncClient(base_url=base, timeout=35, trust_env=False) as client:
        async def monitor():
            while not stop.is_set():
                try:
                    response = await client.get("/services")
                    response.raise_for_status()
                    state = response.json()
                    evidence["snapshots"].append({"at": time.time(), "services": [{
                        "name": s["name"], "phase": s["phase"], "reason": s.get("reason"),
                        "node": s.get("active", {}).get("node") if s.get("active") else None,
                        "role": s.get("active", {}).get("role") if s.get("active") else None,
                        "target": s.get("target", {}).get("node") if s.get("target") else None,
                        "retiring": [{"name": t["name"], "node": t["node"], "scaledDown": t.get("scaledDown", False)}
                                     for t in s.get("retiring", [])], "load": s.get("load")}
                        for s in state["services"]]})
                except Exception as exc:
                    evidence["snapshots"].append({"at": time.time(), "error": type(exc).__name__})
                await asyncio.sleep(1)

        async def request(service, delay, phase, seq):
            request_id = f"{prefix}-{service}-{phase}-{seq}"
            started = time.time()
            try:
                response = await client.post(f"/services/{service}/invoke", json={"input": request_id, "delaySeconds": delay},
                                             headers={"X-Request-ID": request_id})
                body = response.json()
                record = {"id": request_id, "phase": phase, "service": service, "startedAt": started,
                          "elapsed": time.time() - started, "status": response.status_code, "body": body,
                          "target": response.headers.get("X-Runtime-Target"), "outcome": response.headers.get("X-Request-State")}
                record["valid"] = response.status_code == 200 and body.get("requestId") == request_id and body.get("output") == request_id
            except Exception as exc:
                record = {"id": request_id, "phase": phase, "service": service, "status": None,
                          "error": type(exc).__name__, "valid": False}
            evidence["requests"].append(record)

        async def phase(label, duration, workers, delay):
            until = time.monotonic() + duration
            async def worker(index):
                seq = 0
                while time.monotonic() < until:
                    await request("quality-api-demo", delay, label, f"{index}-{seq}")
                    seq += 1
                    if workers == 1:
                        await asyncio.sleep(0.8)
            await asyncio.gather(*(worker(i) for i in range(workers)))

        task = asyncio.create_task(monitor())
        try:
            await request("telemetry-transform-demo", 0.1, "isolation-before", 0)
            await phase("baseline", 5, 1, 0.1)
            await phase("pressure", 30, 8, 2)
            await phase("return", 35, 1, 0.1)
            await request("telemetry-transform-demo", 0.1, "isolation-after", 0)
        finally:
            stop.set()
            await task
            evidence["finishedAt"] = time.time()
            evidence["summary"] = {"requests": len(evidence["requests"]),
                "valid": sum(r["valid"] for r in evidence["requests"]),
                "nodes": sorted({r["body"]["node"] for r in evidence["requests"] if r["valid"]})}
            Path(output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(evidence["summary"], ensure_ascii=False))
    if evidence["summary"]["valid"] != evidence["summary"]["requests"]:
        raise SystemExit("some requests failed; see raw evidence")
    transitions, roles = [], []
    for snapshot in evidence["snapshots"]:
        for state in snapshot.get("services", []):
            if state["name"] == "quality-api-demo" and state["node"] and (not transitions or transitions[-1] != state["node"]):
                transitions.append(state["node"])
            if state["name"] == "quality-api-demo" and state.get("role") and (not roles or roles[-1] != state["role"]):
                roles.append(state["role"])
    print("observed route transitions:", transitions)
    print("observed role transitions:", roles)
    if len(roles) < 3 or roles[0] != roles[-1]:
        raise SystemExit("round trip not observed; request success alone is not offloading success")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.base_url.rstrip("/"), args.output))
