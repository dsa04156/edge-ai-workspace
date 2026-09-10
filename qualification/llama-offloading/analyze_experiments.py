"""Create method comparison tables, break-even results, and accessible figures."""

from __future__ import annotations

import argparse
from pathlib import Path
import math

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import pandas as pd


METHOD_LABELS = {
    "always_on": "Always-On",
    "cold_on_demand": "Cold On-Demand",
    "cached_on_demand": "Cached On-Demand",
}
COLORS = {"always_on": "#0072B2", "cold_on_demand": "#D55E00", "cached_on_demand": "#009E73"}
MARKERS = {"always_on": "o", "cold_on_demand": "s", "cached_on_demand": "^"}
SLO_TTFT_MS = 1500.0


def p95(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(0.95)) if len(values) else math.nan


def interval_union_seconds(rows: pd.DataFrame) -> float:
    intervals = sorted(
        (float(row.timestamp), float(row.completed_timestamp))
        for row in rows.itertuples()
        if pd.notna(row.timestamp) and pd.notna(row.completed_timestamp)
    )
    if not intervals:
        return 0.0
    total = 0.0
    start, end = intervals[0]
    for next_start, next_end in intervals[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def throughput(group: pd.DataFrame) -> float:
    durations: list[float] = []
    dimensions = [column for column in ("experiment", "phase") if column in group.columns]
    partitions = group.groupby(dimensions) if dimensions else [("all", group)]
    for _, partition in partitions:
        start = pd.to_numeric(partition["timestamp"], errors="coerce").min()
        end = pd.to_numeric(partition["completed_timestamp"], errors="coerce").max()
        if pd.notna(start) and pd.notna(end) and end > start:
            durations.append(float(end - start))
    return len(group) / sum(durations) if durations and sum(durations) > 0 else math.nan


def performance_table(ok: pd.DataFrame) -> pd.DataFrame:
    rows = []
    workload = ok[ok["experiment"].isin(["single", "increasing", "burst", "repeated"])]
    for method in METHOD_LABELS:
        group = workload[workload["method"] == method]
        violating = group[pd.to_numeric(group["ttft_ms"], errors="coerce") > SLO_TTFT_MS]
        rows.append(
            {
                "method": METHOD_LABELS[method],
                "requests": len(group),
                "mean_latency_ms": pd.to_numeric(group["actual_latency_ms"], errors="coerce").mean(),
                "p95_latency_ms": p95(group["actual_latency_ms"]),
                "mean_ttft_ms": pd.to_numeric(group["ttft_ms"], errors="coerce").mean(),
                "p95_ttft_ms": p95(group["ttft_ms"]),
                "mean_tokens_per_second": pd.to_numeric(group["tokens_per_second"], errors="coerce").mean(),
                "throughput_requests_per_second": throughput(group),
                "slo_violation_union_seconds": interval_union_seconds(violating),
            }
        )
    return pd.DataFrame(rows)


def activation_table(ok: pd.DataFrame) -> pd.DataFrame:
    rows = []
    probes = ok[ok["experiment"].astype(str).str.startswith("activation_")]
    for method in ("cold_on_demand", "cached_on_demand"):
        for node in ("agx", "spark"):
            group = probes[(probes["method"] == method) & (probes["selected_node"] == node)]
            rows.append(
                {
                    "method": METHOD_LABELS[method],
                    "node": node.upper(),
                    "activation_time_ms": pd.to_numeric(group["activation_time_ms"], errors="coerce").mean(),
                    "worker_start_ms": pd.to_numeric(group["worker_start_ms"], errors="coerce").mean(),
                    "model_remote_download_ms": pd.to_numeric(group["model_remote_download_ms"], errors="coerce").mean(),
                    "model_load_ms": pd.to_numeric(group["model_load_ms"], errors="coerce").mean(),
                    "first_offloaded_request_latency_ms": pd.to_numeric(group["actual_latency_ms"], errors="coerce").mean(),
                }
            )
    return pd.DataFrame(rows)


def idle_resource_table(resources: pd.DataFrame) -> pd.DataFrame:
    idle = resources[resources["experiment"] == "idle"].copy()
    rows = []
    for method in METHOD_LABELS:
        for node in ("nano", "agx", "spark"):
            group = idle[(idle["method"] == method) & (idle["node"] == node)]
            attributable = group[group["gpu_measurement_attributable"].astype(str).str.lower() == "true"]
            rows.append(
                {
                    "method": METHOD_LABELS[method],
                    "node": node.upper(),
                    "idle_gpu_memory_mib": pd.to_numeric(attributable["gpu_memory_used_mib"], errors="coerce").mean(),
                    "idle_inference_runner_rss_mib": pd.to_numeric(group["inference_process_rss_mib"], errors="coerce").mean(),
                    "local_checkpoint_bytes": pd.to_numeric(group["model_cache_bytes"], errors="coerce").mean(),
                    "average_gpu_utilization_percent": pd.to_numeric(attributable["gpu_utilization_percent"], errors="coerce").mean(),
                    "average_ram_utilization_percent": pd.to_numeric(group["ram_utilization_percent"], errors="coerce").mean(),
                    "idle_power_watts": math.nan,
                    "gpu_attribution_note": "direct measurement unavailable" if attributable.empty else "attributable",
                }
            )
    return pd.DataFrame(rows)


def concurrency_table(ok: pd.DataFrame) -> pd.DataFrame:
    data = ok[ok["experiment"].isin(["increasing", "nano_only"])].copy()
    rows = []
    for (experiment, method, concurrency), group in data.groupby(["experiment", "method", "requested_concurrency"]):
        label = "Nano-only" if experiment == "nano_only" else METHOD_LABELS.get(method, method)
        rows.append(
            {
                "series": label,
                "method": method,
                "concurrency": int(concurrency),
                "p95_latency_ms": p95(group["actual_latency_ms"]),
                "p95_ttft_ms": p95(group["ttft_ms"]),
                "throughput_requests_per_second": throughput(group),
            }
        )
    columns = ["series", "method", "concurrency", "p95_latency_ms", "p95_ttft_ms", "throughput_requests_per_second"]
    return pd.DataFrame(rows, columns=columns).sort_values(["series", "concurrency"])


def break_even_table(ok: pd.DataFrame) -> pd.DataFrame:
    baseline = ok[ok["experiment"] == "nano_only"].copy()
    means = baseline.groupby("requested_concurrency")["actual_latency_ms"].mean().to_dict()
    remote = ok[
        ok["selected_node"].isin(["agx", "spark"])
        & (ok["experiment"].eq("increasing") | ok["experiment"].astype(str).str.startswith("activation_"))
    ].copy()
    remote["nano_expected_ms"] = remote["requested_concurrency"].map(means)
    for field in ("activation_time_ms", "rtt_ms", "worker_actual_e2e_ms"):
        remote[field] = pd.to_numeric(remote[field], errors="coerce")
    remote["offload_cost_ms"] = remote["activation_time_ms"] + remote["rtt_ms"] + remote["worker_actual_e2e_ms"]
    remote["offloading_gain_ms"] = remote["nano_expected_ms"] - remote["offload_cost_ms"]
    remote["beneficial"] = remote["offloading_gain_ms"] > 0
    return remote[[
        "request_id", "method", "selected_node", "requested_concurrency", "nano_expected_ms",
        "activation_time_ms", "rtt_ms", "worker_actual_e2e_ms", "offload_cost_ms", "offloading_gain_ms", "beneficial",
    ]]


def break_even_thresholds(ok: pd.DataFrame) -> pd.DataFrame:
    nano = ok[(ok["experiment"] == "nano_only") & (ok["requested_concurrency"] == 1)]
    nano_service_ms = pd.to_numeric(nano["actual_latency_ms"], errors="coerce").mean()
    probes = ok[ok["experiment"].astype(str).str.startswith("activation_")]
    rows = []
    for method in ("cold_on_demand", "cached_on_demand"):
        for node in ("agx", "spark"):
            group = probes[(probes["method"] == method) & (probes["selected_node"] == node)]
            activation_ms = pd.to_numeric(group["activation_time_ms"], errors="coerce").mean()
            remote_ms = (
                pd.to_numeric(group["worker_actual_e2e_ms"], errors="coerce").mean()
                + pd.to_numeric(group["rtt_ms"], errors="coerce").mean()
            )
            saved_ms = nano_service_ms - remote_ms
            requests = math.ceil(activation_ms / saved_ms) if pd.notna(saved_ms) and saved_ms > 0 else math.nan
            rows.append(
                {
                    "method": METHOD_LABELS[method],
                    "node": node.upper(),
                    "nano_service_ms": nano_service_ms,
                    "remote_inference_plus_rtt_ms": remote_ms,
                    "saved_ms_per_request": saved_ms,
                    "activation_ms": activation_ms,
                    "break_even_requests": requests,
                    "break_even_nano_time_seconds": requests * nano_service_ms / 1000.0 if pd.notna(requests) else math.nan,
                }
            )
    return pd.DataFrame(rows)


def line_plot(table: pd.DataFrame, metric: str, ylabel: str, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    for series, group in table.groupby("series"):
        key = next((method for method, label in METHOD_LABELS.items() if label == series), "always_on")
        color = "#6B7280" if series == "Nano-only" else COLORS[key]
        marker = "x" if series == "Nano-only" else MARKERS[key]
        ax.plot(group["concurrency"], group[metric], label=series, color=color, marker=marker, linewidth=2)
    ax.set_xlabel("Concurrency")
    ax.set_ylabel(ylabel)
    if table.empty:
        ax.text(0.5, 0.5, "No observations for this plot", ha="center", va="center", transform=ax.transAxes)
    else:
        ax.set_xticks(sorted(table["concurrency"].unique()))
    ax.grid(alpha=0.25)
    if not table.empty:
        ax.legend()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def time_plot(resources: pd.DataFrame, metric: str, ylabel: str, output: Path, *, burst_only: bool = True) -> None:
    data = resources[resources["experiment"] == "burst"].copy() if burst_only else resources.copy()
    method = "cached_on_demand"
    data = data[data["method"] == method]
    if metric.startswith("gpu_"):
        data = data[data["gpu_measurement_attributable"].astype(str).str.lower() == "true"]
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    any_values = False
    for node, color, marker in zip(("nano", "agx", "spark"), ("#0072B2", "#D55E00", "#009E73"), ("o", "s", "^")):
        group = data[data["node"] == node].copy()
        if group.empty:
            continue
        group[metric] = pd.to_numeric(group[metric], errors="coerce")
        group["elapsed"] = group["timestamp"] - data["timestamp"].min()
        if group[metric].notna().any():
            any_values = True
            ax.plot(group["elapsed"], group[metric], label=node.upper(), color=color, marker=marker, markevery=15)
    if not any_values:
        ax.text(0.5, 0.5, "No attributable GPU observations", ha="center", va="center", transform=ax.transAxes)
    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.25)
    if any_values:
        ax.legend()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def activation_timeline(resources: pd.DataFrame, output: Path) -> None:
    data = resources[(resources["experiment"] == "burst") & (resources["method"] == "cached_on_demand")].copy()
    fig, ax = plt.subplots(figsize=(9, 3.8), constrained_layout=True)
    state_colors = {"COLD": "#9CA3AF", "CACHED": "#E69F00", "ACTIVE": "#009E73"}
    origin = data["timestamp"].min() if not data.empty else 0
    for y, node in enumerate(("nano", "agx", "spark")):
        group = data[data["node"] == node].sort_values("timestamp")
        for current, following in zip(group.itertuples(), list(group.itertuples())[1:] + [None]):
            end = following.timestamp if following else current.timestamp + 1
            ax.barh(y, end - current.timestamp, left=current.timestamp - origin, color=state_colors.get(current.node_state, "#FFFFFF"), edgecolor="none")
    ax.set_yticks(range(3), ["Nano", "AGX", "Spark"])
    ax.set_xlabel("Elapsed time (s)")
    ax.set_title("Cached On-Demand burst state timeline")
    ax.legend(handles=[Patch(color=color, label=state) for state, color in state_colors.items()], title="State", loc="upper right")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def bar_plot(table: pd.DataFrame, value: str, output: Path, ylabel: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8), constrained_layout=True)
    pivot = table.pivot(index="node", columns="method", values=value)
    pivot.plot(kind="bar", ax=ax, color=[COLORS.get(next((k for k, v in METHOD_LABELS.items() if v == col), ""), "#777777") for col in pivot.columns])
    if pivot.notna().sum().sum() == 0:
        ax.text(0.5, 0.5, "No attributable GPU observations", ha="center", va="center", transform=ax.transAxes)
    ax.set_xlabel("Node")
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=0)
    ax.legend(title="Method")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def markdown_table(frame: pd.DataFrame) -> str:
    return frame.to_markdown(index=False, floatfmt=".3f")


def percent_change(old: float, new: float) -> float:
    return 100.0 * (old - new) / old if pd.notna(old) and pd.notna(new) and old != 0 else math.nan


def question_analysis(
    performance: pd.DataFrame,
    activation: pd.DataFrame,
    idle: pd.DataFrame,
    concurrency: pd.DataFrame,
    break_even: pd.DataFrame,
    thresholds: pd.DataFrame,
) -> str:
    lines = ["## 질문별 분석", ""]
    idle_pivot = idle.pivot(index="node", columns="method", values="idle_inference_runner_rss_mib")
    always_remote = idle_pivot.get("Always-On", pd.Series(dtype=float)).reindex(["AGX", "SPARK"]).sum(min_count=1)
    cached_remote = idle_pivot.get("Cached On-Demand", pd.Series(dtype=float)).reindex(["AGX", "SPARK"]).sum(min_count=1)
    lines.append(
        f"1. 직접 귀속 가능한 GPU memory 값은 없다. runner RSS 대체 계측에서 Always-On 원격 합계는 {always_remote:.1f} MiB, Cached는 {cached_remote:.1f} MiB로 {always_remote - cached_remote:.1f} MiB 차이다."
    )
    for node in ("AGX", "SPARK"):
        cold = activation[(activation["method"] == "Cold On-Demand") & (activation["node"] == node)]
        cached = activation[(activation["method"] == "Cached On-Demand") & (activation["node"] == node)]
        cold_first = cold["first_offloaded_request_latency_ms"].iloc[0] if len(cold) else math.nan
        cached_first = cached["first_offloaded_request_latency_ms"].iloc[0] if len(cached) else math.nan
        cold_activation = cold["activation_time_ms"].iloc[0] if len(cold) else math.nan
        cached_activation = cached["activation_time_ms"].iloc[0] if len(cached) else math.nan
        lines.append(
            f"2-3. {node}: Cold 첫 offload {cold_first:.1f} ms, Cached {cached_first:.1f} ms; activation은 {cold_activation:.1f}→{cached_activation:.1f} ms로 {percent_change(cold_activation, cached_activation):.1f}% 감소했다."
        )
    c32 = concurrency[concurrency["concurrency"] == 32].set_index("series")
    if "Nano-only" in c32.index:
        nano_latency = c32.loc["Nano-only", "p95_latency_ms"]
        nano_throughput = c32.loc["Nano-only", "throughput_requests_per_second"]
        for label in ("Always-On", "Cached On-Demand", "Cold On-Demand"):
            if label in c32.index:
                lines.append(
                    f"4. concurrency 32의 {label}: Nano-only 대비 p95 latency {percent_change(nano_latency, c32.loc[label, 'p95_latency_ms']):.1f}% 개선, throughput {(c32.loc[label, 'throughput_requests_per_second'] / nano_throughput - 1) * 100:.1f}% 증가했다."
                )
    perf = performance.set_index("method")
    if "Always-On" in perf.index and "Cached On-Demand" in perf.index:
        lines.append(
            f"5. Cached는 원격 runner RSS {always_remote - cached_remote:.1f} MiB를 유휴 시 반환했고, 전체 p95 latency는 Always-On 대비 {(perf.loc['Cached On-Demand', 'p95_latency_ms'] / perf.loc['Always-On', 'p95_latency_ms'] - 1) * 100:.1f}% 차이였다."
        )
    cached_activation = activation[activation["method"] == "Cached On-Demand"].set_index("node")
    if {"AGX", "SPARK"}.issubset(cached_activation.index):
        better = cached_activation["first_offloaded_request_latency_ms"].idxmin()
        lines.append(f"6. 이 혼합 장비 CPU-only 시험에서 activation 대비 첫 요청 latency가 더 낮은 역할은 {better}였다. 실제 AGX Orin/DGX Spark GPU 결론으로 일반화할 수 없다.")
    lines.append("7. activation을 포함한 gain이 0 이하인 짧은 burst는 원격을 켜지 않는 편이 낫다. Cold 방식은 체크포인트 전송 시간이 길어 이 구간이 특히 크다.")
    if not thresholds.empty:
        rendered = ", ".join(
            f"{row.method}/{row.node} 약 {int(row.break_even_requests)} requests 또는 Nano 순차시간 {row.break_even_nano_time_seconds:.1f}s"
            for row in thresholds.itertuples()
            if pd.notna(row.break_even_requests)
        )
        lines.append(f"8. 단일 요청 service-time 차이를 누적하는 단순 break-even 추정은 {rendered}다. queueing과 병렬성은 제외한 자격시험용 근사치다.")
    elif not break_even.empty:
        useful = break_even.groupby(["method", "selected_node", "requested_concurrency"])["beneficial"].mean().reset_index()
        useful = useful[useful["beneficial"] > 0.5]
        if len(useful):
            first = useful.sort_values("requested_concurrency").iloc[0]
            lines.append(
                f"8. 관측 표본에서 과반의 gain이 양수가 된 가장 낮은 지점은 {first['method']}→{str(first['selected_node']).upper()}, concurrency {int(first['requested_concurrency'])}였다. 정확한 지속시간 임계값은 tables/break-even.csv의 요청별 gain을 사용한다."
            )
        else:
            lines.append("8. 관측 표본 중 과반의 gain이 양수인 구간은 없었다.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    requests = pd.read_csv(args.run_dir / "requests.csv")
    resources = pd.read_csv(args.run_dir / "resources.csv")
    ok = requests[requests["status"] == "ok"].copy()
    for field in ("actual_latency_ms", "ttft_ms", "tokens_per_second", "timestamp", "completed_timestamp", "requested_concurrency"):
        ok[field] = pd.to_numeric(ok[field], errors="coerce")

    tables_dir = args.run_dir / "tables"
    figures_dir = args.run_dir / "figures"
    tables_dir.mkdir(exist_ok=True)
    figures_dir.mkdir(exist_ok=True)
    performance = performance_table(ok)
    activation = activation_table(ok)
    idle = idle_resource_table(resources)
    concurrency = concurrency_table(ok)
    break_even = break_even_table(ok)
    thresholds = break_even_thresholds(ok)
    for name, frame in (("performance", performance), ("activation", activation), ("idle-resources", idle),
                        ("concurrency", concurrency), ("break-even", break_even),
                        ("break-even-thresholds", thresholds)):
        frame.to_csv(tables_dir / f"{name}.csv", index=False)

    line_plot(concurrency, "p95_latency_ms", "p95 latency (ms)", figures_dir / "01-concurrency-vs-p95-latency.png")
    line_plot(concurrency, "p95_ttft_ms", "p95 TTFT (ms)", figures_dir / "02-concurrency-vs-ttft.png")
    line_plot(concurrency, "throughput_requests_per_second", "Throughput (requests/s)", figures_dir / "03-concurrency-vs-throughput.png")
    time_plot(resources, "gpu_utilization_percent", "GPU utilization (%)", figures_dir / "04-gpu-utilization-timeline.png")
    time_plot(resources, "queue_length", "Queue length", figures_dir / "05-queue-length-timeline.png")
    activation_timeline(resources, figures_dir / "06-node-activation-timeline.png")
    bar_plot(idle, "idle_gpu_memory_mib", figures_dir / "07-idle-gpu-memory.png", "Idle GPU memory (MiB)")
    bar_plot(activation, "activation_time_ms", figures_dir / "08-activation-latency.png", "Activation latency (ms)")
    bar_plot(idle, "idle_inference_runner_rss_mib", figures_dir / "09-idle-runner-rss.png", "Idle inference runner RSS (MiB)")

    description = "# Figure descriptions\n\n"
    description += "1. Concurrency against p95 end-to-end latency for all methods and Nano-only.\n"
    description += "2. Concurrency against p95 time-to-first-token; markers duplicate color encoding.\n"
    description += "3. Concurrency against completed request throughput.\n"
    description += "4. Cached burst GPU utilization; unavailable or shared/non-attributable values remain missing, never zero-filled.\n"
    description += "5. Cached burst queue length by node over elapsed time.\n"
    description += "6. Cached burst COLD/CACHED/ACTIVE state intervals sampled once per second.\n"
    description += "7. Idle attributable GPU memory. If unavailable, the empty panel states that directly.\n"
    description += "8. Cold versus cached activation latency for AGX and Spark role nodes.\n"
    description += "9. Supplemental directly attributable inference runner RSS; this is not GPU memory.\n"
    (figures_dir / "README.md").write_text(description, encoding="utf-8")

    report = "# Llama 3.2 1B 오프로딩 비교 결과\n\n"
    report += (
        f"> 혼합 장비 CPU-only 자격시험 결과다. Nano는 실제 Orin Nano의 CPU-only 행이고, AGX·Spark는 amd64 서버 CPU 대체 행이다. 실제 세 장비의 GPU 성능 결론이 아니다. "
        f"총 {len(requests)}개 요청 중 성공 {len(ok)}개, 실패 {len(requests) - len(ok)}개다. "
        "GPU memory·전력은 직접 귀속 계측이 없어 N/A로 유지했다.\n\n"
    )
    report += "## 성능 비교\n\n" + markdown_table(performance) + "\n\n"
    report += "## Activation 비교\n\n" + markdown_table(activation) + "\n\n"
    report += "## 자원 사용 비교\n\n" + markdown_table(idle) + "\n\n"
    report += "## Break-even\n\n"
    if break_even.empty:
        report += "원격 처리 표본이 없어 계산할 수 없다.\n"
    else:
        grouped = break_even.groupby(["method", "selected_node", "requested_concurrency"])["offloading_gain_ms"].agg(["count", "mean", "median"])
        report += markdown_table(grouped.reset_index()) + "\n"
    report += "\n### 단순 누적 break-even 임계값\n\n" + markdown_table(thresholds) + "\n"
    report += "\n" + question_analysis(performance, activation, idle, concurrency, break_even, thresholds) + "\n"
    report += "\nGPU memory와 power는 직접 귀속 가능한 계측값이 없으면 NaN으로 유지했다. inference runner RSS는 GPU memory의 대체값이지 같은 측정값이 아니다.\n"
    (args.run_dir / "report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
