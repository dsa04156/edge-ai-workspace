"""Bounded client-only smoke against an existing experimental llama-server.

Does not start, stop or configure the serving process. Not a matched comparison.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import socket
import threading
import time

import bench


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--node", required=True)
    p.add_argument("--ramp", action="store_true", help="bounded exploratory waves at concurrency 1,2,4; not a saturation certification")
    args = p.parse_args()
    fixtures = json.loads(args.dataset.read_text())[:4]
    if len(fixtures) != 4 or any(len(x["prompt"]) != 512 or x["n_predict"] != 128 for x in fixtures):
        raise ValueError("smoke requires four 512/128 fixtures: one warmup + three measurements")
    props = bench.api(args.base, "/props")
    args.output.mkdir(parents=True, exist_ok=False)
    provenance = {"requester": socket.gethostname(), "server": args.node, "props": props,
                  "dataset_sha256": bench.digest(args.dataset), "matched_comparison": False,
                  "activation_measured": False, "resource_release_measured": False,
                  "reason": "Existing experimental runtime; configuration and build differ from RTX smoke.",
                  "gpu_allocation_report": bench.api("http://127.0.0.1:11435", "/api/ps"),
                  "ollama_version": bench.api("http://127.0.0.1:11435", "/api/version"),
                  "cuda": bench.command(["/usr/local/cuda/bin/nvcc", "--version"]),
                  "power_mode": bench.command(["/usr/sbin/nvpmodel", "-q"])}
    (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    journal = bench.Journal(args.output / "requests.jsonl")
    raw_resources = bench.Journal(args.output / "resources.jsonl")
    stop = threading.Event()
    def collect():
        while not stop.is_set():
            raw_resources.write(bench.resources())
            stop.wait(.5)
    monitor = threading.Thread(target=collect, daemon=True)
    monitor.start()
    records = []
    try:
        for i, body in enumerate(fixtures):
            record = bench.stream(args.base, body, run_id=args.output.name, request_id=body["request_id"],
                                  phase="warmup" if i == 0 else "measure", node=args.node,
                                  planned_at=time.time(), timeout=30)
            record.update(concurrency=1, method="existing-active-runtime", matched_comparison=False)
            journal.write(record)
            records.append(record)
            if record["status"] != "ok":
                raise RuntimeError(f"Smoke stopped: {record['status']}")
        if args.ramp:
            for concurrency in (2, 4):
                sample = bench.resources()
                if sample["ram_available_mib"] < 1024:
                    raise RuntimeError("RAM safety floor")
                # A barrier-free submit wave: actual send times and dispatch lag remain visible.
                planned = time.time()
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = [pool.submit(bench.stream, args.base, fixtures[i], run_id=args.output.name,
                                           request_id=f"c{concurrency}-{fixtures[i]['request_id']}", phase="measure",
                                           node=args.node, planned_at=planned, timeout=30)
                               for i in range(concurrency)]
                    stage = []
                    for future in concurrent.futures.as_completed(futures):
                        record = future.result()
                        record.update(concurrency=concurrency, method="existing-active-runtime", matched_comparison=False)
                        journal.write(record)
                        records.append(record)
                        stage.append(record)
                if any(r["status"] != "ok" for r in stage):
                    raise RuntimeError("Ramp aborted after unsuccessful stage; no retries")
        summary = bench.summarize(records)
        summary["by_concurrency"] = {str(c): bench.summarize([r for r in records if r["concurrency"] == c]) for c in sorted({r["concurrency"] for r in records})}
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
    finally:
        stop.set()
        monitor.join(timeout=15)
        journal.close()
        raw_resources.close()


if __name__ == "__main__":
    main()
