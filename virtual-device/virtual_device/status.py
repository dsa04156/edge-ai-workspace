from __future__ import annotations

import json
from dataclasses import dataclass

from .config import DeviceProfile


@dataclass
class RuntimeStatus:
    virtual_device_id: str
    physical_device_id: str
    phase: str = "starting"
    connection: str = "unknown"
    data_status: str = "unknown"
    last_seen_at: int | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "virtualDeviceId": self.virtual_device_id,
            "physicalDeviceId": self.physical_device_id,
            "phase": self.phase,
            "connection": self.connection,
            "dataStatus": self.data_status,
            "lastSeenAt": self.last_seen_at,
            "lastError": self.last_error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class RuntimeStatusTracker:
    def __init__(self, profile: DeviceProfile) -> None:
        self.status = RuntimeStatus(
            virtual_device_id=profile.virtual_device_id,
            physical_device_id=profile.physical_device_id,
        )

    def mark_connected(self) -> bool:
        return self._transition(phase="running", connection="connected", last_error=None)

    def mark_sample(self, *, collected_at: int, valid: bool, errors: tuple[str, ...]) -> bool:
        return self._transition(
            phase="running" if valid else "degraded",
            connection="connected",
            data_status="fresh",
            last_seen_at=collected_at,
            last_error=None if valid else "; ".join(errors),
            ignore_last_seen_for_change=True,
        )

    def mark_invalid_sample(self, error: str) -> bool:
        data_status = self.status.data_status if self.status.last_seen_at is not None else "stale"
        return self._transition(
            phase="degraded",
            connection="connected",
            data_status=data_status,
            last_error=error,
        )

    def mark_disconnected(self, error: str) -> bool:
        return self._transition(
            phase="degraded",
            connection="disconnected",
            data_status="stale",
            last_error=error,
        )

    def refresh_freshness(
        self,
        *,
        now: float,
        connected_since: float | None,
        offline_after_seconds: float,
    ) -> bool:
        freshness_reference = self.status.last_seen_at
        if freshness_reference is None:
            freshness_reference = connected_since
        if freshness_reference is None or now - freshness_reference < offline_after_seconds:
            return False
        return self._transition(
            phase="degraded",
            data_status="stale",
            last_error=f"no fresh data for {int(offline_after_seconds)} seconds",
        )

    def mark_failed(self, error: str) -> bool:
        return self._transition(
            phase="failed",
            connection="disconnected",
            data_status="stale",
            last_error=error,
        )

    def mark_stopped(self) -> bool:
        return self._transition(
            phase="stopped",
            connection="disconnected",
            data_status="stale",
        )

    def _transition(
        self,
        *,
        phase: str | None = None,
        connection: str | None = None,
        data_status: str | None = None,
        last_seen_at: int | None = None,
        last_error: str | None = None,
        ignore_last_seen_for_change: bool = False,
    ) -> bool:
        before = self._state_key(ignore_last_seen=ignore_last_seen_for_change)
        if phase is not None:
            self.status.phase = phase
        if connection is not None:
            self.status.connection = connection
        if data_status is not None:
            self.status.data_status = data_status
        if last_seen_at is not None:
            self.status.last_seen_at = last_seen_at
        self.status.last_error = last_error
        return before != self._state_key(ignore_last_seen=ignore_last_seen_for_change)

    def _state_key(self, *, ignore_last_seen: bool) -> tuple[object, ...]:
        values: tuple[object, ...] = (
            self.status.phase,
            self.status.connection,
            self.status.data_status,
            self.status.last_error,
        )
        if ignore_last_seen:
            return values
        return values + (self.status.last_seen_at,)
