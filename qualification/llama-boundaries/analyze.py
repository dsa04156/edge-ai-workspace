"""Export raw CSV, descriptive figures, and deliberately non-operational profiles."""
import argparse
import csv
import json
from pathlib import Path
import platform

import bench


def analyze(root):
    rows = [json.loads(line) for line in (root / "requests.jsonl").read_text().splitlines()]
    columns = sorted(set().union(*(set(r) for r in rows)))
    with open(root / "requests.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    groups = {str(c): bench.summarize([r for r in rows if r["concurrency"] == c]) for c in sorted({r["concurrency"] for r in rows})}
    profile = {
        "schema": "edge-ai.llm-observation/v1", "experiment_id": root.name,
        "raw_sha256": bench.digest(root / "requests.jsonl"), "node": rows[0]["selected_node"],
        "requester": rows[0]["requester"], "measurements": groups,
        "condition": {"input_tokens": 512, "output_tokens": 128, "cache_prompt": False, "ignore_eos": True},
        "production_enabled": False, "thresholds_validated": False,
        "routing_boundary": None, "activation_boundary": None, "reclamation_boundary": None,
        "limitations": ["No matched local/remote arrival-trace comparison yet", "No independent repeated blocks or holdout validation", "Single-wave small-n latency quantiles are descriptive", "See provenance.json for runtime differences"],
    }
    (root / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
    x = list(map(int, groups))
    for ax, key, label in zip(axes, ["p95_latency_ms", "p95_ttft_ms", "completed_requests_per_s"], ["p95 latency (ms)", "p95 TTFT (ms)", "Completed requests/s"]):
        ax.scatter(x, [groups[str(c)][key] for c in x], marker="o", color="#0072B2")
        for c in x:
            if groups[str(c)][key] is not None:
                ax.annotate(f"n={groups[str(c)]['n']}", (c, groups[str(c)][key]), xytext=(0, 8), textcoords="offset points", ha="center")
        ax.set(xlabel="Concurrency", ylabel=label, xticks=x)
        observed = [groups[str(c)][key] for c in x if groups[str(c)][key] is not None]
        ax.set_ylim(0, max(observed) * 1.2 if observed and max(observed) > 0 else 1)
    fig.suptitle(f"{root.name}: exploratory observations, NOT an offloading threshold", fontsize=11)
    fig.savefig(root / "concurrency.png", dpi=160)
    plt.close(fig)
    (root / "figure-provenance.json").write_text(json.dumps({
        "raw": "requests.jsonl", "matplotlib": matplotlib.__version__, "python": platform.python_version(),
        "estimator": "linear-interpolated empirical p95 among successful equal-length measurement requests", "uncertainty": "not estimated: insufficient independent repeated blocks",
        "warmup": "excluded from displayed quantiles, retained in raw CSV", "missing": "null, not zero", "smoothing": None,
        "description": "Three scatter panels show latency, first-token delay and throughput by concurrency; each point is labelled with request count. No between-device inference is made."
    }, indent=2))
    print(json.dumps(profile, ensure_ascii=False))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    analyze(p.parse_args().run)
