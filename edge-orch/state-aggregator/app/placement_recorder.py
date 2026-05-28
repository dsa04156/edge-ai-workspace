from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class InfluxResourceProfileRecorder:
    def __init__(self, url: str, org: str, bucket: str, token: str | None) -> None:
        self.url = url.rstrip("/")
        self.org = org
        self.bucket = bucket
        self.token = token

    async def record_snapshot(self, node_profiles: list[dict], placement_advice: list[dict]) -> bool:
        if not self.token:
            logger.warning("InfluxDB token is not configured; skipping resource profile event write")
            return False
        lines = self._node_profile_lines(node_profiles) + self._placement_advice_lines(placement_advice)
        if not lines:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.url}/api/v2/write",
                    params={"org": self.org, "bucket": self.bucket, "precision": "ns"},
                    headers={
                        "Authorization": f"Token {self.token}",
                        "Content-Type": "text/plain; charset=utf-8",
                    },
                    content="\n".join(lines),
                )
                response.raise_for_status()
                return True
        except Exception:
            logger.exception("Failed to write resource profile events to InfluxDB")
            return False

    def _node_profile_lines(self, node_profiles: list[dict]) -> list[str]:
        lines: list[str] = []
        for profile in node_profiles:
            ts = self._timestamp_ns(profile.get("generated_at"))
            tags = {
                "node": profile.get("node"),
                "node_type": profile.get("node_type") or "unknown",
                "status": profile.get("status") or "unknown",
                "event": "resource_profile",
            }
            cpu = profile.get("cpu") or {}
            memory = profile.get("memory") or {}
            gpu = profile.get("gpu") or {}
            network = profile.get("network") or {}
            fields = {
                "cpu_usage_ratio": cpu.get("usage_ratio"),
                "cpu_available_ratio": cpu.get("available_ratio"),
                "memory_usage_ratio": memory.get("usage_ratio"),
                "memory_available_ratio": memory.get("available_ratio"),
                "gpu_available": bool(gpu.get("available")),
                "gpu_utilization_ratio": gpu.get("utilization_ratio"),
                "gpu_memory_free_mib": gpu.get("memory_free_mib"),
                "gpu_memory_total_mib": gpu.get("memory_total_mib"),
                "network_rx_mbps": network.get("rx_mbps"),
                "network_tx_mbps": network.get("tx_mbps"),
                "cpu_pressure": cpu.get("pressure"),
                "memory_pressure": memory.get("pressure"),
                "gpu_pressure": gpu.get("pressure"),
                "network_pressure": network.get("pressure"),
            }
            lines.append(self._line("resource_profile_events", tags, fields, ts))
        return [line for line in lines if line]

    def _placement_advice_lines(self, placement_advice: list[dict]) -> list[str]:
        lines: list[str] = []
        for advice in placement_advice:
            ts = self._timestamp_ns(advice.get("generated_at"))
            for candidate in advice.get("candidates") or []:
                tags = {
                    "service": advice.get("service"),
                    "stage": advice.get("stage"),
                    "node": candidate.get("node"),
                    "node_type": candidate.get("node_type") or "unknown",
                    "decision": candidate.get("decision") or "unknown",
                    "event": "placement_advice",
                }
                fields = {
                    "score": candidate.get("score"),
                    "best_node": candidate.get("node") == advice.get("best_node"),
                    "reason": "; ".join(candidate.get("reasons") or []),
                    "requirements": json.dumps(advice.get("requirements") or {}, ensure_ascii=False, sort_keys=True),
                }
                lines.append(self._line("placement_advice_events", tags, fields, ts))
        return [line for line in lines if line]

    def _line(self, measurement: str, tags: dict[str, Any], fields: dict[str, Any], timestamp_ns: int) -> str:
        tag_text = ",".join(
            f"{self._escape_tag(str(key))}={self._escape_tag(str(value))}"
            for key, value in tags.items()
            if value not in (None, "")
        )
        field_text = ",".join(
            f"{self._escape_field_key(str(key))}={self._format_field(value)}"
            for key, value in fields.items()
            if value is not None
        )
        if not field_text:
            return ""
        return f"{self._escape_measurement(measurement)},{tag_text} {field_text} {timestamp_ns}"

    def _timestamp_ns(self, value: Any) -> int:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)

    def _format_field(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int) and not isinstance(value, bool):
            return f"{value}i"
        if isinstance(value, float):
            return str(value)
        return f'"{str(value).replace(chr(92), chr(92) + chr(92)).replace(chr(34), chr(92) + chr(34))}"'

    def _escape_measurement(self, value: str) -> str:
        return value.replace(" ", "\\ ").replace(",", "\\,")

    def _escape_tag(self, value: str) -> str:
        return value.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")

    def _escape_field_key(self, value: str) -> str:
        return self._escape_tag(value)
