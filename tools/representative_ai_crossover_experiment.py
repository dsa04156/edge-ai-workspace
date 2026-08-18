#!/usr/bin/env python3
"""Find a CPU-to-GPU crossover with real EdgeX frames and a representative model.

This is a benchmark-only temporal-convolution workload.  It is intentionally
not presented as the trained Okdong production model.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import random
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


INPUT_WIDTH = 256
MODEL_VERSION = "representative-temporal-convolution-v1"


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


@dataclass
class TemporalKernel:
    xp: Any
    width: int
    depth: int

    def __post_init__(self) -> None:
        if self.width < INPUT_WIDTH:
            raise ValueError("activation width must be at least the input width")

    @property
    def operations(self) -> int:
        return 9 * self.depth * self.width

    def infer(self, values: list[float]) -> float:
        xp = self.xp
        vector = xp.asarray(values, dtype=xp.float32)
        hidden = xp.tile(vector, math.ceil(self.width / INPUT_WIDTH))[: self.width]
        for _ in range(self.depth):
            hidden = xp.tanh(
                hidden * xp.float32(0.50)
                + xp.roll(hidden, 1) * xp.float32(0.25)
                + xp.roll(hidden, -1) * xp.float32(0.25)
            )
        score = xp.mean(hidden * hidden)
        if xp.__name__ == "cupy":
            xp.cuda.Stream.null.synchronize()
            return float(score.get())
        return float(score)


def model_input(frames: list[dict], sequence: int) -> list[float]:
    values: list[float] = []
    for offset in range(INPUT_WIDTH // 4):
        frame = frames[(sequence + offset) % len(frames)]
        values.extend(
            (
                frame["x"] / 512.0,
                frame["y"] / 512.0,
                frame["z"] / 512.0,
                frame["temperature"] / 512.0,
            )
        )
    return values


def create_server_app():
    import cupy
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="Representative AI crossover benchmark")
    models: dict[tuple[int, int], TemporalKernel] = {}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "backend": "cupy", "modelVersion": MODEL_VERSION}

    @app.post("/infer")
    def infer(payload: dict) -> dict:
        width = int(payload.get("width", 0))
        depth = int(payload.get("depth", 0))
        values = payload.get("values")
        if width < INPUT_WIDTH or width > 2_097_152 or depth < 1 or depth > 64:
            raise HTTPException(422, "unsupported model shape")
        if not isinstance(values, list) or len(values) != INPUT_WIDTH:
            raise HTTPException(422, "values must contain 256 numbers")
        started = time.perf_counter_ns()
        key = (width, depth)
        model = models.get(key)
        if model is None:
            model = TemporalKernel(cupy, width, depth)
            models[key] = model
        score = model.infer(values)
        return {
            "modelVersion": MODEL_VERSION,
            "width": width,
            "depth": depth,
            "operations": model.operations,
            "score": score,
            "serverProcessingMs": (time.perf_counter_ns() - started) / 1_000_000,
        }

    return app


def cpu_burn(stop: multiprocessing.synchronize.Event, ratio: float) -> None:
    period = 0.05
    busy = period * ratio
    while not stop.is_set():
        started = time.perf_counter()
        while time.perf_counter() - started < busy:
            pass
        stop.wait(max(0.0, period - busy))


def summarize(values: list[float]) -> dict:
    return {
        "count": len(values),
        "p50": round(percentile(values, 0.50), 6),
        "p95": round(percentile(values, 0.95), 6),
        "max": round(max(values), 6),
    }


def run_experiment(args: argparse.Namespace) -> dict:
    import numpy
    import sensor_augmentation_experiment as base

    frames, provenance = base.capture_live_frames(
        base_url=args.local_data_url,
        frame_count=args.capture_frame_count,
        timeout_seconds=5,
        max_skew_seconds=5,
        max_age_seconds=10,
    )
    frame_dicts = [frame.as_dict() for frame in frames]
    schedule = [
        (repetition, width, cpu_ratio, method)
        for repetition in range(1, args.repetitions + 1)
        for width in args.widths
        for cpu_ratio in args.cpu_ratios
        for method in ("local", "server1")
    ]
    random.Random(args.seed).shuffle(schedule)
    runs = []
    client = httpx.Client(timeout=30)
    server_warmed: set[int] = set()
    for run_index, (repetition, width, cpu_ratio, method) in enumerate(schedule, 1):
        values = model_input(frame_dicts, run_index)
        local_model = None
        if method == "local":
            local_model = TemporalKernel(numpy, width, args.depth)
            local_model.infer(values)
        elif width not in server_warmed:
            response = client.post(
                f"{args.server_url}/infer",
                json={"width": width, "depth": args.depth, "values": values},
            )
            response.raise_for_status()
            server_warmed.add(width)

        stop = multiprocessing.Event()
        burner = None
        if cpu_ratio > 0:
            burner = multiprocessing.Process(target=cpu_burn, args=(stop, cpu_ratio))
            burner.start()
            time.sleep(0.2)
        latencies: list[float] = []
        server_processing: list[float] = []
        started_cgroup = base.cgroup_snapshot()
        started = time.perf_counter()
        try:
            for sequence in range(args.requests_per_run):
                values = model_input(frame_dicts, sequence)
                request_started = time.perf_counter_ns()
                if local_model is not None:
                    score = local_model.infer(values)
                else:
                    response = client.post(
                        f"{args.server_url}/infer",
                        json={"width": width, "depth": args.depth, "values": values},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if payload["modelVersion"] != MODEL_VERSION:
                        raise RuntimeError("server model version mismatch")
                    score = float(payload["score"])
                    server_processing.append(float(payload["serverProcessingMs"]))
                if not math.isfinite(score):
                    raise RuntimeError("non-finite score")
                latencies.append((time.perf_counter_ns() - request_started) / 1_000_000)
        finally:
            if burner is not None:
                stop.set()
                burner.join(timeout=2)
        elapsed = time.perf_counter() - started
        finished_cgroup = base.cgroup_snapshot()
        cpu_cores_used = (
            (finished_cgroup.usage_usec - started_cgroup.usage_usec)
            / 1_000_000
            / max(elapsed, 1e-9)
        )
        quota_cores = base.cgroup_cpu_limit_cores()
        operations = 9 * args.depth * width
        runs.append(
            {
                "run_index": run_index,
                "repetition": repetition,
                "method": method,
                "width": width,
                "depth": args.depth,
                "operations_per_inference": operations,
                "background_cpu_ratio": cpu_ratio,
                "requests": args.requests_per_run,
                "latency_ms": summarize(latencies),
                "server_processing_ms": summarize(server_processing) if server_processing else None,
                "throughput_per_second": round(args.requests_per_run / elapsed, 6),
                "resource": {
                    "cpu_limit_cores": quota_cores,
                    "cpu_cores_used": round(cpu_cores_used, 6),
                    "cpu_saturation_ratio": round(cpu_cores_used / quota_cores, 6),
                    "throttled_seconds": round(
                        (finished_cgroup.throttled_usec - started_cgroup.throttled_usec)
                        / 1_000_000,
                        6,
                    ),
                    "nr_throttled": finished_cgroup.nr_throttled - started_cgroup.nr_throttled,
                    "memory_end_mib": round(finished_cgroup.memory_current_bytes / 1024 / 1024, 3),
                    "oom_events": finished_cgroup.memory_events_oom - started_cgroup.memory_events_oom,
                },
            }
        )
        print(f"run {run_index}/{len(schedule)} {method=} {width=} {cpu_ratio=} p95={runs[-1]['latency_ms']['p95']}", flush=True)
        time.sleep(args.washout_seconds)
    client.close()
    return {
        "schema_version": "representative-ai-crossover/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "name": "temporal-convolution-performance-proxy",
            "version": MODEL_VERSION,
            "production_model": False,
            "input_width": INPUT_WIDTH,
            "depth": args.depth,
            "limitation": "performance proxy only; weights are deterministic and untrained",
        },
        "input_provenance": provenance,
        "design": {
            "widths": args.widths,
            "cpu_ratios": args.cpu_ratios,
            "repetitions": args.repetitions,
            "requests_per_run": args.requests_per_run,
            "seed": args.seed,
            "schedule": schedule,
        },
        "runs": runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8081)
    run = sub.add_parser("run")
    run.add_argument("--server-url", default="http://representative-ai-server1:8080")
    run.add_argument("--local-data-url", default="http://device-serial-jetson.edgex-edge.svc.cluster.local:59910")
    run.add_argument("--capture-frame-count", type=int, default=120)
    run.add_argument("--widths", default="4096,65536,262144,1048576")
    run.add_argument("--depth", type=int, default=20)
    run.add_argument("--cpu-ratios", default="0,0.5,0.75,1")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--requests-per-run", type=int, default=20)
    run.add_argument("--washout-seconds", type=float, default=0.5)
    run.add_argument("--seed", type=int, default=20260818)
    run.add_argument("--output", default="/tmp/representative-ai-crossover.json")
    args = parser.parse_args()
    if args.command == "run":
        args.widths = [int(value) for value in args.widths.split(",")]
        args.cpu_ratios = [float(value) for value in args.cpu_ratios.split(",")]
    return args


def main() -> None:
    args = parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_server_app(), host="0.0.0.0", port=args.port)
        return
    document = run_experiment(args)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
    print(json.dumps(document, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
