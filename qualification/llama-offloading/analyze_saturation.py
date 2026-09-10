"""Analyze fixed-worker saturation observations and derive routing gates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd


NODES = ("nano", "agx", "spark")
LABELS = {"nano": "Nano role", "agx": "AGX role", "spark": "Spark role"}
COLORS = {"nano": "#0072B2", "agx": "#D55E00", "spark": "#009E73"}
MARKERS = {"nano": "o", "agx": "s", "spark": "^"}
LINESTYLES = {"nano": "-", "agx": "--", "spark": "-."}
X86_GPU_LABELS = {
    "agx": "RTX 5060 Ti (AGX substitute role)",
    "spark": "RTX 5080 (Spark substitute role)",
}
TARGET_BOUNDARY_BY_ROLE = {
    "agx": "실제 Jetson AGX Orin이 아니다",
    "spark": "실제 NVIDIA DGX Spark가 아니다",
}
SLO_TTFT_MS = 1500.0


def numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def p95(frame: pd.DataFrame, column: str) -> float:
    values = numeric(frame, column).dropna()
    return float(values.quantile(0.95)) if len(values) else math.nan


def observed_throughput(frame: pd.DataFrame) -> float:
    submitted = numeric(frame, "timestamp").min()
    completed = numeric(frame, "completed_timestamp").max()
    return len(frame) / (completed - submitted) if pd.notna(submitted) and pd.notna(completed) and completed > submitted else math.nan


def aggregate(requests: pd.DataFrame, resources: pd.DataFrame) -> pd.DataFrame:
    measured = requests[(requests["excluded"].astype(str).str.lower() == "false")].copy()
    rows: list[dict[str, object]] = []
    for (node, concurrency), group in measured.groupby(["target_node", "concurrency"]):
        ok = group[group["status"] == "ok"]
        samples = resources[
            (resources["target_node"] == node)
            & (pd.to_numeric(resources["concurrency"], errors="coerce") == int(concurrency))
            & (resources["sampled_node"] == node)
        ]
        condition_throughputs = [observed_throughput(part) for _, part in ok.groupby("condition_id")]
        rows.append(
            {
                "node": node,
                "concurrency": int(concurrency),
                "blocks": int(group["block"].nunique()),
                "requests": len(group),
                "errors": int((group["status"] != "ok").sum()),
                "error_rate": float((group["status"] != "ok").mean()),
                "median_client_latency_ms": numeric(ok, "client_latency_ms").median(),
                "p95_client_latency_ms": p95(ok, "client_latency_ms"),
                "median_ttft_ms": numeric(ok, "ttft_ms").median(),
                "p95_ttft_ms": p95(ok, "ttft_ms"),
                "median_queue_wait_ms": numeric(ok, "queue_wait_ms").median(),
                "p95_queue_wait_ms": p95(ok, "queue_wait_ms"),
                "median_tokens_per_second": numeric(ok, "tokens_per_second").median(),
                "mean_throughput_rps": pd.Series(condition_throughputs, dtype="float64").mean(),
                "min_throughput_rps": pd.Series(condition_throughputs, dtype="float64").min(),
                "max_throughput_rps": pd.Series(condition_throughputs, dtype="float64").max(),
                "p95_observed_queue_length": p95(samples, "queue_length") if not samples.empty else math.nan,
                "max_observed_queue_length": numeric(samples, "queue_length").max() if not samples.empty else math.nan,
                "mean_cpu_percent": numeric(samples, "cpu_utilization_percent").mean() if not samples.empty else math.nan,
                "mean_ram_percent": numeric(samples, "ram_utilization_percent").mean() if not samples.empty else math.nan,
                "max_temperature_celsius": numeric(samples, "temperature_celsius").max() if not samples.empty else math.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["node", "concurrency"])


def derive_limits(summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    observed_nodes = tuple(node for node in NODES if node in set(summary["node"]))
    for node in observed_nodes:
        group = summary[summary["node"] == node].sort_values("concurrency").copy()
        max_throughput = numeric(group, "mean_throughput_rps").max()
        throughput_knee_rows = group[numeric(group, "mean_throughput_rps") >= 0.95 * max_throughput]
        throughput_knee = int(throughput_knee_rows.iloc[0]["concurrency"]) if not throughput_knee_rows.empty else math.nan
        passing = group[(numeric(group, "p95_ttft_ms") <= SLO_TTFT_MS) & (numeric(group, "error_rate") == 0)]
        slo_capacity = int(passing["concurrency"].max()) if not passing.empty else 0
        failing = group[(numeric(group, "p95_ttft_ms") > SLO_TTFT_MS) | (numeric(group, "error_rate") > 0)]
        first_overload = int(failing.iloc[0]["concurrency"]) if not failing.empty else None
        baseline = group[group["concurrency"] == 1].iloc[0]
        rows.append(
            {
                "node": node,
                "baseline_p95_ttft_ms": baseline["p95_ttft_ms"],
                "baseline_median_tokens_per_second": baseline["median_tokens_per_second"],
                "tokens_per_second_low": 0.8 * float(baseline["median_tokens_per_second"]),
                "max_observed_throughput_rps": max_throughput,
                "throughput_knee_concurrency": throughput_knee,
                "slo_capacity_concurrency": slo_capacity,
                "first_slo_overload_concurrency": first_overload,
                "ttft_high_ms": SLO_TTFT_MS,
            }
        )
    return pd.DataFrame(rows)


def derive_offload_gates(
    summary: pd.DataFrame,
    activation: pd.DataFrame,
    min_improvement: float = 0.15,
) -> pd.DataFrame:
    baseline = summary[summary["concurrency"] == 1].set_index("node")
    if not set(NODES).issubset(baseline.index):
        return pd.DataFrame()
    nano_ms = float(baseline.loc["nano", "median_client_latency_ms"])
    rows: list[dict[str, object]] = []
    for method, activation_label in (
        ("always_on", None),
        ("cached_on_demand", "Cached On-Demand"),
        ("cold_on_demand", "Cold On-Demand"),
    ):
        for target in ("agx", "spark"):
            target_ms = float(baseline.loc[target, "median_client_latency_ms"])
            activation_ms = 0.0
            if activation_label:
                match = activation[
                    (activation["method"] == activation_label)
                    & (activation["node"].astype(str).str.lower() == target)
                ]
                activation_ms = float(pd.to_numeric(match["activation_time_ms"], errors="coerce").iloc[0])
            saving_ms = nano_ms - target_ms
            sequential_break_even = max(1, math.ceil(activation_ms / saving_ms)) if saving_ms > 0 else math.nan
            target_first_completion_ms = activation_ms + target_ms
            required_nano_completion_ms = target_first_completion_ms / (1.0 - min_improvement)
            total_positions = math.ceil(required_nano_completion_ms / nano_ms)
            requests_ahead = max(0, total_positions - 1)
            rows.append(
                {
                    "method": method,
                    "target_node": target,
                    "activation_ms": activation_ms,
                    "nano_median_service_ms": nano_ms,
                    "target_median_service_ms": target_ms,
                    "saved_ms_per_subsequent_request": saving_ms,
                    "sequential_break_even_requests": sequential_break_even,
                    "minimum_nano_requests_ahead_for_15pct_first_request_gain": requests_ahead,
                    "reachable_before_tested_connection_failure_ceiling": requests_ahead < 32,
                }
            )
    return pd.DataFrame(rows)


def save_table(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


def plot(
    summary: pd.DataFrame,
    metric: str,
    ylabel: str,
    path: Path,
    *,
    slo_line: bool = False,
    profile: str = "cpu_substitute",
) -> None:
    mpl.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(8.2, 4.8), layout="constrained")
    observed_nodes = tuple(node for node in NODES if node in set(summary["node"]))
    for node in observed_nodes:
        group = summary[summary["node"] == node]
        if node == "nano" and profile == "orin_nano_gpu":
            label = "Orin Nano GPU"
        elif profile == "x86_gpu_substitute":
            label = X86_GPU_LABELS.get(node, LABELS[node])
        else:
            label = LABELS[node]
        ax.plot(
            group["concurrency"], group[metric], label=label, color=COLORS[node],
            marker=MARKERS[node], linestyle=LINESTYLES[node], linewidth=2,
        )
    if slo_line:
        ax.axhline(SLO_TTFT_MS, color="#6B7280", linestyle=":", linewidth=1.5, label="TTFT SLO 1,500 ms")
    ax.set_xscale("log", base=2)
    ax.set_xlim(0.8, 40)
    ax.set_xlabel("Client concurrency (log2 scale)")
    ax.set_ylabel(ylabel)
    ticks = sorted(int(value) for value in summary["concurrency"].unique())
    ax.set_xticks(ticks, labels=[str(value) for value in ticks])
    if metric in {"mean_throughput_rps", "p95_observed_queue_length"}:
        ax.set_ylim(bottom=0)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.savefig(path.with_suffix(".png"), dpi=180, facecolor="white")
    fig.savefig(path.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def render_report(
    summary: pd.DataFrame,
    limits: pd.DataFrame,
    gates: pd.DataFrame,
    output: Path,
    config: dict[str, object],
) -> None:
    key = summary[["node", "concurrency", "requests", "errors", "p95_ttft_ms", "p95_client_latency_ms", "mean_throughput_rps", "p95_observed_queue_length"]].copy()
    for column in ("p95_ttft_ms", "p95_client_latency_ms", "mean_throughput_rps", "p95_observed_queue_length"):
        key[column] = pd.to_numeric(key[column], errors="coerce").round(3)
    limit_view = limits.copy()
    for column in ("baseline_p95_ttft_ms", "baseline_median_tokens_per_second", "tokens_per_second_low", "max_observed_throughput_rps"):
        limit_view[column] = pd.to_numeric(limit_view[column], errors="coerce").round(3)
    primary = limits.iloc[0]
    profile = str(config.get("execution_profile") or "cpu_substitute")
    nano_gpu = profile == "orin_nano_gpu"
    x86_gpu_substitute = profile == "x86_gpu_substitute"
    queue_high = (
        8
        if nano_gpu
        else int(primary["slo_capacity_concurrency"])
        if x86_gpu_substitute
        else 1
    )
    title = (
        "Llama 3.2 1B Orin Nano GPU 포화점 자격시험"
        if nano_gpu
        else "Llama 3.2 1B x86 GPU 대체 서버 포화점 자격시험"
        if x86_gpu_substitute
        else "Llama 3.2 1B 노드별 포화점 자격시험"
    )
    if nano_gpu:
        boundary = """실제 `etri-dev0001-jetorn` Orin Nano에서 Ollama JetPack 6 CUDA runner로
`llama3.2:1b` 전체 모델을 실행했다. AGX Orin과 DGX Spark는 이 run에 포함하지 않았으므로
두 장비의 성능이나 오프로딩 손익은 결론 내리지 않는다."""
        policy_heading = "## Orin Nano GPU worker에 적용할 초기 부하 기준"
        scope_boundary = """- 요청은 실제 Orin Nano GPU worker API에 직접 전달했다.
- AGX Orin과 DGX Spark 실장비가 없어 원격 activation·break-even은 계산하지 않았다.
- GPU 사용 여부는 Ollama `inference compute`의 CUDA 8.7·JetPack 6 탐지와 `ollama ps`의
  `100% GPU`로 별도 검증했다."""
    elif x86_gpu_substitute:
        hardware = str(config.get("physical_hardware") or "x86 NVIDIA GPU")
        logical_role = str(config.get("logical_role") or primary["node"]).lower()
        role = logical_role.upper()
        target_boundary = TARGET_BOUNDARY_BY_ROLE.get(logical_role, "실제 목표 장비가 아니다")
        boundary = f"""실제 측정 장비는 `{hardware}`를 장착한 x86 서버이며 논리적으로 {role} 역할을
부여했다. Ollama에서 Llama 3.2 1B의 `100% GPU` 실행을 확인했지만, {target_boundary}.
따라서 이 결과는 오프로딩 코드와 GPU 실행 경로 검증용 대체값이며 목표 장비 성능값이 아니다."""
        policy_heading = "## x86 GPU 대체 worker에서 관측한 초기 부하 기준"
        scope_boundary = f"""- 요청은 `{hardware}` worker API에 직접 전달했다.
- 실제 Jetson AGX Orin·DGX Spark의 성능 또는 전력 결과로 해석하지 않는다.
- 모델 digest, prompt, max tokens와 worker concurrency는 Orin Nano 시험과 동일하게 유지했다."""
    else:
        boundary = """Nano는 실제 Orin Nano 노드에서 CPU-only로 실행했다. `AGX/Spark`는 실제 대상 장비가
아니라 amd64 서버에 부여한 역할이며 CPU로 실행했다. 따라서 Nano 행은 Orin Nano
CPU-only 기준선, AGX·Spark 행은 x86 CPU 대체값이며 실제 세 장비의 GPU 용량이 아니다."""
        policy_heading = "## Orin Nano CPU-only worker에 적용할 초기 부하 기준"
        scope_boundary = """- 요청은 워커 API에 직접 전달해 프록시의 세 노드 snapshot lock 시간을 모델 포화로 오인하지 않았다.
- CPU/온도/queue 표본은 보존하지만 서버 GPU 값은 기존 workload와 공유되어 Llama에 귀속하지 않는다.
- Orin Nano GPU와 실제 AGX Orin·DGX Spark 도입 시 같은 GPU runner로 다시 측정한
  값으로 이 기준을 교체해야 한다."""
    if gates.empty:
        if x86_gpu_substitute:
            gates_section = """## 원격 오프로딩 손익

이 run은 x86 GPU 대체 서버 한 대의 포화점만 측정했다. Nano와 동일 workload 결과는
비교할 수 있지만 실제 AGX Orin·DGX Spark의 activation·break-even은 계산하지 않는다."""
        else:
            gates_section = """## 원격 오프로딩 손익

이 run은 Orin Nano GPU 단독 포화점만 측정했다. 실제 AGX Orin·DGX Spark의 동일 조건
성능과 activation 시간이 없으므로 원격 break-even과 대상 선택 기준은 계산하지 않는다."""
    else:
        gates_section = f"""## Activation을 포함한 오프로딩 손익 기준

아래 `minimum_nano_requests_ahead...`는 새 요청이 도착할 때 Orin Nano worker에서 이미
실행·대기 중인 요청 수를 뜻한다. 같은 prompt 길이와 이 run의 중앙 서비스시간을 순차
처리로 근사했다. 실제 라우터는 최신 EWMA, queue, RTT와 activation estimate로 다시 계산한다.

{gates.round(3).to_markdown(index=False)}"""
    report = f"""# {title}

## 판정 요약

{boundary}

- 처리량 knee: 관측 최대 처리량의 95%에 처음 도달한 동시성
- SLO capacity: 오류 0이고 p95 TTFT가 1,500ms 이하인 가장 높은 동시성
- first overload: p95 TTFT 1,500ms 초과 또는 오류가 처음 발생한 동시성
- 반복 단위: block {config.get('blocks')}회. 같은 노드의 요청 여러 개를 독립 장비 반복으로 해석하지 않는다.

{limit_view.to_markdown(index=False)}

{gates_section}

{policy_heading}

- 조기 압력: `queue_length >= {queue_high}`이 2초 동안 지속
- 서비스 한계: rolling/worker EWMA TTFT가 `{SLO_TTFT_MS:.0f}ms` 이상
- 생성 성능 저하 보조 신호: tokens/s가 단독 실행 중앙값의 80%인 `{float(primary['tokens_per_second_low']):.3f}` 이하
- 부하 해제: queue 0 및 active request 0이 4초 지속, 경로 변경 후 5초 cooldown

queue는 임계값에 순간적으로 닿은 것만으로 즉시 오프로딩하지 않는다. 위 부하 latch를 통과한 뒤에도 대상의 `activation + RTT + queue wait + inference`를 포함한 예상 완료시간이 Nano 예상 완료시간보다 15% 이상 짧고 gain이 양수일 때만 새 요청을 보낸다. 대상이 READY가 되기 전에는 보내지 않는다.

## 조건별 원자료 집계

{key.to_markdown(index=False)}

## 해석 경계

{scope_boundary}
- 모델, prompt, max tokens, worker concurrency는 동일하게 고정했다.
- block 안의 node×concurrency 조건 순서는 seed `{config.get('seed')}`로 무작위화해 시간·열·공유 클러스터 부하의 순서 편향을 줄였다.

## 그림

- `figures/p95-ttft.png`: 동시성별 p95 TTFT와 1,500ms SLO
- `figures/throughput.png`: 동시성별 완료 처리량
- `figures/p95-latency.png`: 동시성별 client p95 latency
- `figures/p95-queue.png`: 동시성별 관측 queue p95

동시성이 2배씩 증가하므로 그림 x축은 명시적인 log2 scale을 사용한다. 그림은 색상 외 marker와 line style도 함께 사용하며, 동일 표의 CSV가 접근 가능한 원자료 대안이다.
"""
    output.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--activation-csv", type=Path)
    parser.add_argument(
        "--execution-profile",
        choices=("cpu_substitute", "orin_nano_gpu", "x86_gpu_substitute"),
    )
    parser.add_argument("--physical-hardware")
    parser.add_argument("--logical-role")
    args = parser.parse_args()
    requests = pd.read_csv(args.run_dir / "requests.csv")
    resources = pd.read_csv(args.run_dir / "resources.csv")
    config = json.loads((args.run_dir / "run-config.json").read_text(encoding="utf-8"))
    if args.execution_profile:
        config["execution_profile"] = args.execution_profile
    if args.physical_hardware:
        config["physical_hardware"] = args.physical_hardware
    if args.logical_role:
        config["logical_role"] = args.logical_role
    summary = aggregate(requests, resources)
    limits = derive_limits(summary)
    activation_path = args.activation_csv or args.run_dir.parent / "combined" / "tables" / "activation.csv"
    if set(NODES).issubset(set(summary["node"])):
        if not activation_path.exists():
            raise FileNotFoundError(f"activation comparison is required: {activation_path}")
        activation = pd.read_csv(activation_path)
        gates = derive_offload_gates(summary, activation)
    else:
        gates = pd.DataFrame()
    save_table(summary, args.run_dir / "saturation-summary.csv")
    save_table(limits, args.run_dir / "derived-limits.csv")
    save_table(gates, args.run_dir / "offloading-gates.csv")
    figures = args.run_dir / "figures"
    figures.mkdir(exist_ok=True)
    profile = str(config.get("execution_profile") or "cpu_substitute")
    plot(summary, "p95_ttft_ms", "p95 TTFT (ms)", figures / "p95-ttft", slo_line=True, profile=profile)
    plot(summary, "mean_throughput_rps", "Throughput (requests/s)", figures / "throughput", profile=profile)
    plot(summary, "p95_client_latency_ms", "p95 client latency (ms)", figures / "p95-latency", profile=profile)
    plot(summary, "p95_observed_queue_length", "p95 observed queue length", figures / "p95-queue", profile=profile)
    render_report(summary, limits, gates, args.run_dir / "report.md", config)
    (args.run_dir / "analysis-config.json").write_text(
        json.dumps(
            {
                "execution_profile": profile,
                "ttft_slo_ms": SLO_TTFT_MS,
                "queue_high": (
                    8
                    if profile == "orin_nano_gpu"
                    else int(limits.iloc[0]["slo_capacity_concurrency"])
                    if profile == "x86_gpu_substitute"
                    else 1
                ),
                "input_requests": "requests.csv",
                "input_resources": "resources.csv",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (figures / "README.md").write_text(
        """# 그림 설명\n\n"
        "- `p95-ttft`: 동시성 증가에 따른 p95 TTFT. 회색 점선은 1,500ms SLO다.\n"
        "- `throughput`: 동시성 증가에 따른 완료 요청 처리량이다.\n"
        "- `p95-latency`: 동시성 증가에 따른 전체 요청 p95 지연시간이다.\n"
        "- `p95-queue`: 동시성 증가에 따른 관측 queue length p95다.\n\n"
        "색상에만 의존하지 않도록 marker와 선 모양을 함께 사용했다. 정확한 수치는 "
        "상위 폴더의 `saturation-summary.csv`에서 확인한다.\n""",
        encoding="utf-8",
    )
    print(json.dumps({"limits": limits.to_dict(orient="records"), "offloading_gates": gates.to_dict(orient="records")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
