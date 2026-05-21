from __future__ import annotations

import fnmatch
import os
from typing import Any


class RedisLatestTelemetryClient:
    def __init__(self, redis_url: str, latest_prefix: str = "telemetry:latest") -> None:
        self.redis_url = redis_url
        self.latest_prefix = latest_prefix
        self._client = None

    def _redis(self):
        if self._client is not None:
            return self._client
        try:
            import redis  # type: ignore
        except ImportError:
            return None
        self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def get_latest(self) -> list[dict[str, Any]]:
        client = self._redis()
        if client is None:
            return []
        pattern = f"{self.latest_prefix}:*"
        rows: list[dict[str, Any]] = []
        try:
            keys = client.scan_iter(match=pattern, count=200)
            for key in keys:
                data = client.hgetall(key)
                if not data:
                    continue
                data.setdefault("redis_key", key)
                rows.append(data)
        except Exception:
            return []
        rows.sort(key=lambda item: (item.get("device_id", ""), item.get("sensor", "")))
        return rows


def is_raw_telemetry_property(name: str | None) -> bool:
    if not name:
        return False
    normalized = name.lower()
    explicit = {
        "raw",
        "value",
        "x",
        "y",
        "z",
        "temperature",
        "humidity",
        "vibration",
        "acceleration",
        "light",
        "magnetic",
        "pressure",
        "current",
        "voltage",
    }
    if normalized in explicit:
        return True
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in ("*_raw", "*_value", "temp*", "vib*"))


def redis_url_from_env() -> str:
    return os.getenv("REDIS_URL", "redis://redis.telemetry.svc.cluster.local:6379/0")
