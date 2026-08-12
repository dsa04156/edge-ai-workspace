from __future__ import annotations

from .models import AccelerationFrame, AxisName, AxisSample, JoinCounters


AXES: frozenset[AxisName] = frozenset({"x", "y", "z"})


class FrameJoiner:
    """Join independently queried axis samples without crossing origins."""

    def __init__(self, pending_ttl_ns: int, max_pending: int) -> None:
        if pending_ttl_ns <= 0:
            raise ValueError("pending_ttl_ns must be positive")
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self.pending_ttl_ns = pending_ttl_ns
        self.max_pending = max_pending
        self.counters = JoinCounters()
        self._pending: dict[int, dict[AxisName, int]] = {}
        self._pending_seen_at: dict[int, int] = {}
        self._processed_seen_at: dict[int, int] = {}

    def ingest(
        self,
        axis: AxisName,
        samples: list[AxisSample],
        now_ns: int,
    ) -> list[AccelerationFrame]:
        if axis not in AXES:
            raise ValueError(f"unsupported axis: {axis}")

        self._evict(now_ns)
        frames: list[AccelerationFrame] = []
        for sample in samples:
            if sample.origin in self._processed_seen_at:
                self.counters.duplicates_ignored += 1
                continue

            values = self._pending.setdefault(sample.origin, {})
            self._pending_seen_at.setdefault(sample.origin, now_ns)
            if axis in values:
                self.counters.duplicates_ignored += 1
            values[axis] = sample.value

            if set(values) != AXES:
                continue

            frames.append(
                AccelerationFrame(
                    origin=sample.origin,
                    x=values["x"],
                    y=values["y"],
                    z=values["z"],
                )
            )
            self._pending.pop(sample.origin)
            self._pending_seen_at.pop(sample.origin)
            self._processed_seen_at[sample.origin] = now_ns

        self._evict(now_ns)
        return sorted(frames, key=lambda item: item.origin)

    @property
    def pending_origins(self) -> list[int]:
        return sorted(self._pending)

    def _evict(self, now_ns: int) -> None:
        cutoff = now_ns - self.pending_ttl_ns
        expired = {
            origin
            for origin, first_seen_at in self._pending_seen_at.items()
            if first_seen_at < cutoff
        }
        survivors = [origin for origin in sorted(self._pending) if origin not in expired]
        capacity_excess = max(0, len(survivors) - self.max_pending)

        for origin in [*sorted(expired), *survivors[:capacity_excess]]:
            self._pending.pop(origin, None)
            self._pending_seen_at.pop(origin, None)
            self.counters.incomplete_frames_dropped += 1

        for origin, processed_at in list(self._processed_seen_at.items()):
            if processed_at < cutoff:
                self._processed_seen_at.pop(origin)
