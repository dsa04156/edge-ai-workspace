#!/usr/bin/env python3
"""Analyze run-level GPU pressure results without treating requests as replicates."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def exact_two_sided_sign_p(wins: int, losses: int) -> float | None:
    n = wins + losses
    if n == 0:
        return None
    tail = min(wins, losses)
    probability = 2 * sum(math.comb(n, k) for k in range(tail + 1)) / (2**n)
    return min(1.0, probability)


def analyze(document: dict) -> dict:
    baselines = {
        run["repetition"]: run
        for run in document["runs"]
        if run["compute_duty_ratio"] == 0 and run["memory_load_mib"] == 0
    }
    evaluated = []
    for run in document["runs"]:
        baseline = baselines.get(run["repetition"])
        if baseline is None:
            raise ValueError(f"missing baseline for repetition {run['repetition']}")
        baseline_latency = float(baseline["latency_ms"]["p95"])
        baseline_throughput = float(baseline["throughput_per_second"])
        latency_ratio = (
            float(run["latency_ms"]["p95"]) / baseline_latency
            if baseline_latency > 0 and run["latency_ms"]["p95"] > 0
            else 0.0
        )
        throughput_ratio = (
            float(run["throughput_per_second"]) / baseline_throughput
            if baseline_throughput > 0
            else 0.0
        )
        failed = bool(run["allocation_error"] or run["inference_errors"])
        service_degraded = failed or latency_ratio >= 1.20 or throughput_ratio <= 0.95
        gpu_util = float(run["gpu"]["gpu_utilization_percent"]["p95"])
        memory_ratio = float(run["gpu"]["assigned_memory_used_percent"]["p95"])
        resource_pressure = failed or gpu_util >= 85 or memory_ratio >= 85
        evaluated.append(
            {
                **run,
                "latency_ratio_to_matched_baseline": round(latency_ratio, 6),
                "throughput_ratio_to_matched_baseline": round(throughput_ratio, 6),
                "service_degraded": service_degraded,
                "resource_pressure": resource_pressure,
                "resource_shortage_qualified": resource_pressure and service_degraded,
            }
        )
    grouped: dict[tuple[float, int], list[dict]] = defaultdict(list)
    for run in evaluated:
        grouped[(run["compute_duty_ratio"], run["memory_load_mib"])].append(run)
    conditions = []
    for (compute_ratio, memory_mib), runs in sorted(grouped.items()):
        latency_wins = sum(
            run["latency_ratio_to_matched_baseline"] > 1 for run in runs
        )
        latency_losses = sum(
            0 < run["latency_ratio_to_matched_baseline"] < 1 for run in runs
        )
        conditions.append(
            {
                "compute_duty_ratio": compute_ratio,
                "memory_load_mib": memory_mib,
                "runs": len(runs),
                "gpu_utilization_p95_median": median(
                    [run["gpu"]["gpu_utilization_percent"]["p95"] for run in runs]
                ),
                "gpu_utilization_p95_range": [
                    min(run["gpu"]["gpu_utilization_percent"]["p95"] for run in runs),
                    max(run["gpu"]["gpu_utilization_percent"]["p95"] for run in runs),
                ],
                "assigned_memory_used_p95_median": median(
                    [run["gpu"]["assigned_memory_used_percent"]["p95"] for run in runs]
                ),
                "latency_p95_median_ms": median(
                    [run["latency_ms"]["p95"] for run in runs]
                ),
                "latency_ratio_median": median(
                    [run["latency_ratio_to_matched_baseline"] for run in runs]
                ),
                "throughput_median_per_second": median(
                    [run["throughput_per_second"] for run in runs]
                ),
                "throughput_ratio_median": median(
                    [run["throughput_ratio_to_matched_baseline"] for run in runs]
                ),
                "degraded_runs": sum(run["service_degraded"] for run in runs),
                "shortage_qualified_runs": sum(
                    run["resource_shortage_qualified"] for run in runs
                ),
                "allocation_failures": sum(bool(run["allocation_error"]) for run in runs),
                "latency_direction_sign_p": exact_two_sided_sign_p(
                    latency_wins, latency_losses
                ),
            }
        )
    compute_only = [
        condition
        for condition in conditions
        if condition["memory_load_mib"] == 0
        and condition["compute_duty_ratio"] > 0
        and condition["degraded_runs"] == condition["runs"]
    ]
    observed_crossover = min(
        compute_only,
        key=lambda condition: condition["compute_duty_ratio"],
        default=None,
    )
    return {
        "schema_version": "gpu-resource-pressure-analysis/v1",
        "source_generated_at": document["generated_at"],
        "model": document["model"],
        "input_provenance": {
            key: document["input_provenance"].get(key)
            for key in (
                "physical_source",
                "captured_at",
                "frame_count",
                "dataset_sha256",
                "first_frame_origin",
                "last_frame_origin",
            )
        },
        "execution": document["execution"],
        "predeclared_gates": document["design"],
        "observed_compute_crossover": observed_crossover,
        "conditions": conditions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output")
    args = parser.parse_args()
    document = json.loads(Path(args.input).read_text(encoding="utf-8"))
    analysis = analyze(document)
    encoded = json.dumps(analysis, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
