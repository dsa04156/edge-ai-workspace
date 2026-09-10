"""Descriptive paired-wave analysis; no inferential p-values or validated policy."""
import argparse
import csv
import json
from pathlib import Path
import statistics

import bench


def describe(rows):
    good = [r for r in rows if r["status"] == "ok"]
    per_block = []
    for block in sorted({r["block"] for r in rows}):
        wave = [r for r in rows if r["block"] == block]
        per_block.append({"block": block, **bench.summarize(wave),
                          "duration_s": max(r["completed_at"] for r in wave) - min(r["planned_at"] for r in wave)})
    times = [r["latency_ms"] for r in good]
    ttfts = [r["ttft_ms"] for r in good if r["ttft_ms"] is not None]
    active_s = sum(b["duration_s"] for b in per_block)
    return {"requests": len(rows), "blocks": len(per_block), "successes": len(good),
            "failed": len(rows) - len(good), "mean_latency_ms": statistics.mean(times) if times else None,
            "sd_latency_ms": statistics.stdev(times) if len(times) > 1 else None,
            "p50_latency_ms": bench.percentile(times, .5), "p95_latency_ms": bench.percentile(times, .95),
            "p95_ttft_ms": bench.percentile(ttfts, .95),
            "active_wave_completed_rps": len(good) / active_s if active_s else None,
            "active_wave_output_tokens_s": sum(r["actual_output_tokens"] for r in good) / active_s if active_s else None,
            "blocks_raw": per_block,
            "warning": "Active-wave throughput excludes between-wave idle gaps; not sustained-load capacity. Request SD includes queue-position effects; blocks, not requests, are repeats."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--activation-run", type=Path)
    args = p.parse_args()
    rows = [json.loads(x) for x in (args.run / "requests.jsonl").read_text().splitlines()]
    results = {}
    for c in (1, 2, 4):
        local = describe([r for r in rows if r["concurrency"] == c and r["route"] == "nano"])
        remote = describe([r for r in rows if r["concurrency"] == c and r["route"] == "remote"])
        results[str(c)] = {"nano": local, "remote": remote,
                          "observed_p95_reduction_fraction": 1 - remote["p95_latency_ms"] / local["p95_latency_ms"] if local["p95_latency_ms"] and remote["p95_latency_ms"] is not None else None}
    activation = None
    warmup = None
    if args.activation_run:
        events = [json.loads(x) for x in (args.activation_run / "events.jsonl").read_text().splitlines()]
        activation = next((r["activation_ms"] for r in events if r["event"] == "inference_ready"), None)
        preparation_requests = [json.loads(x) for x in (args.activation_run / "requests.jsonl").read_text().splitlines()]
        warmup = sum(r["latency_ms"] for r in preparation_requests if r["phase"] == "warmup")
    one = results["1"]
    estimate = None
    if activation is not None and one["nano"]["mean_latency_ms"] is not None and one["remote"]["mean_latency_ms"] is not None:
        estimate = one["nano"]["mean_latency_ms"] - activation - (warmup or 0) - one["remote"]["mean_latency_ms"]
    report = {"schema": "edge-ai.llm-paired-observation/v1", "evidence_run": args.run.name,
              "condition": "512 input / 128 output, one slot, same d222767c7 runtime and model, Nano origin, ready remote, three randomized route-order blocks",
              "descriptive": results, "activation_ms_separate_run": activation,
              "warmup_ms_separate_run": warmup,
              "estimated_single_request_gain_ms": estimate,
              "estimate_warning": "Additive native-process estimate, not a measured on-demand first-request trial. Excludes GPU acquisition, Pod/container startup and Nano management RPC. Includes activation probe AND full warmup because paired latency is warmed. Remote latency already includes network; do not add RTT again. Positive native-process gain does not establish positive end-to-end activation gain.",
              "holdout_validated": False, "production_enabled": False,
              "routing_boundary": None, "activation_boundary": None, "reclamation_boundary": None,
              "unmeasured": ["Cold download", "AGX Orin", "DGX Spark", "sustained request-rate saturation", "burst duration crossover", "idle/reload reclamation tradeoff"]}
    (args.run / "comparison.json").write_text(json.dumps(report, indent=2))
    with open(args.run / "requests.csv", "w", newline="") as f:
        fields = sorted(set().union(*(r.keys() for r in rows)))
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    print(json.dumps(report))


if __name__ == "__main__":
    main()
