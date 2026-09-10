"""Measure each inference worker's fixed-placement saturation curve.

Requests go directly to a worker so controller snapshot/locking time is not
mistaken for model capacity.  The proxy is used only to put all workers in the
same Always-On lifecycle state and to collect a common metrics snapshot.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import threading
import time
from typing import Any
from urllib import request
import uuid


TIERS = ("nano", "agx", "spark")
PROMPT = "In one short sentence, explain why edge computing reduces latency."


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 900.0) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(
        url,
        data=body,
        method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["status"]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.resources: list[dict[str, Any]] = []

    def append(self, target: list[dict[str, Any]], row: dict[str, Any]) -> None:
        with self.lock:
            target.append(row)


class Sampler:
    def __init__(
        self,
        proxy_url: str,
        store: Store,
        context: dict[str, Any],
        interval: float,
        tiers: tuple[str, ...] = TIERS,
    ) -> None:
        self.proxy_url = proxy_url.rstrip("/")
        self.store = store
        self.context = context
        self.interval = interval
        self.tiers = tiers
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(5.0, self.interval * 3))

    def _run(self) -> None:
        while not self.stop_event.is_set():
            sampled_at = time.time()
            try:
                metrics = http_json(f"{self.proxy_url}/metrics", timeout=10.0)
                for tier in self.tiers:
                    self.store.append(
                        self.store.resources,
                        {
                            **self.context,
                            "timestamp": sampled_at,
                            "sampled_node": tier,
                            **metrics.get("nodes", {}).get(tier, {}),
                        },
                    )
            except Exception as exc:
                self.store.append(
                    self.store.resources,
                    {
                        **self.context,
                        "timestamp": sampled_at,
                        "sampled_node": "collector",
                        "status": "error",
                        "error": f"{type(exc).__name__}:{exc}",
                    },
                )
            self.stop_event.wait(self.interval)


def one_request(
    worker_url: str,
    store: Store,
    context: dict[str, Any],
    max_tokens: int,
    timeout: float,
) -> None:
    request_id = str(uuid.uuid4())
    submitted = time.time()
    started = time.perf_counter()
    try:
        result = http_json(
            f"{worker_url.rstrip('/')}/generate",
            {
                "request_id": request_id,
                "prompt": PROMPT,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        completed = time.time()
        row = {
            **context,
            "request_id": request_id,
            "timestamp": submitted,
            "completed_timestamp": completed,
            "client_latency_ms": round(1000.0 * (time.perf_counter() - started), 3),
            "status": "ok",
            **result,
        }
    except Exception as exc:
        row = {
            **context,
            "request_id": request_id,
            "timestamp": submitted,
            "completed_timestamp": time.time(),
            "client_latency_ms": round(1000.0 * (time.perf_counter() - started), 3),
            "status": "error",
            "error": f"{type(exc).__name__}:{exc}",
        }
    store.append(store.requests, row)


def run_condition(
    worker_url: str,
    store: Store,
    context: dict[str, Any],
    *,
    concurrency: int,
    duration: float,
    max_tokens: int,
    timeout: float,
) -> None:
    deadline = time.monotonic() + duration

    def client() -> None:
        while time.monotonic() < deadline:
            one_request(worker_url, store, context, max_tokens, timeout)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(client) for _ in range(concurrency)]
        for future in futures:
            future.result()


def wait_ready(worker_urls: dict[str, str], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        states = {
            tier: http_json(f"{url.rstrip('/')}/health", timeout=10.0)
            for tier, url in worker_urls.items()
        }
        if all(state.get("inference_ready") for state in states.values()):
            return
        time.sleep(1.0)
    raise TimeoutError("not all workers reached inference_ready")


def make_schedule(tiers: tuple[str, ...], levels: tuple[int, ...], blocks: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    schedule: list[dict[str, Any]] = []
    order = 0
    for block in range(1, blocks + 1):
        conditions = [(tier, concurrency) for tier in tiers for concurrency in levels]
        rng.shuffle(conditions)
        for within_block, (tier, concurrency) in enumerate(conditions, 1):
            order += 1
            schedule.append(
                {
                    "condition_id": f"b{block:02d}-o{within_block:02d}-{tier}-c{concurrency}",
                    "block": block,
                    "within_block_order": within_block,
                    "run_order": order,
                    "target_node": tier,
                    "concurrency": concurrency,
                }
            )
    return schedule


def parse_tiers(raw: str) -> tuple[str, ...]:
    tiers = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    invalid = [tier for tier in tiers if tier not in TIERS]
    if not tiers or invalid or len(set(tiers)) != len(tiers):
        raise ValueError(f"tiers must be a unique comma-separated subset of {TIERS}: {raw}")
    return tiers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-url", default="http://192.168.0.56:18101")
    parser.add_argument("--nano-url", default="http://192.168.0.3:18100")
    parser.add_argument("--agx-url", default="http://192.168.0.56:18100")
    parser.add_argument("--spark-url", default="http://192.168.0.5:18100")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tiers", default=",".join(TIERS))
    parser.add_argument("--concurrency", default="1,2,4,8,16,32")
    parser.add_argument("--blocks", type=int, default=3)
    parser.add_argument("--stage-seconds", type=float, default=12.0)
    parser.add_argument("--cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--max-tokens", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--seed", type=int, default=20260904)
    args = parser.parse_args()

    worker_urls = {"nano": args.nano_url, "agx": args.agx_url, "spark": args.spark_url}
    selected_tiers = parse_tiers(args.tiers)
    selected_workers = {tier: worker_urls[tier] for tier in selected_tiers}
    levels = tuple(int(item) for item in args.concurrency.split(","))
    schedule = make_schedule(selected_tiers, levels, args.blocks, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "schedule.csv", schedule)
    (args.output_dir / "run-config.json").write_text(
        json.dumps(vars(args), default=str, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if selected_tiers == TIERS:
        print(json.dumps({"event": "configure", "method": "always_on"}), flush=True)
        configured = http_json(f"{args.proxy_url.rstrip('/')}/method", {"method": "always_on"}, timeout=1800.0)
    else:
        print(json.dumps({"event": "configure", "method": "direct_selected_workers", "tiers": selected_tiers}), flush=True)
        configured = {
            "method": "direct_selected_workers",
            "activation": {
                tier: http_json(
                    f"{url.rstrip('/')}/activate",
                    {"target_state": "ACTIVE", "reason": "fixed_saturation"},
                    timeout=1800.0,
                )
                for tier, url in selected_workers.items()
            },
        }
    wait_ready(selected_workers)
    (args.output_dir / "setup.json").write_text(
        json.dumps(configured, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    store = Store()
    for tier, url in selected_workers.items():
        one_request(
            url,
            store,
            {"condition_id": "warmup", "block": 0, "run_order": 0, "target_node": tier, "concurrency": 1, "excluded": True},
            args.max_tokens,
            args.timeout,
        )
    write_csv(args.output_dir / "requests.csv", store.requests)

    total = len(schedule)
    for index, condition in enumerate(schedule, 1):
        context = {**condition, "excluded": False, "stage_seconds": args.stage_seconds}
        print(json.dumps({"event": "condition_start", "index": index, "total": total, **condition}), flush=True)
        sampler = Sampler(args.proxy_url, store, context, args.sample_interval, selected_tiers)
        sampler.start()
        started = time.time()
        try:
            run_condition(
                worker_urls[condition["target_node"]],
                store,
                context,
                concurrency=condition["concurrency"],
                duration=args.stage_seconds,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            )
        finally:
            completed = time.time()
            sampler.stop()
        condition_rows = [row for row in store.requests if row.get("condition_id") == condition["condition_id"]]
        errors = sum(row.get("status") != "ok" for row in condition_rows)
        print(
            json.dumps(
                {
                    "event": "condition_complete",
                    "index": index,
                    "condition_id": condition["condition_id"],
                    "requests": len(condition_rows),
                    "errors": errors,
                    "elapsed_seconds": round(completed - started, 3),
                }
            ),
            flush=True,
        )
        write_csv(args.output_dir / "requests.csv", store.requests)
        write_csv(args.output_dir / "resources.csv", store.resources)
        if args.cooldown_seconds > 0:
            time.sleep(args.cooldown_seconds)

    print(json.dumps({"event": "run_complete", "requests": len(store.requests), "resources": len(store.resources)}), flush=True)


if __name__ == "__main__":
    main()
