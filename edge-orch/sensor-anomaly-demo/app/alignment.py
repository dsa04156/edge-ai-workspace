from __future__ import annotations

from dataclasses import dataclass

from .models import AccelerationFrame, AxisSample


@dataclass(frozen=True)
class AlignedSensorFrame:
    acceleration: AccelerationFrame
    temperature: AxisSample


@dataclass
class AlignmentCounters:
    unaligned_frames_dropped: int = 0


class TemporalAligner:
    """Join asynchronous sensor streams by bounded event-time proximity."""

    def __init__(
        self,
        max_skew_ns: int,
        pending_ttl_ns: int,
        max_pending: int,
    ) -> None:
        if max_skew_ns <= 0:
            raise ValueError("max_skew_ns must be positive")
        if pending_ttl_ns < max_skew_ns:
            raise ValueError("pending_ttl_ns must be at least max_skew_ns")
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self.max_skew_ns = max_skew_ns
        self.pending_ttl_ns = pending_ttl_ns
        self.max_pending = max_pending
        self.counters = AlignmentCounters()
        self._contexts: dict[int, AxisSample] = {}
        self._pending: dict[int, tuple[AccelerationFrame, int]] = {}

    def ingest(
        self,
        frames: list[AccelerationFrame],
        temperatures: list[AxisSample],
        now_ns: int,
    ) -> list[AlignedSensorFrame]:
        for sample in temperatures:
            self._contexts[sample.origin] = sample
        for frame in frames:
            self._pending.setdefault(frame.origin, (frame, now_ns))

        self._evict(now_ns)
        aligned: list[AlignedSensorFrame] = []
        for origin in sorted(self._pending):
            context = self._nearest_context(origin)
            if context is None:
                continue
            frame, _ = self._pending.pop(origin)
            aligned.append(
                AlignedSensorFrame(acceleration=frame, temperature=context)
            )
        self._evict(now_ns)
        return aligned

    @property
    def pending_origins(self) -> list[int]:
        return sorted(self._pending)

    def _nearest_context(self, origin: int) -> AxisSample | None:
        candidates = [
            sample
            for sample in self._contexts.values()
            if abs(sample.origin - origin) <= self.max_skew_ns
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda sample: (
                abs(sample.origin - origin),
                sample.origin > origin,
                sample.origin,
            ),
        )

    def _evict(self, now_ns: int) -> None:
        cutoff = now_ns - self.pending_ttl_ns
        expired = [
            origin
            for origin, (_, first_seen_at) in self._pending.items()
            if first_seen_at < cutoff
        ]
        survivors = [origin for origin in sorted(self._pending) if origin not in expired]
        capacity_excess = max(0, len(survivors) - self.max_pending)
        for origin in [*sorted(expired), *survivors[:capacity_excess]]:
            self._pending.pop(origin, None)
            self.counters.unaligned_frames_dropped += 1

        context_cutoff = now_ns - self.pending_ttl_ns - self.max_skew_ns
        for origin in list(self._contexts):
            if origin < context_cutoff:
                self._contexts.pop(origin, None)
        if len(self._contexts) > self.max_pending:
            for origin in sorted(self._contexts)[: len(self._contexts) - self.max_pending]:
                self._contexts.pop(origin, None)
