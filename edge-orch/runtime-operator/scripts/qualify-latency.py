#!/usr/bin/env python3
"""Opt-in serial latency measurement of the currently active, qualified Llama route."""
import argparse
import asyncio
import json
import math
from pathlib import Path
import time
import uuid

import httpx


async def run(args):
    rows = []
    prefix = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(base_url=args.base_url, trust_env=False, timeout=35) as client:
        state = (await client.get("/services")).json()
        service = next(s for s in state["services"] if s["name"] == args.service)
        active = service["active"]
        assert service["serving"] and active["resident"]
        assert not service.get("target") and not service.get("retiring")
        contract = active["spec"]["inference"]
        for i in range(20):
            request_id = prefix + "-qualification-" + str(i)
            started = time.monotonic()
            response = await client.post("/services/" + args.service + "/invoke",
                json={"prompt": contract["prompt"], "max_tokens": contract["maxTokens"]},
                headers={"X-Request-ID": request_id})
            elapsed = (time.monotonic() - started) * 1000
            body = response.json()
            valid = (response.status_code == 200 and body.get("request_id") == request_id
                     and body.get("node_id") == active["node"] and body.get("model_digest") == contract["modelDigest"]
                     and bool(body.get("response")) and 0 < body.get("eval_count", 0) <= contract["maxTokens"])
            rows.append({"id": request_id, "status": response.status_code, "milliseconds": elapsed,
                         "valid": valid, "body": body})
            await asyncio.sleep(.2)
    result = {"at": time.time(), "service": args.service, "node": active["node"], "variant": active["variant"],
              "ioContract": active["spec"]["ioContract"], "inference": contract,
              "scope": "serial_client_gateway_roundtrip_including_port_forward", "requests": rows,
              "p95Milliseconds": sorted(r["milliseconds"] for r in rows)[math.ceil(.95 * len(rows)) - 1]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    assert all(r["valid"] for r in rows), "measurement failed; original evidence retained"
    print(json.dumps({"node": result["node"], "valid": len(rows), "p95Milliseconds": result["p95Milliseconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(run(parser.parse_args()))
