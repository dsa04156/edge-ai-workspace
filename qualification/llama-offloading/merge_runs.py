"""Merge method-specific raw CSV directories without changing observations."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def merge(filename: str, inputs: list[Path], output: Path) -> None:
    rows: list[dict[str, str]] = []
    fields: list[str] = []
    for directory in inputs:
        path = directory / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if filename == "requests.csv":
                    aliases = {
                        "gpu_util": "gpu_utilization_percent",
                        "gpu_memory_used": "gpu_memory_used_mib",
                        "TTFT": "ttft_ms",
                        "RTT": "rtt_ms",
                        "activation_time": "activation_time_ms",
                        "model_load_time": "model_load_ms",
                        "actual_latency": "actual_latency_ms",
                    }
                    for alias, source in aliases.items():
                        row[alias] = row.get(source, "")
                rows.append(row)
                for field in row:
                    if field not in fields:
                        fields.append(field)
    output.mkdir(parents=True, exist_ok=True)
    with (output / filename).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    for filename in ("requests.csv", "resources.csv", "events.csv"):
        merge(filename, args.inputs, args.output_dir)


if __name__ == "__main__":
    main()
