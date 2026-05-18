from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np


METHOD_ORDER = ["static", "always-offload", "threshold", "selective", "runtime"]
SCENARIO_ORDER = ["normal", "mild-burst", "heavy-burst", "sustained-overload"]
METHOD_LABELS = {
    "static": "Static",
    "always-offload": "Always offload",
    "threshold": "Threshold",
    "selective": "Selective",
    "runtime": "Runtime",
}
SCENARIO_LABELS = {
    "normal": "Normal",
    "mild-burst": "Mild burst",
    "heavy-burst": "Heavy burst",
    "sustained-overload": "Sustained overload",
}
COLORS = {
    "static": "#6B7280",
    "always-offload": "#3B82F6",
    "threshold": "#F59E0B",
    "selective": "#10B981",
    "runtime": "#8B5CF6",
}


def load_results(archive_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(archive_dir.glob("*/*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        data["_path"] = str(path)
        results.append(data)
    return results


def result_map(results: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["scenario"], item["method"]): item for item in results}


def setup_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 220,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 14,
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#E5E7EB",
            "grid.linewidth": 0.8,
            "axes.axisbelow": True,
            "legend.frameon": False,
        }
    )


def save(fig: plt.Figure, out_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(out_dir / f"{stem}.png", bbox_inches="tight")
    fig.savefig(out_dir / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def annotate_bars(ax: plt.Axes, bars: Any, fmt: str = "{:.0f}") -> None:
    for bar in bars:
        height = bar.get_height()
        if not np.isfinite(height):
            continue
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            fmt.format(height),
            ha="center",
            va="bottom",
            fontsize=7,
            color="#374151",
            rotation=90,
            label="_nolegend_",
        )


def plot_latency(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    scenarios = [s for s in SCENARIO_ORDER if any((s, m) in results_by_key for m in METHOD_ORDER)]
    x = np.arange(len(scenarios))
    width = 0.15

    fig, ax = plt.subplots(figsize=(12, 6))
    for idx, method in enumerate(METHOD_ORDER):
        values = [
            results_by_key.get((scenario, method), {}).get("summary", {}).get("e2e_latency_p95_ms", np.nan)
            for scenario in scenarios
        ]
        offset = (idx - (len(METHOD_ORDER) - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            values,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        annotate_bars(ax, bars)

    ax.set_title("End-to-End p95 Latency by Scenario")
    ax.set_ylabel("Latency (ms), lower is better")
    ax.set_xticks(x)
    ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios])
    ax.legend(ncols=5, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    save(fig, out_dir, "01_e2e_p95_latency")


def plot_throughput(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    scenarios = [s for s in SCENARIO_ORDER if any((s, m) in results_by_key for m in METHOD_ORDER)]
    x = np.arange(len(scenarios))
    width = 0.15

    fig, ax = plt.subplots(figsize=(12, 5.6))
    for idx, method in enumerate(METHOD_ORDER):
        values = [
            results_by_key.get((scenario, method), {}).get("summary", {}).get("throughput_jobs_per_s", np.nan)
            for scenario in scenarios
        ]
        offset = (idx - (len(METHOD_ORDER) - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            values,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        annotate_bars(ax, bars, "{:.3f}")

    ax.set_title("Workflow Throughput by Scenario")
    ax.set_ylabel("Jobs per second, ")
    ax.set_xticks(x)
    ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios])
    ax.legend(ncols=5, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    ax.set_ylim(0, ax.get_ylim()[1] * 1.16)
    save(fig, out_dir, "02_throughput")


def plot_migration_quality(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    labels: list[str] = []
    useful: list[float] = []
    unnecessary: list[float] = []
    colors: list[str] = []
    for scenario in SCENARIO_ORDER:
        for method in METHOD_ORDER:
            item = results_by_key.get((scenario, method))
            if not item:
                continue
            summary = item["summary"]
            migrations = summary.get("migration_count", 0) or 0
            unnecessary_count = summary.get("unnecessary_migration_count", 0) or 0
            labels.append(f"{SCENARIO_LABELS[scenario]}\n{METHOD_LABELS[method]}")
            useful.append(max(migrations - unnecessary_count, 0))
            unnecessary.append(unnecessary_count)
            colors.append(COLORS[method])

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(14, 6))
    ax.bar(x, useful, color=colors, edgecolor="white", linewidth=0.8, label="Useful migration")
    ax.bar(
        x,
        unnecessary,
        bottom=useful,
        color="#EF4444",
        edgecolor="white",
        linewidth=0.8,
        hatch="///",
        label="Unnecessary migration",
    )
    ax.set_title("Migration Decision Quality")
    ax.set_ylabel("Count per 5 workflows")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 5.8)
    ax.legend(loc="upper right")
    save(fig, out_dir, "03_migration_quality")


def plot_net_gain(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    scenarios = [s for s in SCENARIO_ORDER if any((s, m) in results_by_key for m in METHOD_ORDER)]
    x = np.arange(len(scenarios))

    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    for method in ["selective", "runtime"]:
        values = [
            results_by_key.get((scenario, method), {}).get("summary", {}).get("net_gain_mean_ms", np.nan)
            for scenario in scenarios
        ]
        ax.plot(
            x,
            values,
            marker="o",
            linewidth=2.4,
            markersize=7,
            label=METHOD_LABELS[method],
            color=COLORS[method],
        )
        for xi, value in zip(x, values):
            if np.isfinite(value):
                ax.text(xi, value + 45, f"{value:.0f}", ha="center", fontsize=8, color=COLORS[method])

    ax.axhline(900, color="#111827", linewidth=1.2, linestyle="--", label="900 ms decision margin")
    ax.set_title("Predicted Net Gain for Adaptive Methods")
    ax.set_ylabel("Mean net gain (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios])
    ax.legend(loc="upper left")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.16)
    save(fig, out_dir, "04_adaptive_net_gain")


def plot_stage_composition(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    scenario = "heavy-burst"
    methods = [method for method in METHOD_ORDER if (scenario, method) in results_by_key]
    capture = []
    preprocess = []
    inference = []
    for method in methods:
        summary = results_by_key[(scenario, method)]["summary"]
        capture.append(summary.get("capture_latency_mean_ms", 0))
        preprocess.append(summary.get("preprocess_latency_mean_ms", 0))
        inference.append(summary.get("inference_latency_mean_ms", 0))

    x = np.arange(len(methods))
    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    ax.bar(x, capture, color="#60A5FA", edgecolor="white", linewidth=0.8, label="Capture")
    ax.bar(x, preprocess, bottom=capture, color="#34D399", edgecolor="white", linewidth=0.8, label="Preprocess")
    ax.bar(
        x,
        inference,
        bottom=np.array(capture) + np.array(preprocess),
        color="#A78BFA",
        edgecolor="white",
        linewidth=0.8,
        label="Inference",
    )
    totals = np.array(capture) + np.array(preprocess) + np.array(inference)
    for xi, total in zip(x, totals):
        ax.text(xi, total + 120, f"{total:.0f}", ha="center", fontsize=8, color="#374151")
    ax.set_title("Heavy Burst Stage Latency Composition")
    ax.set_ylabel("Mean latency (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels([METHOD_LABELS[m] for m in methods], rotation=20, ha="right")
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    ax.set_ylim(0, ax.get_ylim()[1] * 1.14)
    save(fig, out_dir, "05_heavy_burst_stage_composition")


def plot_poster_summary(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    scenarios = [s for s in SCENARIO_ORDER if (s, "static") in results_by_key]
    methods = [m for m in METHOD_ORDER if m != "static"]
    x = np.arange(len(scenarios))
    width = 0.18

    fig, axes = plt.subplots(
        2,
        2,
        figsize=(14, 9),
        gridspec_kw={"height_ratios": [1.05, 0.95]},
    )
    ax_latency, ax_throughput, ax_overhead, ax_unnecessary = axes.ravel()
    fig.suptitle("Selective Replanning Poster Summary", fontsize=18, y=0.98)

    for idx, method in enumerate(methods):
        offset = (idx - (len(methods) - 1) / 2) * width
        latency_delta_pct = []
        throughput_delta_pct = []
        overhead_values = []
        unnecessary_values = []
        for scenario in scenarios:
            static_summary = results_by_key[(scenario, "static")]["summary"]
            method_summary = results_by_key.get((scenario, method), {}).get("summary", {})
            static_latency = static_summary.get("e2e_latency_p95_ms", np.nan)
            method_latency = method_summary.get("e2e_latency_p95_ms", np.nan)
            static_tps = static_summary.get("throughput_jobs_per_s", np.nan)
            method_tps = method_summary.get("throughput_jobs_per_s", np.nan)
            latency_delta_pct.append((static_latency - method_latency) / static_latency * 100)
            throughput_delta_pct.append((method_tps - static_tps) / static_tps * 100)
            overhead_values.append(method_summary.get("migration_time_mean_ms", np.nan))
            unnecessary_values.append(method_summary.get("unnecessary_migration_count", 0))

        ax_latency.bar(
            x + offset,
            latency_delta_pct,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        ax_throughput.bar(
            x + offset,
            throughput_delta_pct,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        ax_overhead.bar(
            x + offset,
            overhead_values,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        ax_unnecessary.bar(
            x + offset,
            unnecessary_values,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )

    ax_latency.axhline(0, color="#111827", linewidth=1.0)
    ax_latency.set_title("E2E p95 Latency vs Static")
    ax_latency.set_ylabel("Reduction (%)")
    ax_latency.text(
        0.01,
        0.95,
        "",
        transform=ax_latency.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    ax_throughput.axhline(0, color="#111827", linewidth=1.0)
    ax_throughput.set_title("Throughput vs Static")
    ax_throughput.set_ylabel("Increase (%)")
    ax_throughput.text(
        0.01,
        0.95,
        "",
        transform=ax_throughput.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    ax_overhead.set_title("Migration Overhead")
    ax_overhead.set_ylabel("Mean migration time (ms)")
    ax_overhead.text(
        0.01,
        0.95,
        "lower is better",
        transform=ax_overhead.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    ax_unnecessary.set_title("Unnecessary Migration")
    ax_unnecessary.set_ylabel("Count per 5 workflows")
    ax_unnecessary.set_ylim(0, 5.8)
    ax_unnecessary.text(
        0.01,
        0.95,
        "lower is better",
        transform=ax_unnecessary.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    for ax in axes.ravel():
        ax.set_xticks(x)
        ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios], rotation=15, ha="right")

    handles, labels = ax_latency.get_legend_handles_labels()
    fig.legend(handles, labels, ncols=4, loc="upper center", bbox_to_anchor=(0.5, 0.94))
    fig.subplots_adjust(top=0.84, hspace=0.42, wspace=0.24)
    fig.savefig(out_dir / "06_poster_static_latency_migration_summary.png", bbox_inches="tight")
    fig.savefig(out_dir / "06_poster_static_latency_migration_summary.svg", bbox_inches="tight")
    plt.close(fig)


def plot_poster_two_panel(results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path) -> None:
    scenarios = [s for s in SCENARIO_ORDER if (s, "static") in results_by_key]
    methods = [m for m in METHOD_ORDER if m != "static"]
    x = np.arange(len(scenarios))
    width = 0.18

    fig, (ax_latency, ax_unnecessary) = plt.subplots(1, 2, figsize=(14, 5.4))
    fig.suptitle("Static Baseline Comparison and Migration Quality", fontsize=17, y=1.02)

    for idx, method in enumerate(methods):
        offset = (idx - (len(methods) - 1) / 2) * width
        latency_delta_pct = []
        unnecessary_values = []
        for scenario in scenarios:
            static_summary = results_by_key[(scenario, "static")]["summary"]
            method_summary = results_by_key.get((scenario, method), {}).get("summary", {})
            static_latency = static_summary.get("e2e_latency_p95_ms", np.nan)
            method_latency = method_summary.get("e2e_latency_p95_ms", np.nan)
            latency_delta_pct.append((static_latency - method_latency) / static_latency * 100)
            unnecessary_values.append(method_summary.get("unnecessary_migration_count", 0))

        ax_latency.bar(
            x + offset,
            latency_delta_pct,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        ax_unnecessary.bar(
            x + offset,
            unnecessary_values,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )

    ax_latency.axhline(0, color="#111827", linewidth=1.0)
    ax_latency.set_title("E2E p95 Latency vs Static")
    ax_latency.set_ylabel("Latency reduction (%)")
    ax_latency.text(
        0.01,
        0.95,
        "",
        transform=ax_latency.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    ax_unnecessary.set_title("Unnecessary Migration")
    ax_unnecessary.set_ylabel("Count per 5 workflows")
    ax_unnecessary.set_ylim(0, 5.8)
    ax_unnecessary.text(
        0.01,
        0.95,
        "lower is better",
        transform=ax_unnecessary.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    for ax in (ax_latency, ax_unnecessary):
        ax.set_xticks(x)
        ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios], rotation=15, ha="right")

    handles, labels = ax_latency.get_legend_handles_labels()
    fig.legend(handles, labels, ncols=4, loc="upper center", bbox_to_anchor=(0.5, 0.94))
    fig.subplots_adjust(top=0.78, wspace=0.24)
    fig.savefig(out_dir / "07_poster_two_panel_latency_migration_quality.png", bbox_inches="tight")
    fig.savefig(out_dir / "07_poster_two_panel_latency_migration_quality.svg", bbox_inches="tight")
    plt.close(fig)


def plot_poster_performance_two_panel(
    results_by_key: dict[tuple[str, str], dict[str, Any]], out_dir: Path
) -> None:
    scenarios = [s for s in SCENARIO_ORDER if (s, "static") in results_by_key]
    methods = [m for m in METHOD_ORDER if m != "static"]
    x = np.arange(len(scenarios))
    width = 0.18

    fig, (ax_latency, ax_throughput) = plt.subplots(1, 2, figsize=(14, 5.4))
    fig.suptitle("Performance Compared with Static Baseline", fontsize=17, y=1.02)

    for idx, method in enumerate(methods):
        offset = (idx - (len(methods) - 1) / 2) * width
        latency_delta_pct = []
        throughput_delta_pct = []
        for scenario in scenarios:
            static_summary = results_by_key[(scenario, "static")]["summary"]
            method_summary = results_by_key.get((scenario, method), {}).get("summary", {})
            static_latency = static_summary.get("e2e_latency_p95_ms", np.nan)
            method_latency = method_summary.get("e2e_latency_p95_ms", np.nan)
            static_tps = static_summary.get("throughput_jobs_per_s", np.nan)
            method_tps = method_summary.get("throughput_jobs_per_s", np.nan)
            latency_delta_pct.append((static_latency - method_latency) / static_latency * 100)
            throughput_delta_pct.append((method_tps - static_tps) / static_tps * 100)

        ax_latency.bar(
            x + offset,
            latency_delta_pct,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )
        ax_throughput.bar(
            x + offset,
            throughput_delta_pct,
            width,
            label=METHOD_LABELS[method],
            color=COLORS[method],
            edgecolor="white",
            linewidth=0.8,
        )

    ax_latency.axhline(0, color="#111827", linewidth=1.0)
    ax_latency.set_title("E2E p95 Latency vs Static")
    ax_latency.set_ylabel("Latency reduction (%)")
    ax_latency.text(
        0.01,
        0.95,
        "",
        transform=ax_latency.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    ax_throughput.axhline(0, color="#111827", linewidth=1.0)
    ax_throughput.set_title("Throughput vs Static")
    ax_throughput.set_ylabel("Throughput increase (%)")
    ax_throughput.text(
        0.01,
        0.95,
        "",
        transform=ax_throughput.transAxes,
        fontsize=9,
        color="#374151",
        va="top",
    )

    for ax in (ax_latency, ax_throughput):
        ax.set_xticks(x)
        ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios], rotation=15, ha="right")

    handles, labels = ax_latency.get_legend_handles_labels()
    fig.legend(handles, labels, ncols=4, loc="upper center", bbox_to_anchor=(0.5, 0.94))
    fig.subplots_adjust(top=0.78, wspace=0.24)
    fig.savefig(out_dir / "08_poster_two_panel_e2e_throughput.png", bbox_inches="tight")
    fig.savefig(out_dir / "08_poster_two_panel_e2e_throughput.svg", bbox_inches="tight")
    plt.close(fig)


def write_summary_csv(results: list[dict[str, Any]], out_dir: Path) -> None:
    def csv_value(value: Any) -> str:
        return "" if value is None else str(value)

    rows = [
        "scenario,method,e2e_p95_ms,preprocess_p95_ms,throughput_jobs_per_s,"
        "migration_count,unnecessary_migration_count,net_gain_mean_ms"
    ]
    ordered = sorted(
        results,
        key=lambda item: (
            SCENARIO_ORDER.index(item["scenario"]) if item["scenario"] in SCENARIO_ORDER else 99,
            METHOD_ORDER.index(item["method"]) if item["method"] in METHOD_ORDER else 99,
        ),
    )
    for item in ordered:
        summary = item["summary"]
        rows.append(
            ",".join(
                [
                    item["scenario"],
                    item["method"],
                    csv_value(summary.get("e2e_latency_p95_ms")),
                    csv_value(summary.get("preprocess_latency_p95_ms")),
                    csv_value(summary.get("throughput_jobs_per_s")),
                    csv_value(summary.get("migration_count")),
                    csv_value(summary.get("unnecessary_migration_count")),
                    csv_value(summary.get("net_gain_mean_ms")),
                ]
            )
        )
    (out_dir / "summary.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot selective replanning experiment logs.")
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=Path("docs/archive/embedded-conference/archive/selective-replanning-2026-04-23"),
    )
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    archive_dir = args.archive_dir
    out_dir = args.out_dir or archive_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    setup_style()
    results = load_results(archive_dir)
    by_key = result_map(results)

    plot_latency(by_key, out_dir)
    plot_throughput(by_key, out_dir)
    plot_migration_quality(by_key, out_dir)
    plot_net_gain(by_key, out_dir)
    plot_stage_composition(by_key, out_dir)
    plot_poster_summary(by_key, out_dir)
    plot_poster_two_panel(by_key, out_dir)
    plot_poster_performance_two_panel(by_key, out_dir)
    write_summary_csv(results, out_dir)
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    main()
