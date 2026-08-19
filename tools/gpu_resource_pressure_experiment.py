#!/usr/bin/env python3
"""Measure GPU compute/memory pressure against inference latency and throughput.

The benchmark runs inside a bounded HAMi vGPU allocation.  It captures real
Arduino readings through EdgeX Local Data, uses the existing representative
temporal convolution proxy, and never changes the active inference route.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL_VERSION = "representative-temporal-convolution-v1"


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "p50": round(percentile(values, 0.50), 6),
        "p95": round(percentile(values, 0.95), 6),
        "max": round(max(values), 6),
    }


def _parse_number(raw: str) -> float | None:
    value = raw.strip().replace("MiB", "").replace("W", "")
    if not value or value in {"N/A", "[Not Supported]"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def query_gpu_sample(assigned_memory_mib: int) -> dict[str, float | None]:
    gpu_raw = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,utilization.memory,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.splitlines()[0]
    gpu_values = [_parse_number(value) for value in gpu_raw.split(",")]
    process_raw = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.splitlines()
    visible_process_memory: list[float] = []
    for line in process_raw:
        parts = line.split(",")
        if len(parts) != 2:
            continue
        memory_mib = _parse_number(parts[1])
        if memory_mib is not None:
            visible_process_memory.append(memory_mib)
    process_memory_mib = sum(visible_process_memory) if visible_process_memory else None
    memory_ratio = (
        process_memory_mib / assigned_memory_mib * 100
        if process_memory_mib is not None and assigned_memory_mib > 0
        else None
    )
    return {
        "gpu_utilization_percent": gpu_values[0],
        "gpu_memory_utilization_percent": gpu_values[1],
        "temperature_celsius": gpu_values[2],
        "power_watts": gpu_values[3],
        "process_memory_mib": process_memory_mib,
        "assigned_memory_used_percent": memory_ratio,
    }


class GpuSampler:
    def __init__(self, interval_seconds: float, assigned_memory_mib: int) -> None:
        self.interval_seconds = interval_seconds
        self.assigned_memory_mib = assigned_memory_mib
        self.samples: list[dict[str, float | None]] = []
        self.errors: list[str] = []
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                self.samples.append(query_gpu_sample(self.assigned_memory_mib))
            except Exception as exc:  # measurement failure must remain visible
                self.errors.append(f"{type(exc).__name__}: {exc}")
            self.stop.wait(self.interval_seconds)

    def __enter__(self) -> "GpuSampler":
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=10)


class ComputePressure:
    def __init__(self, cupy: Any, duty_ratio: float, matrix_size: int) -> None:
        self.cupy = cupy
        self.duty_ratio = duty_ratio
        self.matrix_size = matrix_size
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.errors: list[str] = []
        self.a = cupy.ones(matrix_size * matrix_size, dtype=cupy.float32)
        self.output = cupy.empty_like(self.a)
        cupy.cuda.Stream.null.synchronize()

    def _run(self) -> None:
        cupy = self.cupy
        stream = cupy.cuda.Stream(non_blocking=True)
        period_seconds = 0.1
        busy_seconds = period_seconds * self.duty_ratio
        try:
            while not self.stop.is_set():
                cycle_started = time.perf_counter()
                while time.perf_counter() - cycle_started < busy_seconds:
                    with stream:
                        for _ in range(16):
                            cupy.multiply(
                                self.a,
                                cupy.float32(1.000001),
                                out=self.output,
                            )
                            cupy.tanh(self.output, out=self.a)
                    stream.synchronize()
                remaining = period_seconds - (time.perf_counter() - cycle_started)
                if remaining > 0:
                    self.stop.wait(remaining)
        except Exception as exc:
            self.errors.append(f"{type(exc).__name__}: {exc}")
            self.stop.set()

    def __enter__(self) -> "ComputePressure":
        if self.duty_ratio > 0:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=10)


def _summarize_samples(samples: list[dict[str, float | None]]) -> dict[str, dict]:
    keys = (
        "gpu_utilization_percent",
        "gpu_memory_utilization_percent",
        "temperature_celsius",
        "power_watts",
        "process_memory_mib",
        "assigned_memory_used_percent",
    )
    return {
        key: summarize(
            [float(sample[key]) for sample in samples if sample.get(key) is not None]
        )
        for key in keys
    }


def run_experiment(args: argparse.Namespace) -> dict:
    import cupy
    import representative_ai_crossover_experiment as representative
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
        (repetition, compute_ratio, memory_mib)
        for repetition in range(1, args.repetitions + 1)
        for compute_ratio in args.compute_duty_ratios
        for memory_mib in args.memory_loads_mib
    ]
    random.Random(args.seed).shuffle(schedule)
    runs: list[dict] = []
    for run_index, (repetition, compute_ratio, memory_mib) in enumerate(schedule, 1):
        pool = cupy.get_default_memory_pool()
        pool.free_all_blocks()
        cupy.cuda.Stream.null.synchronize()
        allocation_error: str | None = None
        inference_errors: list[str] = []
        latencies_ms: list[float] = []
        successes = 0
        elapsed = 0.0
        sampler = GpuSampler(args.sample_interval_seconds, args.assigned_gpu_memory_mib)
        try:
            kernel = representative.TemporalKernel(cupy, args.width, args.depth)
            values = representative.model_input(frame_dicts, run_index)
            pressure = ComputePressure(cupy, compute_ratio, args.matrix_size)
            memory_buffer = None
            if memory_mib > 0:
                try:
                    memory_buffer = cupy.empty(memory_mib * 1024 * 1024, dtype=cupy.uint8)
                    memory_buffer.fill(1)
                    cupy.cuda.Stream.null.synchronize()
                except cupy.cuda.memory.OutOfMemoryError as exc:
                    allocation_error = f"OutOfMemoryError: {exc}"
            if allocation_error is None:
                for _ in range(args.warmup_requests):
                    kernel.infer(values)
                with pressure, sampler:
                    started = time.perf_counter()
                    while time.perf_counter() - started < args.duration_seconds:
                        request_started = time.perf_counter_ns()
                        try:
                            score = kernel.infer(values)
                            if not math.isfinite(score):
                                raise RuntimeError("non-finite score")
                            successes += 1
                            latencies_ms.append(
                                (time.perf_counter_ns() - request_started) / 1_000_000
                            )
                        except Exception as exc:
                            inference_errors.append(f"{type(exc).__name__}: {exc}")
                            break
                    elapsed = time.perf_counter() - started
                inference_errors.extend(
                    f"ComputePressure: {error}" for error in pressure.errors
                )
            else:
                with sampler:
                    time.sleep(min(1.0, args.duration_seconds))
            del memory_buffer
            del pressure
            del kernel
        except Exception as exc:
            inference_errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            cupy.cuda.Stream.null.synchronize()
            pool.free_all_blocks()
        runs.append(
            {
                "run_index": run_index,
                "repetition": repetition,
                "compute_duty_ratio": compute_ratio,
                "memory_load_mib": memory_mib,
                "requests_completed": successes,
                "elapsed_seconds": round(elapsed, 6),
                "latency_ms": summarize(latencies_ms),
                "throughput_per_second": round(successes / elapsed, 6) if elapsed else 0.0,
                "gpu": _summarize_samples(sampler.samples),
                "sampler_errors": sampler.errors,
                "allocation_error": allocation_error,
                "inference_errors": inference_errors,
            }
        )
        latest = runs[-1]
        print(
            f"run {run_index}/{len(schedule)} rep={repetition} compute={compute_ratio} "
            f"memory={memory_mib}MiB gpu_p95="
            f"{latest['gpu']['gpu_utilization_percent']['p95']} "
            f"memory_p95={latest['gpu']['assigned_memory_used_percent']['p95']} "
            f"latency_p95={latest['latency_ms']['p95']} "
            f"throughput={latest['throughput_per_second']} "
            f"allocation_error={bool(allocation_error)}",
            flush=True,
        )
        time.sleep(args.washout_seconds)
    return {
        "schema_version": "gpu-resource-pressure/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "name": "temporal-convolution-performance-proxy",
            "version": MODEL_VERSION,
            "production_model": False,
            "width": args.width,
            "depth": args.depth,
            "operations_per_inference": 9 * args.width * args.depth,
        },
        "input_provenance": provenance,
        "execution": {
            "node_name": os.getenv("NODE_NAME", "unknown"),
            "pod_name": os.getenv("POD_NAME", "unknown"),
            "mode": os.getenv("EXECUTION_MODE", "bounded-hami-vgpu"),
            "co_resident_service": os.getenv("CO_RESIDENT_SERVICE", "none"),
            "assigned_gpu_cores_percent": args.assigned_gpu_cores_percent,
            "assigned_gpu_memory_mib": args.assigned_gpu_memory_mib,
        },
        "design": {
            "compute_duty_ratios": args.compute_duty_ratios,
            "memory_loads_mib": args.memory_loads_mib,
            "repetitions": args.repetitions,
            "duration_seconds": args.duration_seconds,
            "sample_interval_seconds": args.sample_interval_seconds,
            "seed": args.seed,
            "schedule": schedule,
            "primary_service_degradation_gate": {
                "latency_increase_percent": 20,
                "throughput_decrease_percent": 5,
            },
            "resource_pressure_observation_gate": {
                "gpu_utilization_percent": 85,
                "assigned_gpu_memory_used_percent": 85,
            },
        },
        "runs": runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--local-data-url",
        default="http://device-serial-jetson.edgex-edge.svc.cluster.local:59910",
    )
    parser.add_argument("--capture-frame-count", type=int, default=120)
    parser.add_argument("--width", type=int, default=65536)
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--compute-duty-ratios", default="0,0.5,0.75,1")
    parser.add_argument("--memory-loads-mib", default="0,128,256,384")
    parser.add_argument("--repetitions", type=int, default=6)
    parser.add_argument("--duration-seconds", type=float, default=4)
    parser.add_argument("--warmup-requests", type=int, default=5)
    parser.add_argument("--washout-seconds", type=float, default=0.5)
    parser.add_argument("--sample-interval-seconds", type=float, default=0.5)
    parser.add_argument("--matrix-size", type=int, default=2048)
    parser.add_argument("--assigned-gpu-cores-percent", type=int, default=20)
    parser.add_argument("--assigned-gpu-memory-mib", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--output", default="/tmp/gpu-resource-pressure.json")
    args = parser.parse_args()
    args.compute_duty_ratios = [
        float(value) for value in args.compute_duty_ratios.split(",")
    ]
    args.memory_loads_mib = [int(value) for value in args.memory_loads_mib.split(",")]
    return args


def main() -> None:
    args = parse_args()
    document = run_experiment(args)
    Path(args.output).write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"result written to {args.output}")


if __name__ == "__main__":
    main()
