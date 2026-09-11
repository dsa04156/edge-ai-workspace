"""Plot all 126 existing conditions; no inference execution or raw-data mutation."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

NODES = {"nano": "Orin Nano", "agx": "AGX Orin", "spark": "DGX Spark"}
COLORS = ["#0072B2", "#9B4F00", "#7030A0"]
MARKERS = ["o", "s", "^"]
MODELS = [
    ("qwen2.5:0.5b-instruct-q8_0", "Qwen 2.5 0.5B"),
    ("llama3.2:1b-instruct-q8_0", "Llama 3.2 1B"),
    ("qwen2.5:1.5b-instruct-q8_0", "Qwen 2.5 1.5B"),
    ("gemma2:2b-instruct-q8_0", "Gemma 2 2B"),
    ("qwen2.5:3b-instruct-q8_0", "Qwen 2.5 3B"),
    ("llama3.2:3b-instruct-q8_0", "Llama 3.2 3B"),
]
CONCURRENCY = [f"i512-o128-c{c}" for c in [1, 2, 4, 8]]
LENGTHS = ["i128-o64-c1", "i512-o128-c1", "i2048-o128-c1", "i512-o256-c1"]


def main(source, output):
    output.mkdir(parents=True, exist_ok=True)
    data = json.loads(source.read_text())
    rows = data["conditions"]
    lookup = {(r["node"], r["model"], r["case"]): r for r in rows}
    expected = {(node, model, case) for node in NODES for model, _ in MODELS
                for case in set(CONCURRENCY + LENGTHS)}
    assert set(lookup) == expected and len(rows) == 126
    assert all(r["success"] == r["requests"] and r["blocks"] == 3 for r in rows)
    for r in rows:
        assert r["requests"] == 3 * int(r["case"].rsplit("c", 1)[1])
    font_manager.fontManager.addfont("/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf")
    style = {"font.family": "UnDotum", "font.size": 13, "axes.titlesize": 16,
             "axes.labelsize": 13, "axes.unicode_minus": False, "svg.fonttype": "path"}
    charts = [
        ("concurrency-latency", CONCURRENCY, "p50_latency_ms", 1000,
         "요청을 한꺼번에 많이 보내면 얼마나 기다릴까?", "전체 응답시간 중앙값 (초 · 낮을수록 빠름)",
         ["1개", "2개", "4개", "8개"], "한꺼번에 보내는 요청 수", True),
        ("token-length-latency", LENGTHS, "p50_latency_ms", 1000,
         "입력·출력이 길어지면 얼마나 걸릴까?", "전체 응답시간 중앙값 (초 · 낮을수록 빠름)",
         ["128→64\n짧은 요청", "512→128\n기본", "2048→128\n긴 입력", "512→256\n긴 출력"], "입력 토큰 → 출력 토큰", True),
        ("concurrency-throughput", CONCURRENCY, "active_wave_output_tokens_s", 1,
         "요청 수를 늘리면 초당 처리량도 늘어날까?", "출력 토큰/s (높을수록 처리량 큼)",
         ["1개", "2개", "4개", "8개"], "한꺼번에 보내는 요청 수", False),
    ]
    outputs = []
    with plt.rc_context(style):
        for stem, cases, metric, divisor, title, ylabel, labels, xlabel, spread in charts:
            fig, axes = plt.subplots(2, 3, figsize=(16, 10), sharey=True)
            fig.subplots_adjust(left=.065, right=.985, bottom=.17, top=.83, hspace=.50, wspace=.17)
            largest = max(lookup[node, model, case]["max_latency_ms" if spread else metric] / divisor
                          for node in NODES for model, _ in MODELS for case in cases)
            for ax, (model, name) in zip(axes.flat, MODELS):
                for ni, (node, device) in enumerate(NODES.items()):
                    group = [lookup[node, model, case] for case in cases]
                    vals = np.array([r[metric] / divisor for r in group])
                    x = np.arange(4, dtype=float)
                    if spread:
                        x += (ni - 1) * .075
                        low = np.array([r["min_latency_ms"] / divisor for r in group])
                        high = np.array([r["max_latency_ms"] / divisor for r in group])
                        ax.errorbar(x, vals, yerr=[vals - low, high - vals], color=COLORS[ni],
                                    marker=MARKERS[ni], markersize=6, linewidth=1.8, elinewidth=.8,
                                    capsize=3, label=device, linestyle="-" if cases == CONCURRENCY else "none")
                    else:
                        ax.plot(x, vals, color=COLORS[ni], marker=MARKERS[ni], markersize=6,
                                linewidth=1.8, label=device)
                ax.set_title(name, loc="left", fontweight="bold")
                ax.set_xticks(range(4), labels)
                ax.set_xlabel(xlabel)
                ax.set_ylim(0, largest * 1.08)
                ax.set_xlim(-.25, 3.25)
                ax.grid(axis="y", color="#dddddd", linewidth=.7)
                ax.set_axisbelow(True)
                ax.spines[["top", "right"]].set_visible(False)
            for ax in axes[:, 0]:
                ax.set_ylabel(ylabel)
            handles, legend_labels = axes[0, 0].get_legend_handles_labels()
            fig.legend(handles, legend_labels, loc="upper center", bbox_to_anchor=(.5, .92), ncol=3, frameon=False)
            fig.suptitle(title, fontsize=23, fontweight="bold", y=.99)
            if stem == "token-length-latency":
                note = "조건마다 요청 1개 × 3회차 (n=3) · 점: 중앙값 / 세로선: 관측 최솟값~최댓값 (신뢰구간 아님)"
            elif spread:
                note = "입력 512 / 출력 128토큰 · 요청 수별 표본 n=3·6·12·24 · 점: 중앙값 / 세로선: 최솟값~최댓값 (대기 포함)"
            else:
                note = "입력 512 / 출력 128토큰 · 처리량 = 성공 출력 토큰 수 ÷ 세 요청 묶음의 실제 소요시간 합"
            fig.text(.5, .065, note, ha="center", fontsize=12)
            fig.text(.5, .030, "Q8_0 · 슬롯 1개 · 2026-09-10 실측 · 후속 27개 실행은 조건 전 냉각 대기 적용; 냉각·적재 시간 제외", ha="center", fontsize=12)
            for ext in ["png", "svg"]:
                dest = output / f"{stem}.{ext}"
                fig.savefig(dest, dpi=150, facecolor="white")
                outputs.append({"file": dest.name, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
            plt.close(fig)
    columns = ["node", "model", "case", "requests", "success", "failures", "blocks", "p50_latency_ms",
               "p95_latency_ms", "min_latency_ms", "max_latency_ms", "p95_ttft_ms", "median_decode_tokens_s",
               "active_wave_requests_s", "active_wave_output_tokens_s"]
    with (output / "all-conditions.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: r[key] for key in columns} for r in rows)
    table = ["## 9. 전체 126개 조건 결과", "", "- 시간 단위: 초 / 처리량: 출력 토큰/s", "- 조건 표기: 입력 토큰 → 출력 토큰 / 한꺼번에 보내는 요청 수", "- 중앙값·표본 p95: 대기 포함 / 표본 수: 같은 세션의 세 회차 합계", "- p95는 작은 표본의 기술통계; 운영 보장값으로 해석 불가", ""]
    for node, name in NODES.items():
        table += [f"### {name}", "", "| 모델 | 입력→출력 | 요청 수 | 표본 수 | 응답 중앙값 | 응답 p95 | 첫 응답 p95 | 출력 토큰/s |", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for model, label in MODELS:
            for case in [CONCURRENCY[0], *CONCURRENCY[1:], LENGTHS[0], LENGTHS[2], LENGTHS[3]]:
                r = lookup[node, model, case]
                inp, out, count = case.split("-")
                table.append(f"| {label} | {inp[1:]}→{out[1:]} | {count[1:]} | {r['requests']} | {r['p50_latency_ms']/1000:.3f} | {r['p95_latency_ms']/1000:.3f} | {r['p95_ttft_ms']/1000:.3f} | {r['active_wave_output_tokens_s']:.3f} |")
        table.append("")
    (output / "all-conditions-table.txt").write_text("\n".join(table) + "\n")
    for name in ["all-conditions.csv", "all-conditions-table.txt"]:
        outputs.append({"file": name, "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest()})
    (output / "all-figures-provenance.json").write_text(json.dumps({
        "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "condition_count": len(rows), "latency_condition_coverage": len(expected),
        "transformations": ["read existing condition aggregates", "milliseconds / 1000 for seconds", "no smoothing or new exclusion"],
        "spread": "observed request minimum-to-maximum, not confidence intervals",
        "latency_estimator": "pooled request median; same-session n=3 times concurrency",
        "throughput": "success output tokens divided by sum of three actual wave durations; not median decode speed",
        "missing": "reject missing, duplicate or incomplete conditions; never replace with zero",
        "limitations": "slot1; memory limits5/8/8GiB; 27 cooled continuation cells; cooling/loading excluded; no sustained-capacity/quality claim",
        "figure_inches": [16, 10], "dpi": 150, "font": "UnDotum", "matplotlib": matplotlib.__version__, "numpy": np.__version__,
        "outputs": outputs, "audience": "project docs and conversation", "publisher": "not a journal submission"
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"Rendered 3 charts, 6 images, and all {len(rows)} conditions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.source, args.output)
