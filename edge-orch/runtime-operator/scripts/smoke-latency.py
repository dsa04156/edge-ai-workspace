#!/usr/bin/env python3
"""Opt-in qualified GPU requests: prove latency-triggered move and measured recovery."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import uuid

import httpx


async def run(args):
    evidence = {"startedAt": time.time(), "requests": [], "snapshots": []}
    done = asyncio.Event()
    latest = {}
    prefix = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(base_url=args.base_url, trust_env=False, timeout=35) as client:
        async def observe():
            data = (await client.get("/services")).json()
            s = next(s for s in data["services"] if s["name"] == args.service)
            latest.clear()
            latest.update(s)
            evidence["snapshots"].append({"at": time.time(), "phase": s["phase"], "reason": s.get("reason"),
                "activeNode": s.get("active", {}).get("node"), "activeRole": s.get("active", {}).get("role"),
                "load": s.get("load"), "latency": s.get("latency"), "lastTransition": s.get("lastTransition"),
                "target": {k: s["target"].get(k) for k in ("node", "role", "triggerReason")} if s.get("target") else None,
                "retiring": [t["node"] for t in s.get("retiring", [])], "lastRelease": s.get("lastRelease")})
        await observe()
        assert latest["serving"] and latest["active"]["role"] == "edge" and not latest.get("target")
        policy = latest["active"]["spec"]["policy"]
        # Live CR is also archived separately because policy-only edits preserve this revision.
        assert policy.get("latency") and policy["pressureSeconds"] > 200
        evidence["activeRevisionPolicy"] = policy
        contract = latest["active"]["spec"]["inference"]
        evidence["inferenceContract"] = contract
        async def monitor():
            while not done.is_set():
                try:
                    await observe()
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    evidence["snapshots"].append({"at": time.time(), "error": type(exc).__name__})
                await asyncio.sleep(1)
        async def invoke(phase, i):
            request_id = f"{prefix}-{phase}-{i}"
            started = time.monotonic()
            try:
                response = await client.post("/services/" + args.service + "/invoke",
                    json={"prompt": contract["prompt"], "max_tokens": contract["maxTokens"]},
                    headers={"X-Request-ID": request_id})
                body = response.json()
                valid = (response.status_code == 200 and body.get("request_id") == request_id
                         and body.get("model_digest") == contract["modelDigest"] and bool(body.get("response"))
                         and 0 < body.get("eval_count", 0) <= contract["maxTokens"])
                row = {"id": request_id, "phase": phase, "status": response.status_code, "body": body, "valid": valid}
            except (httpx.HTTPError, ValueError) as exc:
                row = {"id": request_id, "phase": phase, "valid": False, "error": type(exc).__name__}
            row["elapsedMilliseconds"] = (time.monotonic() - started) * 1000
            evidence["requests"].append(row)
        monitor_task = asyncio.create_task(monitor())
        try:
            until = time.monotonic() + 35
            async def pressure(worker):
                i = 0
                while time.monotonic() < until:
                    await invoke("pressure", f"{worker}-{i}")
                    i += 1
            await asyncio.gather(*(pressure(i) for i in range(6)))
            until = time.monotonic() + 120
            i = 0
            while time.monotonic() < until:
                await invoke("recovery", i)
                i += 1
                if (latest.get("lastTransition", {}).get("reason") == "sustained_low_load_return"
                        and latest.get("active", {}).get("role") == "edge" and not latest.get("retiring")
                        and not latest.get("target") and any(s.get("activeRole") == "server" for s in evidence["snapshots"])):
                    break
                await asyncio.sleep(.6)
        finally:
            done.set()
            await monitor_task
            await observe()
            transitions = {s["lastTransition"]["at"]: s["lastTransition"] for s in evidence["snapshots"] if s.get("lastTransition")}
            recent = [t for at, t in transitions.items() if at >= evidence["startedAt"]]
            evidence["finishedAt"] = time.time()
            evidence["summary"] = {"requests": len(evidence["requests"]), "valid": sum(r["valid"] for r in evidence["requests"]),
                "transitions": recent, "latencyTriggered": any(t["reason"] == "sustained_latency_breach" for t in recent),
                "returned": any(t["reason"] == "sustained_low_load_return" for t in recent) and latest["active"]["role"] == "edge",
                "retiring": len(latest.get("retiring", []))}
            Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(evidence["summary"]))
        result = evidence["summary"]
        assert result["requests"] == result["valid"] and result["latencyTriggered"] and result["returned"] and not result["retiring"], "latency round trip failed; original evidence retained"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(run(parser.parse_args()))
