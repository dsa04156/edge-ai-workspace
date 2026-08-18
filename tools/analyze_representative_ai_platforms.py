#!/usr/bin/env python3
"""Summarize paired edge-local versus Server1 benchmark runs by edge platform."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def exact_two_sided_sign_pvalue(wins: int, trials: int) -> float:
    tail = sum(math.comb(trials, value) for value in range(0, min(wins, trials - wins) + 1))
    return min(1.0, 2 * tail / (2**trials))


def summarize(documents: list[dict]) -> dict:
    conditions: list[dict] = []
    platform_pairs: dict[str, list[dict]] = defaultdict(list)
    profile_pairs: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for document in documents:
        site = document["execution"]["site"]
        grouped: dict[tuple[int, float], dict[str, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for run in document["runs"]:
            grouped[(run["width"], run["background_cpu_ratio"])][run["method"]].append(run)
        for (width, cpu_ratio), methods in sorted(grouped.items()):
            local_by_repetition = {run["repetition"]: run for run in methods["local"]}
            server_by_repetition = {run["repetition"]: run for run in methods["server1"]}
            pairs = []
            for repetition in sorted(set(local_by_repetition) & set(server_by_repetition)):
                local = local_by_repetition[repetition]
                server = server_by_repetition[repetition]
                local_p95 = local["latency_ms"]["p95"]
                server_p95 = server["latency_ms"]["p95"]
                pairs.append(
                    {
                        "latency_win": server_p95 < local_p95,
                        "qualified": server_p95 <= local_p95 * 0.90
                        and server["throughput_per_second"] >= local["throughput_per_second"] * 0.95,
                        "latency_reduction_ratio": (local_p95 - server_p95) / local_p95,
                        "throughput_ratio": server["throughput_per_second"] / local["throughput_per_second"],
                    }
                )
            platform_pairs[site].extend(pairs)
            profile_pairs[(site, width)].extend(pairs)
            local_p95 = statistics.median(run["latency_ms"]["p95"] for run in methods["local"])
            server_p95 = statistics.median(run["latency_ms"]["p95"] for run in methods["server1"])
            local_throughput = statistics.median(run["throughput_per_second"] for run in methods["local"])
            server_throughput = statistics.median(run["throughput_per_second"] for run in methods["server1"])
            conditions.append(
                {
                    "site": site,
                    "node_name": document["execution"]["node_name"],
                    "width": width,
                    "operations_per_inference": 9 * document["model"]["depth"] * width,
                    "background_cpu_ratio": cpu_ratio,
                    "local_p95_ms": round(local_p95, 6),
                    "server1_p95_ms": round(server_p95, 6),
                    "local_throughput_per_second": round(local_throughput, 6),
                    "server1_throughput_per_second": round(server_throughput, 6),
                    "local_cpu_saturation_ratio": round(
                        statistics.median(run["resource"]["cpu_saturation_ratio"] for run in methods["local"]),
                        6,
                    ),
                    "local_throttled_seconds": round(
                        statistics.median(run["resource"]["throttled_seconds"] for run in methods["local"]),
                        6,
                    ),
                    "condition_qualified": server_p95 <= local_p95 * 0.90
                    and server_throughput >= local_throughput * 0.95,
                }
            )
    platforms = {}
    for site, pairs in sorted(platform_pairs.items()):
        wins = sum(pair["latency_win"] for pair in pairs)
        platforms[site] = {
            "paired_runs": len(pairs),
            "server1_latency_wins": wins,
            "qualified_pairs": sum(pair["qualified"] for pair in pairs),
            "sign_test_two_sided_p": exact_two_sided_sign_pvalue(wins, len(pairs)),
            "median_latency_reduction_ratio": statistics.median(
                pair["latency_reduction_ratio"] for pair in pairs
            ),
            "median_throughput_ratio": statistics.median(
                pair["throughput_ratio"] for pair in pairs
            ),
        }
    profiles = {}
    for (site, width), pairs in sorted(profile_pairs.items()):
        wins = sum(pair["latency_win"] for pair in pairs)
        profiles[f"{site}:{width}"] = {
            "site": site,
            "width": width,
            "operations_per_inference": 9 * documents[0]["model"]["depth"] * width,
            "paired_runs": len(pairs),
            "server1_latency_wins": wins,
            "qualified_pairs": sum(pair["qualified"] for pair in pairs),
            "sign_test_two_sided_p": exact_two_sided_sign_pvalue(wins, len(pairs)),
            "median_latency_reduction_ratio": statistics.median(
                pair["latency_reduction_ratio"] for pair in pairs
            ),
            "median_throughput_ratio": statistics.median(
                pair["throughput_ratio"] for pair in pairs
            ),
        }
    hashes = {document["input_provenance"]["dataset_sha256"] for document in documents}
    if len(hashes) != 1:
        raise ValueError("platform documents do not use the same captured dataset")
    return {
        "schema_version": "representative-ai-platform-comparison/v1",
        "dataset_sha256": hashes.pop(),
        "platforms": platforms,
        "profiles": profiles,
        "conditions": conditions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = summarize(
        [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.inputs]
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
