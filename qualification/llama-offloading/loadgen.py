"""Concurrent load generator for baseline, static and dynamic scenarios."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time
from urllib import request
import uuid


FIELDS = [
    "scenario", "concurrency", "request_id", "timestamp", "completed_timestamp", "selected_node",
    "physical_node", "selection_reason", "queue_length", "active_requests",
    "cpu_utilization_percent", "gpu_utilization_percent",
    "gpu_memory_utilization_percent", "ram_utilization_percent",
    "temperature_celsius", "ttft_ms", "tokens_per_second", "rtt_ms",
    "predicted_e2e_ms", "actual_e2e_ms", "worker_actual_e2e_ms", "status", "error",
]


def post(url: str, payload: dict, timeout: float) -> dict:
    req = request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def one(proxy_url: str, scenario: str, concurrency: int, max_tokens: int, timeout: float) -> dict:
    request_id = str(uuid.uuid4())
    mode = "dynamic"
    target = None
    if scenario == "nano_only":
        mode = "nano_only"
    elif scenario.startswith("static_"):
        mode = "static"
        target = scenario.removeprefix("static_")
    payload = {
        "request_id": request_id,
        "prompt": "In one short sentence, explain why edge computing reduces latency.",
        "max_tokens": max_tokens,
        "placement_mode": mode,
        "target_node": target,
        "timeout_seconds": timeout,
    }
    try:
        response = post(f"{proxy_url.rstrip('/')}/generate", payload, timeout)
        return {"scenario": scenario, "concurrency": concurrency, **response["placement"], "status": "ok", "error": ""}
    except Exception as exc:
        return {
            "scenario": scenario, "concurrency": concurrency, "request_id": request_id,
            "timestamp": time.time(), "status": "error", "error": f"{type(exc).__name__}:{exc}",
        }


def run(args: argparse.Namespace) -> list[dict]:
    rows: list[dict] = []
    levels = [int(value) for value in args.concurrency.split(",")]
    for level in levels:
        count = max(level, level * args.rounds)
        started = time.time()
        with ThreadPoolExecutor(max_workers=level) as pool:
            futures = [
                pool.submit(one, args.proxy_url, args.scenario, level, args.max_tokens, args.timeout)
                for _ in range(count)
            ]
            rows.extend(future.result() for future in as_completed(futures))
        elapsed = time.time() - started
        print(json.dumps({"scenario": args.scenario, "concurrency": level, "requests": count, "elapsed_seconds": round(elapsed, 3)}), flush=True)
        if args.stage_pause > 0:
            time.sleep(args.stage_pause)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-url", default="http://192.168.0.56:18101")
    parser.add_argument("--scenario", choices=("nano_only", "static_nano", "static_agx", "static_spark", "dynamic"), required=True)
    parser.add_argument("--concurrency", default="1,2,4,8,16")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=16)
    parser.add_argument("--stage-pause", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
