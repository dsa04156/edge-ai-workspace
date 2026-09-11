"""Descriptive figures with all C1 observations; no inferred confidence intervals."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

NAMES = {"nano": "Orin Nano", "agx": "AGX Orin", "spark": "DGX Spark (GB10)"}
COLORS = {"nano": "#0072B2", "agx": "#9B4F00", "spark": "#7030A0"}
MARKERS = {"nano": "o", "agx": "s", "spark": "^"}


def plot(root):
    result = json.loads((root / "comparison.json").read_text())
    models = sorted(json.loads((root / "models.json").read_text()), key=lambda m: m["size_bytes"])
    labels = [m["model"].replace(":", " ").replace("-instruct-q8_0", "").replace("llama3.2", "Llama 3.2").replace("qwen2.5", "Qwen 2.5").replace("gemma2", "Gemma 2") for m in models]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    fig.subplots_adjust(left=.065, right=.98, bottom=.21, top=.84, wspace=.22)
    for axis, case, metric, title in [(axes[0], "i512-o128-c1", "p50_latency_ms", "One request: median and all 3 observations"),
                                      (axes[1], "i512-o128-c8", "p95_latency_ms", "8 simultaneous requests: pooled sample p95 (n=24)")]:
        for ni, (node, name) in enumerate(NAMES.items()):
            vals = []
            for mi, model in enumerate(models):
                rows = [r for r in result["conditions"] if r["node"] == node and r["model"] == model["model"] and r["case"] == case]
                value = rows[0][metric]/1000 if len(rows) == 1 and rows[0]["blocks"] == 3 else np.nan
                vals.append(value)
                if case == "i512-o128-c1" and len(rows) == 1 and rows[0]["blocks"] == 3:
                    for block in range(3):
                        cell = next(c for c in result["cells"] if c["node"] == node and c["model"] == model["model"] and c["block"] == block)
                        file = root / cell["path"] / "workload/requests.jsonl"
                        if file.exists():
                            requests = [json.loads(line) for line in file.read_text().splitlines()]
                            for r in requests:
                                if r.get("case") == case and r["status"] == "ok":
                                    axis.scatter(mi + (ni-1)*.19, r["latency_ms"]/1000, s=65, marker=MARKERS[node],
                                                 facecolors="none", edgecolors=COLORS[node], linewidths=1, zorder=3)
            axis.scatter(np.arange(len(models))+(ni-1)*.19, vals, color=COLORS[node], marker=MARKERS[node], s=28, label=name, zorder=4)
        axis.set_xticks(range(len(models)), labels, rotation=25, ha="right")
        axis.set_ylim(bottom=0)
        axis.set_ylabel("Response latency (seconds; lower is faster)")
        axis.set_title(title, fontsize=11)
        axis.grid(axis="y", color="#dddddd", linewidth=.6)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False)
    incomplete = any(not c["complete"] for c in result["cells"])
    prefix = "PARTIAL · " if incomplete else ""
    fig.suptitle(prefix + "Six Q8_0 models on three physical GPUs · 512 input / 128 output tokens", fontsize=14, y=.98)
    fig.supxlabel("Within-session screening, slot=1: queueing included; model loading excluded. No quality or saturation claim.", fontsize=10, y=.015)
    for suffix in ["png", "svg"]:
        fig.savefig(root / ("model-comparison." + suffix), dpi=180, facecolor="white")
    plt.close(fig)
    (root / "figure-provenance.json").write_text(json.dumps({"source": "comparison.json",
        "source_sha256": hashlib.sha256((root / "comparison.json").read_bytes()).hexdigest(),
        "matplotlib": matplotlib.__version__, "numpy": np.__version__, "figure_inches": [13, 6],
        "dpi": 180, "estimator": "C1 median with all observations; C8 pooled linear-interpolation p95",
        "missing": "gaps, never zero; incomplete three-block groups omitted", "confidence_intervals": "none; three blocks only",
        "audience": "project experiment report", "publisher": "not a journal submission"}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    a = p.parse_args()
    plot(a.root)
