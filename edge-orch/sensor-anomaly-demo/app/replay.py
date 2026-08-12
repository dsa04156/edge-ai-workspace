from __future__ import annotations

import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import ValidationError

from .contracts import PumpMotorTelemetry
from .local_data import ACCELERATION_SOURCES, TEMPERATURE_SOURCE, LocalDataSource
from .models import AxisSample


class ReplayDatasetError(ValueError):
    """The replay file is unreadable or violates the pump telemetry contract."""


@dataclass(frozen=True)
class ReplaySeries:
    source: LocalDataSource
    samples: tuple[AxisSample, ...]


class PumpReplayDataset:
    def __init__(
        self,
        records: Iterable[PumpMotorTelemetry],
        *,
        rebase_origin_ns: int | None = None,
    ) -> None:
        ordered = sorted(records, key=lambda item: item.observed_at)
        if not ordered:
            raise ReplayDatasetError("replay dataset must contain at least one record")
        event_ids = [item.event_id for item in ordered]
        if len(event_ids) != len(set(event_ids)):
            raise ReplayDatasetError("replay eventId values must be unique")

        first_origin = int(ordered[0].observed_at.timestamp() * 1_000_000_000)
        origins = [
            int(record.observed_at.timestamp() * 1_000_000_000) for record in ordered
        ]
        if rebase_origin_ns is not None:
            origins = [rebase_origin_ns + (origin - first_origin) for origin in origins]

        source_values = {
            "x": [record.signals.acceleration_x.value for record in ordered],
            "y": [record.signals.acceleration_y.value for record in ordered],
            "z": [record.signals.acceleration_z.value for record in ordered],
            "temperature": [record.signals.temperature.value for record in ordered],
        }
        sources = (*ACCELERATION_SOURCES, TEMPERATURE_SOURCE)
        self.records = tuple(ordered)
        self._series = {
            (source.device_name, source.resource_name): ReplaySeries(
                source=source,
                samples=tuple(
                    AxisSample(origin=origin, value_type="Float64", value=value)
                    for origin, value in zip(
                        origins,
                        source_values[source.key],
                        strict=True,
                    )
                ),
            )
            for source in sources
        }

    @classmethod
    def from_jsonl(
        cls,
        content: str,
        *,
        rebase_origin_ns: int | None = None,
    ) -> PumpReplayDataset:
        records: list[PumpMotorTelemetry] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(PumpMotorTelemetry.model_validate_json(line))
            except (ValidationError, ValueError) as exc:
                raise ReplayDatasetError(
                    f"replay line {line_number} failed schema validation"
                ) from exc
        return cls(records, rebase_origin_ns=rebase_origin_ns)

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        rebase_origin_ns: int | None = None,
    ) -> PumpReplayDataset:
        selected = Path(path)
        try:
            content = selected.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReplayDatasetError("replay file could not be read") from exc
        return cls.from_jsonl(content, rebase_origin_ns=rebase_origin_ns)

    def series(self, device_name: str, resource_name: str) -> ReplaySeries | None:
        return self._series.get((device_name, resource_name))

    @property
    def first_origin(self) -> int:
        return min(series.samples[0].origin for series in self._series.values())

    @property
    def last_origin(self) -> int:
        return max(series.samples[-1].origin for series in self._series.values())


def create_replay_app(dataset: PumpReplayDataset) -> FastAPI:
    application = FastAPI(
        title="okdong-pump-data-replay",
        version="1.0.0",
    )

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/v1/replay/status")
    async def status() -> dict[str, int | str]:
        return {
            "schemaVersion": "okdong.pump-motor.telemetry/v1",
            "recordCount": len(dataset.records),
            "firstOrigin": dataset.first_origin,
            "lastOrigin": dataset.last_origin,
        }

    @application.get(
        "/api/v3/localdata/device/name/{device_name}/resource/name/{resource_name}"
    )
    async def local_data(
        device_name: str,
        resource_name: str,
        from_origin: int | None = Query(default=None, alias="from", ge=1),
        to_origin: int | None = Query(default=None, alias="to", ge=1),
        limit: int = Query(default=1_000, ge=1, le=1_000),
    ) -> dict:
        series = dataset.series(device_name, resource_name)
        if series is None:
            raise HTTPException(status_code=404, detail="replay source was not found")
        rows = [
            sample
            for sample in series.samples
            if (from_origin is None or sample.origin >= from_origin)
            and (to_origin is None or sample.origin <= to_origin)
        ][:limit]
        return {
            "apiVersion": "v3",
            "statusCode": 200,
            "deviceName": device_name,
            "resourceName": resource_name,
            "count": len(rows),
            "retention": {
                "maxAge": "replay-dataset",
                "maxSamples": len(series.samples),
            },
            "samples": [
                {
                    "origin": row.origin,
                    "valueType": row.value_type,
                    "value": row.value,
                }
                for row in rows
            ],
        }

    return application


def create_app_from_env() -> FastAPI:
    replay_file = os.getenv("REPLAY_FILE", "").strip()
    if not replay_file:
        raise RuntimeError("REPLAY_FILE is required")
    rebase = os.getenv("REPLAY_REBASE_TO_NOW", "true").strip().lower()
    if rebase not in {"true", "false"}:
        raise RuntimeError("REPLAY_REBASE_TO_NOW must be true or false")
    dataset = PumpReplayDataset.from_path(
        replay_file,
        rebase_origin_ns=time.time_ns() if rebase == "true" else None,
    )
    return create_replay_app(dataset)
