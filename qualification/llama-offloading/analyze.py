"""Aggregate per-request CSVs into the requested comparison table."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from pathlib import Path
import statistics

TIERS = ("nano", "agx", "spark")


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("status") == "ok"]


def stage_duration(rows: list[dict[str, str]]) -> float:
    timestamps = [float(row["timestamp"]) for row in rows]
    completed = [float(row.get("completed_timestamp") or row["timestamp"]) for row in rows]
    return max(completed) - min(timestamps) if rows else 0.0


def summarize_rows(rows: list[dict[str, str]], scenario: str, concurrency: int | None = None) -> dict:
    latency = [float(row["actual_e2e_ms"]) for row in rows]
    ttft = [float(row["ttft_ms"]) for row in rows]
    tps = [float(row["tokens_per_second"]) for row in rows]
    counts = Counter(row["selected_node"] for row in rows)
    ordered = sorted(rows, key=lambda row: float(row["timestamp"]))
    transitions = sum(
        1
        for previous, current in zip(ordered, ordered[1:])
        if TIERS.index(current["selected_node"]) > TIERS.index(previous["selected_node"])
    )
    offloaded_requests = sum(1 for row in rows if row["selected_node"] != "nano")
    if concurrency is None:
        grouped = {
            value: [row for row in rows if int(row["concurrency"]) == value]
            for value in sorted({int(row["concurrency"]) for row in rows})
        }
        duration = sum(stage_duration(group) for group in grouped.values())
    else:
        duration = stage_duration(rows)
    result = {
        "scenario": scenario,
        "requests": len(rows),
        "mean_latency_ms": statistics.fmean(latency) if latency else 0.0,
        "p95_latency_ms": percentile(latency, 0.95),
        "mean_ttft_ms": statistics.fmean(ttft) if ttft else 0.0,
        "p95_ttft_ms": percentile(ttft, 0.95),
        "mean_tokens_per_second": statistics.fmean(tps) if tps else 0.0,
        "throughput_requests_per_second": len(rows) / duration if duration > 0 else 0.0,
        "offloading_transitions": transitions,
        "offloaded_requests": offloaded_requests,
        "nano_requests": counts["nano"],
        "agx_requests": counts["agx"],
        "spark_requests": counts["spark"],
    }
    if concurrency is not None:
        result = {"scenario": scenario, "concurrency": concurrency, **{key: value for key, value in result.items() if key != "scenario"}}
    return result


def summarize(path: Path) -> tuple[dict, list[dict]]:
    rows = read_rows(path)
    scenario = rows[0]["scenario"] if rows else path.stem
    overall = summarize_rows(rows, scenario)
    details = [
        summarize_rows(
            [row for row in rows if int(row["concurrency"]) == concurrency],
            scenario,
            concurrency,
        )
        for concurrency in sorted({int(row["concurrency"]) for row in rows})
    ]
    return overall, details


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["scenario"])
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, title: str, rows: list[dict]) -> None:
    headers = list(rows[0]) if rows else ["scenario"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(f"{row[key]:.3f}" if isinstance(row[key], float) else str(row[key]) for key in headers) + " |")
    path.write_text(f"# {title}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--detail-csv-output", type=Path)
    parser.add_argument("--detail-markdown-output", type=Path)
    args = parser.parse_args()
    aggregated = [summarize(path) for path in args.inputs]
    summaries = [item[0] for item in aggregated]
    details = [row for item in aggregated for row in item[1]]
    baseline = next((row for row in summaries if row["scenario"] == "nano_only"), None)
    for row in summaries:
        row["latency_improvement_percent_vs_nano"] = (
            100.0 * (baseline["mean_latency_ms"] - row["mean_latency_ms"]) / baseline["mean_latency_ms"]
            if baseline and baseline["mean_latency_ms"] > 0 else 0.0
        )
    write_csv(args.csv_output, summaries)
    write_markdown(args.markdown_output, "Llama offloading comparison", summaries)
    if args.detail_csv_output:
        write_csv(args.detail_csv_output, details)
    if args.detail_markdown_output:
        write_markdown(args.detail_markdown_output, "Llama offloading comparison by concurrency", details)


if __name__ == "__main__":
    main()
