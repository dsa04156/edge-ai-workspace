from __future__ import annotations

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

    async def record_snapshot(self, service_profiles: list[dict[str, Any]]) -> bool:
        if not self.token:
            logger.warning("InfluxDB token is not configured; skipping service resource profile write")
            return False
        lines = self._service_profile_lines(service_profiles)
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
            logger.exception("Failed to write service resource profile events to InfluxDB")
            return False

    def _service_profile_lines(self, service_profiles: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for profile in service_profiles:
            ts = self._timestamp_ns(profile.get("generated_at"))
            requirements = profile.get("resource_requirements") or {}
            requests = requirements.get("requests") or {}
            limits = requirements.get("limits") or {}
            missing = requirements.get("missing") or {}
            tags = {
                "namespace": profile.get("namespace"),
                "service": profile.get("service"),
                "profile_type": profile.get("profile_type") or "running_service_resource_requirements",
                "requirements_declared": str(bool(profile.get("requirements_declared"))).lower(),
                "event": "service_resource_profile",
            }
            fields = {
                "pod_count": profile.get("pod_count"),
                "container_count": profile.get("container_count"),
                "request_coverage_ratio": profile.get("request_coverage_ratio"),
                "limit_coverage_ratio": profile.get("limit_coverage_ratio"),
                "request_cpu_cores": requests.get("cpu_cores"),
                "request_memory_mib": requests.get("memory_mib"),
                "limit_cpu_cores": limits.get("cpu_cores"),
                "limit_memory_mib": limits.get("memory_mib"),
                "limit_gpu_units": limits.get("gpu_units"),
                "current_cpu_usage_cores": (profile.get("current_usage") or {}).get("cpu_cores"),
                "current_memory_working_set_mib": (profile.get("current_usage") or {}).get("memory_working_set_mib"),
                "usage_sampled_container_count": (profile.get("current_usage") or {}).get("sampled_container_count"),
                "usage_coverage_ratio": (profile.get("current_usage") or {}).get("usage_coverage_ratio"),
                "missing_cpu_request_containers": missing.get("cpu_request_containers"),
                "missing_memory_request_containers": missing.get("memory_request_containers"),
                "missing_cpu_limit_containers": missing.get("cpu_limit_containers"),
                "missing_memory_limit_containers": missing.get("memory_limit_containers"),
                "nodes": ",".join(profile.get("nodes") or []),
                "interpretation": profile.get("interpretation"),
            }
            lines.append(self._line("service_resource_profile_events", tags, fields, ts))
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
