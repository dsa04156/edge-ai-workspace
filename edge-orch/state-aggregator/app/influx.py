from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetrySample:
    device_id: str
    timestamp: datetime
    property: str | None = None
    value: str | float | int | bool | None = None


class InfluxTelemetryClient:
    def __init__(
        self,
        url: str,
        org: str,
        bucket: str,
        token: str | None,
        measurement: str,
        query_window: str,
    ) -> None:
        self.url = url.rstrip("/")
        self.org = org
        self.bucket = bucket
        self.token = token
        self.measurement = measurement
        self.query_window = query_window

    async def get_latest_by_device(self) -> dict[str, TelemetrySample]:
        if not self.token:
            logger.warning("InfluxDB token is not configured; skipping telemetry freshness query")
            return {}

        flux = f'''
from(bucket: "{self._escape_flux_string(self.bucket)}")
  |> range(start: {self.query_window})
  |> filter(fn: (r) => r._measurement == "{self._escape_flux_string(self.measurement)}")
  |> filter(fn: (r) => exists r.device_id)
  |> group(columns: ["device_id"])
  |> last()
  |> keep(columns: ["device_id", "property", "_time", "_value"])
'''
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.url}/api/v2/query",
                    params={"org": self.org},
                    headers={
                        "Authorization": f"Token {self.token}",
                        "Accept": "application/csv",
                        "Content-Type": "application/vnd.flux",
                    },
                    content=flux,
                )
                response.raise_for_status()
        except Exception:
            logger.exception("Failed to query InfluxDB telemetry")
            return {}

        return self._parse_csv(response.text)

    def _parse_csv(self, content: str) -> dict[str, TelemetrySample]:
        samples: dict[str, TelemetrySample] = {}
        data_lines = [
            line
            for line in content.splitlines()
            if line and not line.startswith("#") and not line.startswith(",result,table")
        ]
        if not data_lines:
            return samples

        reader = csv.DictReader(StringIO("\n".join(data_lines)))
        for row in reader:
            device_id = row.get("device_id")
            timestamp_text = row.get("_time")
            if not device_id or not timestamp_text:
                continue
            timestamp = self._parse_time(timestamp_text)
            if timestamp is None:
                continue
            value: Any = row.get("_value")
            samples[device_id] = TelemetrySample(
                device_id=device_id,
                timestamp=timestamp,
                property=row.get("property") or None,
                value=value,
            )
        return samples

    def _parse_time(self, value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            logger.warning("Failed to parse InfluxDB timestamp: %s", value)
            return None

    def _escape_flux_string(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')
