#!/usr/bin/env python3
"""Run a reproducible local-vs-Server1 inference pressure experiment.

The script is copied into the running sensor-anomaly-demo container and executed
there so the benchmark shares the production container's CPU and memory cgroup.
It never changes the Deployment or the active inference route.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
from typing import Callable, TypedDict

import httpx

REPOSITORY_SERVICE_ROOT = (
    Path(__file__).resolve().parents[1] / "edge-orch" / "sensor-anomaly-demo"
)
for service_root in (Path("/app"), REPOSITORY_SERVICE_ROOT):
    if (service_root / "app" / "config.py").is_file():
        sys.path.insert(0, str(service_root))
        break

from app.config import DEFAULT_LOCAL_DATA_BASE_URL, Settings
from app.local_data import ACCELERATION_SOURCES, TEMPERATURE_SOURCE, LocalDataClient
from app.model_adapter import build_model_adapter
from app.models import AccelerationFrame, AxisSample


CGROUP = Path("/sys/fs/cgroup")
DEFAULT_SERVER_URL = "http://sensor-anomaly-inference-server1:8080"
DEFAULT_SOURCE_MODEL_VERSION = "baseline-1.0.0"
DEFAULT_CANDIDATE_MODEL_VERSION = "cuda-baseline-1.0.0"


class InferenceMeasurement(TypedDict):
    server_processing_ms: float | None
    request_bytes: int
    response_bytes: int


@dataclass(frozen=True)
class ExperimentFrame:
    frame_origin: int
    x: float
    y: float
    z: float
    temperature_origin: int
    temperature: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "frame_origin": self.frame_origin,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "temperature_origin": self.temperature_origin,
            "temperature": self.temperature,
        }


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


async def _fetch_live_sources(
    base_url: str,
    timeout_seconds: float,
    to_origin: int,
) -> dict[str, list[AxisSample]]:
    client = LocalDataClient(base_url, timeout_seconds)
    try:
        sources = (*ACCELERATION_SOURCES, TEMPERATURE_SOURCE)
        rows = await asyncio.gather(
            *(client.fetch(source, None, to_origin) for source in sources)
        )
        return {
            source.key: samples
            for source, samples in zip(sources, rows, strict=True)
        }
    finally:
        await client.close()


def capture_live_frames(
    *,
    base_url: str,
    frame_count: int,
    timeout_seconds: float,
    max_skew_seconds: float,
    max_age_seconds: float,
    now_ns: int | None = None,
) -> tuple[list[ExperimentFrame], dict]:
    captured_at_ns = time.time_ns() if now_ns is None else now_ns
    rows_by_source = asyncio.run(
        _fetch_live_sources(base_url, timeout_seconds, captured_at_ns)
    )
    axis_values = {
        source.axis: {
            row.origin: float(row.value) for row in rows_by_source[source.key]
        }
        for source in ACCELERATION_SOURCES
    }
    common_origins = sorted(
        set(axis_values["x"])
        & set(axis_values["y"])
        & set(axis_values["z"])
    )
    temperatures = rows_by_source[TEMPERATURE_SOURCE.key]
    if not temperatures:
        raise RuntimeError("live Local Data returned no temperature samples")

    maximum_skew_ns = int(max_skew_seconds * 1_000_000_000)
    aligned: list[ExperimentFrame] = []
    for origin in common_origins:
        temperature = min(
            temperatures,
            key=lambda sample: abs(sample.origin - origin),
        )
        if abs(temperature.origin - origin) > maximum_skew_ns:
            continue
        aligned.append(
            ExperimentFrame(
                frame_origin=origin,
                x=axis_values["x"][origin],
                y=axis_values["y"][origin],
                z=axis_values["z"][origin],
                temperature_origin=temperature.origin,
                temperature=float(temperature.value),
            )
        )
    if len(aligned) < frame_count:
        raise RuntimeError(
            f"live Local Data provided {len(aligned)} aligned frames; "
            f"{frame_count} required"
        )
    frames = aligned[-frame_count:]
    latest_age_seconds = (captured_at_ns - frames[-1].frame_origin) / 1_000_000_000
    if latest_age_seconds < 0 or latest_age_seconds > max_age_seconds:
        raise RuntimeError(
            f"latest live frame age {latest_age_seconds:.3f}s exceeds "
            f"the {max_age_seconds:.3f}s capture limit"
        )

    encoded = json.dumps(
        [frame.as_dict() for frame in frames],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    skew_ms = [
        abs(frame.frame_origin - frame.temperature_origin) / 1_000_000
        for frame in frames
    ]
    values = {
        "x": [frame.x for frame in frames],
        "y": [frame.y for frame in frames],
        "z": [frame.z for frame in frames],
        "temperature": [frame.temperature for frame in frames],
    }
    provenance = {
        "mode": "live-local-data-capture-replay",
        "physical_source": "arduino-001",
        "device_service": "device-serial-jetson",
        "local_data_api": "v3",
        "captured_at": datetime.fromtimestamp(
            captured_at_ns / 1_000_000_000, timezone.utc
        ).isoformat(),
        "frame_count": len(frames),
        "first_frame_origin": frames[0].frame_origin,
        "last_frame_origin": frames[-1].frame_origin,
        "latest_frame_age_seconds": round(latest_age_seconds, 6),
        "dataset_sha256": hashlib.sha256(encoded).hexdigest(),
        "source_sample_counts": {
            key: len(rows) for key, rows in rows_by_source.items()
        },
        "temperature_alignment_lag_ms": {
            "p50": round(percentile(skew_ms, 0.50), 6),
            "p95": round(percentile(skew_ms, 0.95), 6),
            "max": round(max(skew_ms), 6),
        },
        "value_ranges": {
            key: {"min": min(rows), "max": max(rows)}
            for key, rows in values.items()
        },
        "frames": [frame.as_dict() for frame in frames],
    }
    return frames, provenance


def synthetic_frames(frame_count: int) -> list[ExperimentFrame]:
    return [
        ExperimentFrame(
            frame_origin=_origin(0, sequence),
            x=250.0 + (sequence % 7),
            y=245.0 + (sequence % 11),
            z=255.0 + (sequence % 13),
            temperature_origin=_origin(0, sequence),
            temperature=280.0 + (sequence % 5),
        )
        for sequence in range(frame_count)
    ]


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


def _selected_frame(frames: list[ExperimentFrame], sequence: int) -> ExperimentFrame:
    return frames[sequence % len(frames)]


def local_inferer(
    frames: list[ExperimentFrame],
) -> Callable[[int], InferenceMeasurement]:
    settings = Settings.from_env().model_copy(
        update={
            "service_role": "edge-worker",
            "model_backend": "online-baseline",
            "model_version": DEFAULT_SOURCE_MODEL_VERSION,
        }
    )
    model = build_model_adapter(settings)

    def infer(sequence: int) -> InferenceMeasurement:
        captured = _selected_frame(frames, sequence)
        temperature = AxisSample(
            origin=captured.temperature_origin,
            value_type="Float64",
            value=captured.temperature,
        )
        model.ingest_temperature(temperature)
        decision = model.infer(
            AccelerationFrame(
                origin=captured.frame_origin,
                x=captured.x,
                y=captured.y,
                z=captured.z,
            ),
            captured.temperature_origin,
        )
        if decision is None:
            raise RuntimeError("local model did not return a decision")
        return {
            "server_processing_ms": None,
            "request_bytes": 0,
            "response_bytes": 0,
        }

    for sequence in range(settings.warmup_samples + 5):
        infer(sequence)
    return infer


class Server1Inferer:
    def __init__(
        self,
        base_url: str,
        run_index: int,
        expected_model_version: str,
        frames: list[ExperimentFrame],
        request_prefix: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_index = run_index
        self.expected_model_version = expected_model_version
        self.frames = frames
        self.request_prefix = request_prefix
        self.client = httpx.Client(timeout=5.0)

    def __call__(self, sequence: int) -> InferenceMeasurement:
        captured = _selected_frame(self.frames, sequence)
        request_id = f"augmentation-{self.request_prefix}-{self.run_index}-{sequence}"
        request_payload = {
            "apiVersion": "v1",
            "requestId": request_id,
            "inputContract": "okdong.pump-motor.telemetry/v1",
            "frame": {
                "origin": captured.frame_origin,
                "x": captured.x,
                "y": captured.y,
                "z": captured.z,
            },
            "temperature": {
                "origin": captured.temperature_origin,
                "value": captured.temperature,
            },
        }
        request_body = json.dumps(
            request_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self.client.post(
            f"{self.base_url}/api/v1/inference",
            content=request_body,
            headers={"content-type": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("requestId") != request_id:
            raise RuntimeError("Server1 returned a mismatched requestId")
        if payload.get("origin") != captured.frame_origin:
            raise RuntimeError("Server1 returned a mismatched input origin")
        if payload.get("modelVersion") != self.expected_model_version:
            raise RuntimeError("Server1 returned an unexpected modelVersion")
        server_processing_ms = payload.get("serverProcessingMs")
        if server_processing_ms is not None and (
            not isinstance(server_processing_ms, (int, float))
            or server_processing_ms < 0
        ):
            raise RuntimeError("Server1 returned invalid serverProcessingMs")
        return {
            "server_processing_ms": server_processing_ms,
            "request_bytes": len(request_body),
            "response_bytes": len(response.content),
        }

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
    frames: list[ExperimentFrame],
    request_prefix: str,
) -> dict:
    quota_cores = cgroup_cpu_limit_cores()
    inferer: Callable[[int], InferenceMeasurement]
    server_inferer: Server1Inferer | None = None
    if method == "local":
        inferer = local_inferer(frames)
    else:
        server_inferer = Server1Inferer(
            server_url,
            run_index,
            candidate_model_version,
            frames,
            request_prefix,
        )
        inferer = server_inferer

    latencies: list[float] = []
    server_processing_latencies: list[float] = []
    edge_server_overheads: list[float] = []
    request_sizes: list[int] = []
    response_sizes: list[int] = []
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
                measurement: InferenceMeasurement | None = None
                try:
                    measurement = inferer(sequence)
                except Exception as exc:
                    errors.append(exc.__class__.__name__)
                edge_decision_latency_ms = (
                    time.perf_counter() - request_started
                ) * 1_000
                latencies.append(edge_decision_latency_ms)
                if measurement is not None:
                    server_processing_ms = measurement["server_processing_ms"]
                    if server_processing_ms is not None:
                        server_processing_latencies.append(server_processing_ms)
                        edge_server_overheads.append(
                            max(0.0, edge_decision_latency_ms - server_processing_ms)
                        )
                    request_sizes.append(measurement["request_bytes"])
                    response_sizes.append(measurement["response_bytes"])
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
        "input_dataset_sha256": hashlib.sha256(
            json.dumps(
                [frame.as_dict() for frame in frames],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "duration_seconds": round(wall_seconds, 6),
        "request_count": len(latencies),
        "completed_count": completed,
        "error_count": len(errors),
        "error_types": sorted(set(errors)),
        "throughput_per_second": round(completed / wall_seconds, 6),
        "edge_decision_e2e_latency_ms": {
            "mean": round(statistics.fmean(latencies), 6) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 6),
            "p95": round(percentile(latencies, 0.95), 6),
            "p99": round(percentile(latencies, 0.99), 6),
            "max": round(max(latencies), 6) if latencies else 0.0,
        },
        # Backward-compatible alias for v1 analysis artifacts.
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 6) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 6),
            "p95": round(percentile(latencies, 0.95), 6),
            "p99": round(percentile(latencies, 0.99), 6),
            "max": round(max(latencies), 6) if latencies else 0.0,
        },
        "server_processing_ms": {
            "sample_count": len(server_processing_latencies),
            "p50": round(percentile(server_processing_latencies, 0.50), 6),
            "p95": round(percentile(server_processing_latencies, 0.95), 6),
        },
        "edge_server_roundtrip_overhead_ms": {
            "sample_count": len(edge_server_overheads),
            "p50": round(percentile(edge_server_overheads, 0.50), 6),
            "p95": round(percentile(edge_server_overheads, 0.95), 6),
        },
        "http_payload_bytes": {
            "request_mean": round(statistics.fmean(request_sizes), 3)
            if request_sizes
            else 0.0,
            "response_mean": round(statistics.fmean(response_sizes), 3)
            if response_sizes
            else 0.0,
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


def build_rate_schedule(
    target_rates: list[float],
    cpu_ratios: list[float],
    memory_loads_mib: list[int],
    repetitions: int,
    seed: int,
) -> list[tuple[float, float, int, str]]:
    randomizer = random.Random(seed)
    schedule: list[tuple[float, float, int, str]] = []
    for _repetition in range(repetitions):
        levels = [
            (target_rps, ratio, memory_load_mib)
            for target_rps in target_rates
            for ratio in cpu_ratios
            for memory_load_mib in memory_loads_mib
        ]
        randomizer.shuffle(levels)
        for target_rps, ratio, memory_load_mib in levels:
            methods = ["local", "server1"]
            randomizer.shuffle(methods)
            schedule.extend(
                (target_rps, ratio, memory_load_mib, method)
                for method in methods
            )
    return schedule


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-mode",
        choices=("synthetic", "live-local-data"),
        default="synthetic",
    )
    parser.add_argument("--capture-frame-count", type=int, default=120)
    parser.add_argument("--capture-max-age-seconds", type=float, default=10)
    parser.add_argument("--local-data-url", default=DEFAULT_LOCAL_DATA_BASE_URL)
    parser.add_argument("--local-data-timeout-seconds", type=float, default=5)
    parser.add_argument("--cpu-ratios", default="0,0.25,0.5,0.75,1")
    parser.add_argument("--memory-loads-mib", default="0")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--duration-seconds", type=float, default=10)
    parser.add_argument("--target-rps", type=float, default=1)
    parser.add_argument(
        "--target-rates",
        help="comma-separated target rates captured in one randomized block",
    )
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
    if (
        args.capture_frame_count < 2
        or args.capture_max_age_seconds <= 0
        or args.local_data_timeout_seconds <= 0
    ):
        parser.error("capture settings must be positive and frame count at least 2")
    args.cpu_ratios = [float(value) for value in args.cpu_ratios.split(",")]
    args.target_rates = (
        [float(value) for value in args.target_rates.split(",")]
        if args.target_rates
        else [args.target_rps]
    )
    args.memory_loads_mib = [
        int(value) for value in args.memory_loads_mib.split(",")
    ]
    if not args.cpu_ratios or any(value < 0 or value > 1 for value in args.cpu_ratios):
        parser.error("cpu-ratios must contain values between 0 and 1")
    if not args.target_rates or any(value <= 0 for value in args.target_rates):
        parser.error("target-rates must contain positive values")
    if not args.memory_loads_mib or any(
        value < 0 or value > 80 for value in args.memory_loads_mib
    ):
        parser.error("memory-loads-mib must contain values between 0 and 80")
    return args


def main() -> None:
    args = parse_args()
    if args.input_mode == "live-local-data":
        frames, input_provenance = capture_live_frames(
            base_url=args.local_data_url,
            frame_count=args.capture_frame_count,
            timeout_seconds=args.local_data_timeout_seconds,
            max_skew_seconds=Settings.from_env().context_max_skew_seconds,
            max_age_seconds=args.capture_max_age_seconds,
        )
    else:
        frames = synthetic_frames(args.capture_frame_count)
        encoded = json.dumps(
            [frame.as_dict() for frame in frames],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        input_provenance = {
            "mode": "deterministic-synthetic",
            "frame_count": len(frames),
            "dataset_sha256": hashlib.sha256(encoded).hexdigest(),
            "frames": [frame.as_dict() for frame in frames],
        }
    request_prefix = (
        f"{time.time_ns()}-{input_provenance['dataset_sha256'][:12]}"
    )
    schedule = build_rate_schedule(
        args.target_rates,
        args.cpu_ratios,
        args.memory_loads_mib,
        args.repetitions,
        args.seed,
    )
    document = {
        "schema_version": "sensor-augmentation-experiment/v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_provenance": input_provenance,
        "measurement_contract": {
            "origin": "frame_ready_at_edge",
            "endpoint": "decision_available_at_edge",
            "primary_metric": "edge_decision_e2e_latency_ms",
            "common_upstream_excluded": "physical_sensor_to_frame_ready_at_edge",
            "local_path": "edge_input_build_and_local_inference",
            "server1_path": (
                "edge_request_build_and_serialization_network_server_queue_and_"
                "processing_response_network_parse_and_validation"
            ),
            "server_processing_scope": (
                "server_request_fingerprint_lock_wait_and_model_processing; "
                "excludes_http_parse_and_response_serialization"
            ),
            "input_semantics": (
                "captured real sensor frames are fixed before treatment and replayed "
                "identically through both paths"
                if args.input_mode == "live-local-data"
                else "deterministic synthetic frames"
            ),
        },
        "design": {
            "experimental_unit": "one timed run in the live sensor container cgroup",
            "block": "repetition, target request rate and pressure level",
            "treatments": ["local", "server1"],
            "randomization_seed": args.seed,
            "cpu_ratios": args.cpu_ratios,
            "memory_loads_mib": args.memory_loads_mib,
            "repetitions": args.repetitions,
            "duration_seconds": args.duration_seconds,
            "target_rps": (
                args.target_rates[0]
                if len(args.target_rates) == 1
                else args.target_rates
            ),
            "target_rates": args.target_rates,
            "input_mode": args.input_mode,
            "capture_frame_count": len(frames),
            "washout_seconds": args.washout_seconds,
            "schedule": [
                {
                    "background_cpu_ratio": ratio,
                    "memory_load_mib": memory_load_mib,
                    "target_rps": target_rps,
                    "method": method,
                }
                for target_rps, ratio, memory_load_mib, method in schedule
            ],
        },
        "environment": {
            "pod": os.getenv("HOSTNAME", "unknown"),
            "cpu_limit_cores": cgroup_cpu_limit_cores(),
            "server_url": args.server_url,
            "source_model_version": DEFAULT_SOURCE_MODEL_VERSION,
            "candidate_model_version": args.candidate_model_version,
            "request_prefix": request_prefix,
        },
        "runs": [],
    }
    total = len(schedule)
    for index, (target_rps, ratio, memory_load_mib, method) in enumerate(
        schedule, start=1
    ):
        print(
            f"run {index}/{total}: method={method} "
            f"target_rps={target_rps} background_cpu_ratio={ratio} "
            f"memory_load_mib={memory_load_mib}",
            flush=True,
        )
        document["runs"].append(
            run_condition(
                method=method,
                background_cpu_ratio=ratio,
                memory_load_mib=memory_load_mib,
                duration_seconds=args.duration_seconds,
                target_rps=target_rps,
                run_index=index,
                server_url=args.server_url,
                candidate_model_version=args.candidate_model_version,
                frames=frames,
                request_prefix=request_prefix,
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
