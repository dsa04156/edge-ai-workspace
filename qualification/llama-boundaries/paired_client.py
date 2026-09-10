"""Run on Nano: randomized paired local/remote waves, exact shared token fixtures.

This fixed finite-arrival design measures queueing/ready routing, not sustained RPS.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import random
import socket
import time

import bench


def schedule(blocks, seed):
    rng = random.Random(seed)
    plan = []
    for block in range(blocks):
        for concurrency in (1, 2, 4):
            routes = ["nano", "remote"]
            rng.shuffle(routes)
            for route in routes:
                plan.append({"block": block, "concurrency": concurrency, "route": route})
    return plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--local", default="http://127.0.0.1:18200")
    p.add_argument("--remote", required=True)
    p.add_argument("--remote-node", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--blocks", type=int, default=3, choices=range(1, 4))
    p.add_argument("--expected-host", default="etri-dev0001-jetorn")
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--remote-only", action="store_true",
                   help="Measure only Nano-origin remote path; not a paired comparison")
    args = p.parse_args()
    os.environ["BOUNDARY_KEY_FILE"] = str(args.key_file.resolve())
    if socket.gethostname() != args.expected_host:
        raise RuntimeError("request generator is not running on intended Nano")
    args.output.mkdir(parents=True, exist_ok=False)
    urls = {"nano": args.local, "remote": args.remote}
    if args.remote_only:
        urls.pop('nano')
    props = {key: bench.api(url, "/props") for key, url in urls.items()}
    builds = {p.get("build_info") for p in props.values()}
    contexts = {p["default_generation_settings"]["n_ctx"] for p in props.values()}
    if len(builds) != 1 or len(contexts) != 1 or contexts != {2048}:
        raise RuntimeError("runtime/context mismatch")
    plan = schedule(args.blocks, 20260907)
    if args.remote_only:
        plan = [step for step in plan if step['route'] == 'remote']
    fixtures = json.loads(args.dataset.read_text())
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2))
    (args.output / "provenance.json").write_text(json.dumps({"server_props": props, "dataset_sha256": bench.digest(args.dataset),
        "requester": socket.gethostname(), "paired": not args.remote_only, "arrival_pattern": "simultaneous wave, same token fixtures by block/concurrency, relative arrival offset zero", "seed": 20260907, "holdout": False, "production_enabled": False}, indent=2))
    journal = bench.Journal(args.output / "requests.jsonl")
    rows = []
    start = time.monotonic()
    try:
        for step in plan:
            if time.monotonic() - start > 180:
                raise RuntimeError("paired test wall deadline")
            base = urls[step["route"]]
            bench.api(base, "/health")
            planned = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=step["concurrency"]) as pool:
                futures = [pool.submit(bench.stream, base, fixtures[(step["block"] + i) % len(fixtures)],
                                      run_id=args.output.name, request_id=f"b{step['block']}-c{step['concurrency']}-{step['route']}-{i}",
                                      phase="measure", node=args.expected_host if step["route"] == "nano" else args.remote_node,
                                      planned_at=planned, timeout=30) for i in range(step["concurrency"])]
                stage = []
                for future in concurrent.futures.as_completed(futures):
                    row = future.result()
                    row.update(step, method="ready-route-remote-only" if args.remote_only else "ready-route-paired", matched_comparison=not args.remote_only)
                    journal.write(row)
                    rows.append(row)
                    stage.append(row)
            if any(r["status"] != "ok" or not r["zero_prefix_reuse_verified"] for r in stage):
                raise RuntimeError("failed/mismatched/cache-reused request; later waves cancelled")
        summary = {route: {str(c): bench.summarize([r for r in rows if r["route"] == route and r["concurrency"] == c]) for c in (1, 2, 4)} for route in urls}
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
    finally:
        journal.close()


if __name__ == "__main__":
    main()
