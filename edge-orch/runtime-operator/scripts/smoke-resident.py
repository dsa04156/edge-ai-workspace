#!/usr/bin/env python3
"""Opt-in actual model traffic against a reviewed resident RuntimeService."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid

import httpx


async def run(base, service, output):
    evidence = {"startedAt": time.time(), "service": service, "requests": [], "snapshots": []}
    prefix = str(uuid.uuid4())[:8]
    done = asyncio.Event()
    async with httpx.AsyncClient(base_url=base, timeout=35, trust_env=False) as client:
        state = (await client.get("/services")).json()
        selected = next(s for s in state["services"] if s["name"] == service)
        assert selected["serving"] and selected["active"].get("resident")
        contract = selected["active"]["spec"]["inference"]
        evidence["inferenceContract"] = contract
        payload = {"prompt": contract["prompt"], "max_tokens": contract["maxTokens"]}

        async def monitor():
            while not done.is_set():
                try:
                    x = (await client.get("/services")).json()
                    evidence["snapshots"].append({"at": time.time(), "services": [{
                        "name": s["name"], "phase": s["phase"], "node": s.get("active", {}).get("node") if s.get("active") else None,
                        "role": s.get("active", {}).get("role") if s.get("active") else None,
                        "targetNode": s.get("target", {}).get("node") if s.get("target") else None,
                        "reason": s.get("reason"), "load": s.get("load"),
                        "retiringNodes": [t["node"] for t in s.get("retiring", [])]} for s in x["services"]]})
                except Exception as exc:
                    evidence["snapshots"].append({"at": time.time(), "error": type(exc).__name__})
                await asyncio.sleep(1)

        async def invoke(phase, seq):
            request_id = f"{prefix}-{phase}-{seq}"
            started = time.time()
            try:
                r = await client.post(f"/services/{service}/invoke", json=payload, headers={"X-Request-ID": request_id})
                body = r.json()
                good = (r.status_code == 200 and body.get("request_id") == request_id
                        and body.get("model_digest") == contract["modelDigest"] and bool(body.get("response"))
                        and 0 < body.get("eval_count", 0) <= contract["maxTokens"])
                record = {"id": request_id, "phase": phase, "status": r.status_code, "body": body,
                          "target": r.headers.get("X-Runtime-Target"), "outcome": r.headers.get("X-Request-State"), "valid": good}
            except Exception as exc:
                record = {"id": request_id, "phase": phase, "valid": False, "error": type(exc).__name__}
            record.update(startedAt=started, elapsed=time.time() - started)
            evidence["requests"].append(record)

        task = asyncio.create_task(monitor())
        try:
            await invoke("baseline", 0)
            until = time.monotonic() + 25
            async def load(index):
                seq = 0
                while time.monotonic() < until:
                    await invoke("pressure", f"{index}-{seq}")
                    seq += 1
            await asyncio.gather(*(load(i) for i in range(6)))
            for i in range(6):
                await invoke("return", i)
                await asyncio.sleep(10)
        finally:
            done.set()
            await task
            evidence["finishedAt"] = time.time()
            roles, nodes = [], []
            for x in evidence["snapshots"]:
                for s in x.get("services", []):
                    if s["name"] == service and s.get("node"):
                        if not nodes or nodes[-1] != s["node"]:
                            nodes.append(s["node"])
                        if not roles or roles[-1] != s["role"]:
                            roles.append(s["role"])
            evidence["summary"] = {"requests": len(evidence["requests"]), "valid": sum(r["valid"] for r in evidence["requests"]),
                "roles": roles, "nodes": nodes, "roundTrip": len(roles) >= 3 and roles[0] == roles[-1]}
            Path(output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(evidence["summary"]))
    if not evidence["summary"]["roundTrip"] or evidence["summary"]["requests"] != evidence["summary"]["valid"]:
        raise SystemExit("resident round trip failed; original evidence retained")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--service", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    asyncio.run(run(args.base_url, args.service, args.output))
