#!/usr/bin/env python3
"""Summarize sensor augmentation experiment JSON without optional dependencies."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


LATENCY_IMPROVEMENT_MARGIN = 0.10
THROUGHPUT_NONINFERIORITY_MARGIN = 0.05


def median(values: list[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def repetition_index(run: dict, document: dict) -> int:
    runs_per_repetition = len(document["runs"]) // document["design"]["repetitions"]
    return (run["run_index"] - 1) // runs_per_repetition + 1


def exact_two_sided_sign_test_p(wins: int, losses: int) -> float:
    """Return the exact two-sided binomial sign-test p-value, ignoring ties."""
    observations = wins + losses
    if observations == 0:
        return 1.0
    tail = min(wins, losses)
    probability = 2 * sum(
        math.comb(observations, index) for index in range(tail + 1)
    ) / (2**observations)
    return round(min(1.0, probability), 15)


def summarize_document(document: dict, source: str) -> dict:
    grouped: dict[tuple[float, int, str], list[dict]] = defaultdict(list)
    for run in document["runs"]:
        grouped[
            (
                float(run["background_cpu_ratio"]),
                int(run.get("memory_load_mib", 0)),
                run["method"],
            )
        ].append(run)

    groups = []
    groups_by_condition: dict[tuple[float, int], dict[str, dict]] = defaultdict(dict)
    for (cpu_ratio, memory_mib, method), runs in sorted(grouped.items()):
        group = {
            "background_cpu_ratio": cpu_ratio,
            "memory_load_mib": memory_mib,
            "method": method,
            "n": len(runs),
            "latency_p95_ms_median": median(
                [run["latency_ms"]["p95"] for run in runs]
            ),
            "latency_p95_ms_range": [
                round(min(run["latency_ms"]["p95"] for run in runs), 6),
                round(max(run["latency_ms"]["p95"] for run in runs), 6),
            ],
            "throughput_per_second_median": median(
                [run["throughput_per_second"] for run in runs]
            ),
            "schedule_lag_p95_ms_median": median(
                [run["schedule_lag_ms"]["p95"] for run in runs]
            ),
            "cpu_saturation_ratio_median": median(
                [run["resource"]["cpu_saturation_ratio"] for run in runs]
            ),
            "throttled_seconds_median": median(
                [run["resource"]["throttled_seconds"] for run in runs]
            ),
            "memory_peak_mib_median": median(
                [run["resource"]["memory_peak_mib"] for run in runs]
            ),
            "errors": sum(run["error_count"] for run in runs),
            "oom_events": sum(
                run["resource"]["oom_events"] for run in runs
            ),
        }
        groups.append(group)
        groups_by_condition[(cpu_ratio, memory_mib)][method] = group

    condition_comparisons = []
    for (cpu_ratio, memory_mib), methods in sorted(groups_by_condition.items()):
        if set(methods) != {"local", "server1"}:
            continue
        local = methods["local"]
        server = methods["server1"]
        latency_ratio = (
            server["latency_p95_ms_median"] / local["latency_p95_ms_median"]
        )
        throughput_ratio = (
            server["throughput_per_second_median"]
            / local["throughput_per_second_median"]
        )
        reliability_passed = bool(
            local["errors"] == 0
            and server["errors"] == 0
            and local["oom_events"] == 0
            and server["oom_events"] == 0
        )
        latency_margin_passed = bool(
            latency_ratio <= 1 - LATENCY_IMPROVEMENT_MARGIN
        )
        throughput_margin_passed = bool(
            throughput_ratio >= 1 - THROUGHPUT_NONINFERIORITY_MARGIN
        )
        condition_comparisons.append(
            {
                "background_cpu_ratio": cpu_ratio,
                "memory_load_mib": memory_mib,
                "server_to_local_p95_ratio": round(latency_ratio, 6),
                "server_to_local_throughput_ratio": round(throughput_ratio, 6),
                "latency_margin_passed": latency_margin_passed,
                "throughput_margin_passed": throughput_margin_passed,
                "reliability_passed": reliability_passed,
                "qualification_passed": bool(
                    latency_margin_passed
                    and throughput_margin_passed
                    and reliability_passed
                ),
            }
        )

    pairs: dict[tuple[int, float, int], dict[str, dict]] = defaultdict(dict)
    for run in document["runs"]:
        key = (
            repetition_index(run, document),
            float(run["background_cpu_ratio"]),
            int(run.get("memory_load_mib", 0)),
        )
        pairs[key][run["method"]] = run
    pair_rows = []
    for (repetition, cpu_ratio, memory_mib), methods in sorted(pairs.items()):
        if set(methods) != {"local", "server1"}:
            continue
        local = methods["local"]
        server = methods["server1"]
        local_p95 = local["latency_ms"]["p95"]
        server_p95 = server["latency_ms"]["p95"]
        pair_rows.append(
            {
                "repetition": repetition,
                "background_cpu_ratio": cpu_ratio,
                "memory_load_mib": memory_mib,
                "server_minus_local_p95_ms": round(server_p95 - local_p95, 6),
                "server_to_local_p95_ratio": round(server_p95 / local_p95, 6),
                "server_to_local_throughput_ratio": round(
                    server["throughput_per_second"]
                    / local["throughput_per_second"],
                    6,
                ),
                "server_latency_win": server_p95 < local_p95,
                "server_throughput_win": (
                    server["throughput_per_second"]
                    > local["throughput_per_second"]
                ),
            }
        )

    latency_wins = sum(row["server_latency_win"] for row in pair_rows)
    throughput_wins = sum(row["server_throughput_win"] for row in pair_rows)
    return {
        "source": source,
        "target_rps": document["design"]["target_rps"],
        "run_count": len(document["runs"]),
        "pair_count": len(pair_rows),
        "groups": groups,
        "condition_comparisons": condition_comparisons,
        "paired_comparisons": pair_rows,
        "server_latency_wins": latency_wins,
        "server_throughput_wins": throughput_wins,
        "latency_sign_test_two_sided_p": exact_two_sided_sign_test_p(
            latency_wins, len(pair_rows) - latency_wins
        ),
        "throughput_sign_test_two_sided_p": exact_two_sided_sign_test_p(
            throughput_wins, len(pair_rows) - throughput_wins
        ),
        "qualified_condition_count": sum(
            item["qualification_passed"] for item in condition_comparisons
        ),
        "errors": sum(run["error_count"] for run in document["runs"]),
        "oom_events": sum(
            run["resource"]["oom_events"] for run in document["runs"]
        ),
    }


def summarize(paths: list[Path]) -> dict:
    experiments = []
    skipped_generated_files = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if "runs" not in document:
            if str(document.get("schema_version", "")).startswith(
                "sensor-augmentation-analysis/"
            ):
                skipped_generated_files.append(path.name)
                continue
            raise ValueError(f"{path}: experiment JSON must contain runs")
        experiments.append(summarize_document(document, path.name))
    if not experiments:
        raise ValueError("no experiment JSON inputs were provided")

    pair_count = sum(item["pair_count"] for item in experiments)
    latency_wins = sum(item["server_latency_wins"] for item in experiments)
    throughput_wins = sum(item["server_throughput_wins"] for item in experiments)
    qualified_condition_count = sum(
        item["qualified_condition_count"] for item in experiments
    )
    validated_condition_count = sum(
        len(item["condition_comparisons"]) for item in experiments
    )
    return {
        "schema_version": "sensor-augmentation-analysis/v2",
        "qualification_rule": {
            "latency_p95_improvement_percent": int(
                LATENCY_IMPROVEMENT_MARGIN * 100
            ),
            "throughput_noninferiority_percent": int(
                THROUGHPUT_NONINFERIORITY_MARGIN * 100
            ),
            "requires_zero_errors_and_oom": True,
            "application": "future_candidate_promotion_gate",
        },
        "experiment_count": len(experiments),
        "run_count": sum(item["run_count"] for item in experiments),
        "pair_count": pair_count,
        "server_latency_wins": latency_wins,
        "server_throughput_wins": throughput_wins,
        "latency_sign_test_two_sided_p": exact_two_sided_sign_test_p(
            latency_wins, pair_count - latency_wins
        ),
        "throughput_sign_test_two_sided_p": exact_two_sided_sign_test_p(
            throughput_wins, pair_count - throughput_wins
        ),
        "qualified_condition_count": qualified_condition_count,
        "validated_condition_count": validated_condition_count,
        "candidate_qualified": bool(
            validated_condition_count > 0
            and qualified_condition_count == validated_condition_count
        ),
        "errors": sum(item["errors"] for item in experiments),
        "oom_events": sum(item["oom_events"] for item in experiments),
        "skipped_generated_files": skipped_generated_files,
        "experiments": experiments,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.paths)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
