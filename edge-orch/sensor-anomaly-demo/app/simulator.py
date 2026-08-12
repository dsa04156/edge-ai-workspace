from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

from .contracts import Measurement, PumpMotorSignals, PumpMotorTelemetry


def generate_pump_samples(
    *,
    count: int,
    interval_ms: int,
    anomaly_start: int | None,
    anomaly_length: int,
    asset_id: str,
    device_id: str,
    start: datetime,
    seed: int,
) -> list[PumpMotorTelemetry]:
    if count < 1:
        raise ValueError("count must be positive")
    if interval_ms < 1:
        raise ValueError("interval_ms must be positive")
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must include a timezone")
    if anomaly_start is not None and not 0 <= anomaly_start < count:
        raise ValueError("anomaly_start must be inside the generated range")
    if anomaly_length < 1:
        raise ValueError("anomaly_length must be positive")

    randomizer = random.Random(seed)
    records: list[PumpMotorTelemetry] = []
    for index in range(count):
        anomalous = (
            anomaly_start is not None
            and anomaly_start <= index < anomaly_start + anomaly_length
        )
        oscillation = math.sin(index / 3.0) * 2.0
        multiplier = 8.0 if anomalous else 1.0
        noise = lambda: randomizer.uniform(-0.35, 0.35)
        records.append(
            PumpMotorTelemetry(
                event_id=f"sim-{asset_id}-{index:06d}",
                source_type="simulator",
                device_id=device_id,
                asset_id=asset_id,
                node_id="simulated-edge-node",
                observed_at=start + timedelta(milliseconds=interval_ms * index),
                signals=PumpMotorSignals(
                    acceleration_x=Measurement(
                        value=(100.0 + oscillation + noise()) * multiplier,
                        unit="raw",
                    ),
                    acceleration_y=Measurement(
                        value=(98.0 - oscillation + noise()) * multiplier,
                        unit="raw",
                    ),
                    acceleration_z=Measurement(
                        value=(101.0 + noise()) * multiplier,
                        unit="raw",
                    ),
                    temperature=Measurement(
                        value=300.0 + index * 0.02 + (35.0 if anomalous else 0.0),
                        unit="raw",
                    ),
                ),
                attributes={"fixture": "deterministic-pump-v1"},
            )
        )
    return records


def write_jsonl(records: list[PumpMotorTelemetry], output: TextIO) -> None:
    for record in records:
        output.write(
            json.dumps(
                record.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        output.write("\n")


def _parse_start(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--start must include a timezone")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate contract-valid Okdong pump/motor replay JSONL.",
    )
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--anomaly-start", type=int, default=80)
    parser.add_argument("--anomaly-length", type=int, default=10)
    parser.add_argument("--asset-id", default="virtual-pump-001")
    parser.add_argument("--device-id", default="pump-simulator-001")
    parser.add_argument(
        "--start",
        type=_parse_start,
        default=datetime.now(timezone.utc),
    )
    parser.add_argument("--seed", type=int, default=20260803)
    parser.add_argument("--output", default="-")
    args = parser.parse_args(argv)

    records = generate_pump_samples(
        count=args.count,
        interval_ms=args.interval_ms,
        anomaly_start=args.anomaly_start,
        anomaly_length=args.anomaly_length,
        asset_id=args.asset_id,
        device_id=args.device_id,
        start=args.start,
        seed=args.seed,
    )
    if args.output == "-":
        write_jsonl(records, sys.stdout)
        return 0
    selected = Path(args.output)
    with selected.open("w", encoding="utf-8") as output:
        write_jsonl(records, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
