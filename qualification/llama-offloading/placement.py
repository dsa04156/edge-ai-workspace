"""Stateful rule-based placement for the isolated Llama offloading prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


TIERS = ("nano", "agx", "spark")


@dataclass
class PolicyConfig:
    min_improvement: float = 0.15
    overload_dwell_seconds: float = 2.0
    recovery_dwell_seconds: float = 4.0
    cooldown_seconds: float = 5.0
    queue_high: int = 1
    queue_recovered: int = 0
    ttft_high_ms: float = 1500.0
    ttft_recovered_ms: float = 1000.0
    # Generic engine defaults. Hardware-qualified values are injected by the
    # deployment so unit tests and library users do not inherit one node's TPS.
    min_tokens_per_second: float = 4.0
    recovered_tokens_per_second: float = 5.0


@dataclass
class PlacementDecision:
    node: str
    reason: str
    predicted_e2e_ms: float
    candidates: dict[str, float]


@dataclass
class PlacementEngine:
    config: PolicyConfig = field(default_factory=PolicyConfig)
    route: str = "nano"
    overload_since: dict[str, float | None] = field(
        default_factory=lambda: {tier: None for tier in TIERS}
    )
    recovery_since: dict[str, float | None] = field(
        default_factory=lambda: {tier: None for tier in TIERS}
    )
    cooldown_until: float = 0.0

    @staticmethod
    def predicted_e2e(metrics: dict[str, Any]) -> float:
        rtt = float(metrics.get("rtt_ms") or 0.0)
        active = int(metrics.get("active_requests") or 0)
        queued = int(metrics.get("queue_length") or 0)
        concurrency = max(1, int(metrics.get("max_concurrency") or 1))
        inference = float(
            metrics.get("ewma_inference_ms")
            or metrics.get("last_inference_ms")
            or metrics.get("profile_inference_ms")
            or 1000.0
        )
        ahead = queued + max(0, active - concurrency + 1)
        queue_wait = (ahead / concurrency) * inference
        activation = 0.0
        if str(metrics.get("node_state") or "ACTIVE") != "ACTIVE":
            activation = float(metrics.get("activation_estimate_ms") or 0.0)
        return rtt + activation + queue_wait + inference

    def _is_overloaded(self, metrics: dict[str, Any]) -> bool:
        queue = int(metrics.get("queue_length") or 0)
        ttft = float(metrics.get("ewma_ttft_ms") or metrics.get("last_ttft_ms") or 0.0)
        tps = float(metrics.get("ewma_tokens_per_second") or metrics.get("last_tokens_per_second") or 0.0)
        return (
            queue >= self.config.queue_high
            or ttft >= self.config.ttft_high_ms
            or (tps > 0 and tps <= self.config.min_tokens_per_second)
        )

    def _is_recovered(self, metrics: dict[str, Any]) -> bool:
        queue = int(metrics.get("queue_length") or 0)
        active = int(metrics.get("active_requests") or 0)
        # An inactive lower tier cannot produce fresh service-performance samples.
        # Its historical TTFT/TPS may describe an old overload episode forever, so
        # recovery is based on continuously observed idle capacity.  The recovery
        # dwell and cooldown still prevent an immediate or oscillating fallback.
        return queue <= self.config.queue_recovered and active == 0

    def _update_latches(self, snapshots: dict[str, dict[str, Any]], now: float) -> None:
        for tier in TIERS:
            metrics = snapshots[tier]
            healthy = bool(metrics.get("healthy"))
            overloaded = healthy and self._is_overloaded(metrics)
            recovered = healthy and self._is_recovered(metrics)
            if overloaded:
                if self.overload_since[tier] is None:
                    self.overload_since[tier] = now
            else:
                self.overload_since[tier] = None
            if recovered:
                if self.recovery_since[tier] is None:
                    self.recovery_since[tier] = now
            else:
                self.recovery_since[tier] = None

    @staticmethod
    def _sustained(since: float | None, seconds: float, now: float) -> bool:
        return since is not None and now - since >= seconds

    def select(
        self,
        snapshots: dict[str, dict[str, Any]],
        *,
        mode: str = "dynamic",
        static_node: str | None = None,
        now: float | None = None,
    ) -> PlacementDecision:
        now = time.monotonic() if now is None else now
        predictions = {tier: self.predicted_e2e(snapshots[tier]) for tier in TIERS}

        if mode == "nano_only":
            return PlacementDecision("nano", "policy:nano_only", predictions["nano"], predictions)
        if mode == "static":
            if static_node not in TIERS:
                raise ValueError("static_node must be one of nano, agx, spark")
            return PlacementDecision(
                static_node,
                f"policy:static:{static_node}",
                predictions[static_node],
                predictions,
            )
        if mode != "dynamic":
            raise ValueError("mode must be nano_only, static, or dynamic")

        self._update_latches(snapshots, now)
        current_index = TIERS.index(self.route)

        # Recover one tier at a time only after both the current and lower
        # tiers have stayed idle. A lower tier is naturally idle while all
        # traffic is offloaded, so lower-idle alone is not demand recovery.
        if current_index > 0 and now >= self.cooldown_until:
            lower = TIERS[current_index - 1]
            if (
                self._sustained(self.recovery_since[self.route], self.config.recovery_dwell_seconds, now)
                and self._sustained(self.recovery_since[lower], self.config.recovery_dwell_seconds, now)
            ):
                previous = self.route
                self.route = lower
                self.cooldown_until = now + self.config.cooldown_seconds
                return PlacementDecision(
                    lower,
                    f"recovery:{previous}->{lower}:sustained",
                    predictions[lower],
                    predictions,
                )

        # Escalate one tier at a time when service pressure persists and E2E improves.
        if current_index < len(TIERS) - 1 and now >= self.cooldown_until:
            current = self.route
            candidate = TIERS[current_index + 1]
            if self._sustained(
                self.overload_since[current], self.config.overload_dwell_seconds, now
            ) and snapshots[candidate].get("available", snapshots[candidate].get("healthy")):
                current_cost = predictions[current]
                candidate_cost = predictions[candidate]
                improvement = (
                    (current_cost - candidate_cost) / current_cost if current_cost > 0 else 0.0
                )
                if improvement >= self.config.min_improvement:
                    self.route = candidate
                    self.cooldown_until = now + self.config.cooldown_seconds
                    return PlacementDecision(
                        candidate,
                        f"offload:{current}->{candidate}:predicted_improvement={improvement:.3f}",
                        candidate_cost,
                        predictions,
                    )

        return PlacementDecision(
            self.route,
            f"hold:{self.route}:hysteresis_or_improvement_gate",
            predictions[self.route],
            predictions,
        )
