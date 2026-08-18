#!/usr/bin/env python3
"""Run a reproducible local-vs-Server1 inference pressure experiment.

The script is copied into the running sensor-anomaly-demo container and executed
there so the benchmark shares the production container's CPU and memory cgroup.
It never changes the Deployment or the active inference route.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

REPOSITORY_SERVICE_ROOT = (
    Path(__file__).resolve().parents[1] / "edge-orch" / "sensor-anomaly-demo"
)
for service_root in (Path("/app"), REPOSITORY_SERVICE_ROOT):
    if (service_root / "app" / "config.py").is_file():
        sys.path.insert(0, str(service_root))
        break

from app.config import Settings
from app.model_adapter import build_model_adapter
from app.models import AccelerationFrame, AxisSample


CGROUP = Path("/sys/fs/cgroup")
DEFAULT_SERVER_URL = "http://sensor-anomaly-inference-server1:8080"
DEFAULT_SOURCE_MODEL_VERSION = "baseline-1.0.0"
DEFAULT_CANDIDATE_MODEL_VERSION = "cuda-baseline-1.0.0"


@dataclass(frozen=True)
class CgroupSnapshot:
    observed_at: float
    usage_usec: int
    throttled_usec: int
    nr_throttled: int
    memory_current_bytes: int
    memory_events_oom: int
    memory_events_oom_kill: int


def _read_key_values(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, raw = line.split(maxsplit=1)
        values[key] = int(raw)
    return values


def cgroup_cpu_limit_cores() -> float:
    quota, period = (CGROUP / "cpu.max").read_text(encoding="utf-8").split()
    if quota == "max":
        return float(os.cpu_count() or 1)
    return int(quota) / int(period)


def cgroup_snapshot() -> CgroupSnapshot:
    cpu = _read_key_values(CGROUP / "cpu.stat")
    memory = _read_key_values(CGROUP / "memory.events")
    return CgroupSnapshot(
        observed_at=time.monotonic(),
        usage_usec=cpu.get("usage_usec", 0),
        throttled_usec=cpu.get("throttled_usec", 0),
        nr_throttled=cpu.get("nr_throttled", 0),
        memory_current_bytes=int(
            (CGROUP / "memory.current").read_text(encoding="utf-8").strip()
        ),
        memory_events_oom=memory.get("oom", 0),
        memory_events_oom_kill=memory.get("oom_kill", 0),
    )


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def _cpu_burn(stop: multiprocessing.synchronize.Event, duty_cycle: float) -> None:
    period_seconds = 0.1
    busy_seconds = period_seconds * duty_cycle
    while not stop.is_set():
        cycle_started = time.perf_counter()
        while time.perf_counter() - cycle_started < busy_seconds:
            pass
        remaining = period_seconds - (time.perf_counter() - cycle_started)
        if remaining > 0:
            stop.wait(remaining)


class CpuPressure:
    def __init__(self, requested_ratio: float, quota_cores: float) -> None:
        self.requested_ratio = requested_ratio
        self.quota_cores = quota_cores
        self.duty_cycle = min(1.0, requested_ratio * quota_cores)
        self.stop = multiprocessing.Event()
        self.process: multiprocessing.Process | None = None

    def __enter__(self) -> CpuPressure:
        if self.duty_cycle > 0:
            self.process = multiprocessing.Process(
                target=_cpu_burn,
                args=(self.stop, self.duty_cycle),
                daemon=True,
            )
            self.process.start()
            time.sleep(0.5)
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        if self.process is not None:
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)


class MemoryPressure:
    def __init__(self, memory_load_mib: int) -> None:
        self.memory_load_mib = memory_load_mib
        self.buffer: bytearray | None = None

    def __enter__(self) -> MemoryPressure:
        if self.memory_load_mib > 0:
            self.buffer = bytearray(self.memory_load_mib * 1024 * 1024)
            for offset in range(0, len(self.buffer), 4096):
                self.buffer[offset] = 1
        return self

    def __exit__(self, *_: object) -> None:
        self.buffer = None


def _origin(run_index: int, sequence: int) -> int:
    return 1_900_000_000_000_000_000 + run_index * 1_000_000 + sequence


def local_inferer(run_index: int) -> Callable[[int], None]:
    settings = Settings.from_env().model_copy(
        update={
            "service_role": "edge-worker",
            "model_backend": "online-baseline",
            "model_version": DEFAULT_SOURCE_MODEL_VERSION,
        }
    )
    model = build_model_adapter(settings)

    def infer(sequence: int) -> None:
        origin = _origin(run_index, sequence)
        temperature = AxisSample(
            origin=origin,
            value_type="Float64",
            value=280.0 + (sequence % 5),
        )
        model.ingest_temperature(temperature)
        decision = model.infer(
            AccelerationFrame(
                origin=origin,
                x=250.0 + (sequence % 7),
                y=245.0 + (sequence % 11),
                z=255.0 + (sequence % 13),
            ),
            origin,
        )
        if decision is None:
            raise RuntimeError("local model did not return a decision")

    for sequence in range(settings.warmup_samples + 5):
        infer(sequence)
    return infer


class Server1Inferer:
    def __init__(
        self, base_url: str, run_index: int, expected_model_version: str
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_index = run_index
        self.expected_model_version = expected_model_version
        self.client = httpx.Client(timeout=5.0)

    def __call__(self, sequence: int) -> None:
        origin = _origin(self.run_index, sequence)
        response = self.client.post(
            f"{self.base_url}/api/v1/inference",
            json={
                "apiVersion": "v1",
                "requestId": f"augmentation-experiment-{self.run_index}-{sequence}",
                "inputContract": "okdong.pump-motor.telemetry/v1",
                "frame": {
                    "origin": origin,
                    "x": 250.0 + (sequence % 7),
                    "y": 245.0 + (sequence % 11),
                    "z": 255.0 + (sequence % 13),
                },
                "temperature": {
                    "origin": origin,
                    "value": 280.0 + (sequence % 5),
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("requestId") != f"augmentation-experiment-{self.run_index}-{sequence}":
            raise RuntimeError("Server1 returned a mismatched requestId")
        if payload.get("modelVersion") != self.expected_model_version:
            raise RuntimeError("Server1 returned an unexpected modelVersion")

    def close(self) -> None:
        self.client.close()


def service_status() -> dict:
    try:
        response = httpx.get("http://127.0.0.1:8080/api/v1/status", timeout=3.0)
        response.raise_for_status()
        payload = response.json()
        return {
            "input_state": payload.get("inputState"),
            "model_state": payload.get("modelState"),
            "processing_latency_p95_ms": (payload.get("performance") or {}).get(
                "processingLatencyP95Ms"
            ),
            "backlog": (payload.get("performance") or {}).get("backlog"),
            "throughput_per_second": (payload.get("performance") or {}).get(
                "throughputPerSecond"
            ),
            "process_cpu_cores": (payload.get("processResources") or {}).get(
                "cpuCores"
            ),
            "process_memory_rss_mib": (payload.get("processResources") or {}).get(
                "memoryRssMib"
            ),
        }
    except Exception as exc:  # status evidence must not abort the experiment
        return {"error": exc.__class__.__name__}


def run_condition(
    *,
    method: str,
    background_cpu_ratio: float,
    memory_load_mib: int,
    duration_seconds: float,
    target_rps: float,
    run_index: int,
    server_url: str,
    candidate_model_version: str,
) -> dict:
    quota_cores = cgroup_cpu_limit_cores()
    inferer: Callable[[int], None]
    server_inferer: Server1Inferer | None = None
    if method == "local":
        inferer = local_inferer(run_index)
    else:
        server_inferer = Server1Inferer(
            server_url, run_index, candidate_model_version
        )
        inferer = server_inferer

    latencies: list[float] = []
    schedule_lag: list[float] = []
    errors: list[str] = []
    memory_peak = 0
    started_cgroup = cgroup_snapshot()
    service_before = service_status()
    interval = 1.0 / target_rps
    sequence = 10_000
    try:
        with MemoryPressure(memory_load_mib), CpuPressure(
            background_cpu_ratio, quota_cores
        ):
            started = time.monotonic()
            next_start = started
            while time.monotonic() - started < duration_seconds:
                now = time.monotonic()
                if now < next_start:
                    time.sleep(next_start - now)
                actual_start = time.monotonic()
                schedule_lag.append(max(0.0, (actual_start - next_start) * 1000))
                request_started = time.perf_counter()
                try:
                    inferer(sequence)
                except Exception as exc:
                    errors.append(exc.__class__.__name__)
                latencies.append((time.perf_counter() - request_started) * 1000)
                memory_peak = max(memory_peak, cgroup_snapshot().memory_current_bytes)
                sequence += 1
                next_start += interval
            finished = time.monotonic()
    finally:
        if server_inferer is not None:
            server_inferer.close()

    finished_cgroup = cgroup_snapshot()
    service_after = service_status()
    wall_seconds = max(finished - started, 1e-9)
    cpu_cores_used = (
        (finished_cgroup.usage_usec - started_cgroup.usage_usec)
        / 1_000_000
        / wall_seconds
    )
    completed = len(latencies) - len(errors)
    return {
        "run_index": run_index,
        "method": method,
        "background_cpu_ratio": background_cpu_ratio,
        "memory_load_mib": memory_load_mib,
        "target_rps": target_rps,
        "duration_seconds": round(wall_seconds, 6),
        "request_count": len(latencies),
        "completed_count": completed,
        "error_count": len(errors),
        "error_types": sorted(set(errors)),
        "throughput_per_second": round(completed / wall_seconds, 6),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 6) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 6),
            "p95": round(percentile(latencies, 0.95), 6),
            "p99": round(percentile(latencies, 0.99), 6),
            "max": round(max(latencies), 6) if latencies else 0.0,
        },
        "schedule_lag_ms": {
            "p95": round(percentile(schedule_lag, 0.95), 6),
            "max": round(max(schedule_lag), 6) if schedule_lag else 0.0,
        },
        "resource": {
            "cpu_limit_cores": quota_cores,
            "cpu_cores_used": round(cpu_cores_used, 6),
            "cpu_saturation_ratio": round(cpu_cores_used / quota_cores, 6),
            "throttled_seconds": round(
                (finished_cgroup.throttled_usec - started_cgroup.throttled_usec)
                / 1_000_000,
                6,
            ),
            "nr_throttled": (
                finished_cgroup.nr_throttled - started_cgroup.nr_throttled
            ),
            "memory_start_mib": round(
                started_cgroup.memory_current_bytes / 1024 / 1024, 3
            ),
            "memory_peak_mib": round(memory_peak / 1024 / 1024, 3),
            "memory_end_mib": round(
                finished_cgroup.memory_current_bytes / 1024 / 1024, 3
            ),
            "oom_events": (
                finished_cgroup.memory_events_oom
                - started_cgroup.memory_events_oom
            ),
            "oom_kill_events": (
                finished_cgroup.memory_events_oom_kill
                - started_cgroup.memory_events_oom_kill
            ),
        },
        "service_before": service_before,
        "service_after": service_after,
    }


def build_schedule(
    cpu_ratios: list[float],
    memory_loads_mib: list[int],
    repetitions: int,
    seed: int,
) -> list[tuple[float, int, str]]:
    randomizer = random.Random(seed)
    schedule: list[tuple[float, int, str]] = []
    for repetition in range(repetitions):
        levels = [
            (ratio, memory_load_mib)
            for ratio in cpu_ratios
            for memory_load_mib in memory_loads_mib
        ]
        randomizer.shuffle(levels)
        for ratio, memory_load_mib in levels:
            methods = ["local", "server1"]
            randomizer.shuffle(methods)
            schedule.extend(
                (ratio, memory_load_mib, method) for method in methods
            )
    return schedule


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu-ratios", default="0,0.25,0.5,0.75,1")
    parser.add_argument("--memory-loads-mib", default="0")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--duration-seconds", type=float, default=10)
    parser.add_argument("--target-rps", type=float, default=1)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--washout-seconds", type=float, default=2)
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument(
        "--candidate-model-version", default=DEFAULT_CANDIDATE_MODEL_VERSION
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.repetitions < 1 or args.duration_seconds <= 0 or args.target_rps <= 0:
        parser.error("repetitions, duration-seconds and target-rps must be positive")
    args.cpu_ratios = [float(value) for value in args.cpu_ratios.split(",")]
    args.memory_loads_mib = [
        int(value) for value in args.memory_loads_mib.split(",")
    ]
    if not args.cpu_ratios or any(value < 0 or value > 1 for value in args.cpu_ratios):
        parser.error("cpu-ratios must contain values between 0 and 1")
    if not args.memory_loads_mib or any(
        value < 0 or value > 80 for value in args.memory_loads_mib
    ):
        parser.error("memory-loads-mib must contain values between 0 and 80")
    return args


def main() -> None:
    args = parse_args()
    schedule = build_schedule(
        args.cpu_ratios,
        args.memory_loads_mib,
        args.repetitions,
        args.seed,
    )
    document = {
        "schema_version": "sensor-augmentation-experiment/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "experimental_unit": "one timed run in the live sensor container cgroup",
            "block": "repetition and background CPU ratio",
            "treatments": ["local", "server1"],
            "randomization_seed": args.seed,
            "cpu_ratios": args.cpu_ratios,
            "memory_loads_mib": args.memory_loads_mib,
            "repetitions": args.repetitions,
            "duration_seconds": args.duration_seconds,
            "target_rps": args.target_rps,
            "washout_seconds": args.washout_seconds,
            "schedule": [
                {
                    "background_cpu_ratio": ratio,
                    "memory_load_mib": memory_load_mib,
                    "method": method,
                }
                for ratio, memory_load_mib, method in schedule
            ],
        },
        "environment": {
            "pod": os.getenv("HOSTNAME", "unknown"),
            "cpu_limit_cores": cgroup_cpu_limit_cores(),
            "server_url": args.server_url,
            "source_model_version": DEFAULT_SOURCE_MODEL_VERSION,
            "candidate_model_version": args.candidate_model_version,
        },
        "runs": [],
    }
    total = len(schedule)
    for index, (ratio, memory_load_mib, method) in enumerate(schedule, start=1):
        print(
            f"run {index}/{total}: method={method} "
            f"background_cpu_ratio={ratio} memory_load_mib={memory_load_mib}",
            flush=True,
        )
        document["runs"].append(
            run_condition(
                method=method,
                background_cpu_ratio=ratio,
                memory_load_mib=memory_load_mib,
                duration_seconds=args.duration_seconds,
                target_rps=args.target_rps,
                run_index=index,
                server_url=args.server_url,
                candidate_model_version=args.candidate_model_version,
            )
        )
        if index < total and args.washout_seconds > 0:
            time.sleep(args.washout_seconds)
    document["completed_at"] = datetime.now(timezone.utc).isoformat()
    output = json.dumps(document, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output, flush=True)


if __name__ == "__main__":
    main()
