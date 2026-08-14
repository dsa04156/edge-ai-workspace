from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .service_demo_models import (
    ServiceAugmentationCandidate,
    ServiceAugmentationDwell,
    ServiceAugmentationGate,
    ServiceAugmentationMetrics,
    ServiceAugmentationObservation,
    ServiceAugmentationState,
    ServiceDemoState,
)


RESOURCE_PRESSURE_SECONDS = 300
SERVICE_PRESSURE_SECONDS = 180
CPU_PRESSURE_RATIO = 0.85
MEMORY_PRESSURE_RATIO = 0.85
LATENCY_PRESSURE_MS = 4_000.0
THROUGHPUT_FLOOR_PER_SECOND = 0.8
METRIC_FRESH_SECONDS = 60


@dataclass(frozen=True)
class ServiceAugmentationSignals:
    input_valid: bool
    model_ready: bool
    performance_valid: bool
    resource_valid: bool
    cpu_ratio: float | None
    memory_ratio: float | None
    processing_latency_p95_ms: float
    backlog: int
    throughput_per_second: float
    candidate_ready: bool
    observation_source: str
    observation_scope: str


class ServiceAugmentationEvaluator:
    """Stateful, read-only evaluator. It never mutates a workload or route."""

    def __init__(self) -> None:
        self._resource_pressure_since: datetime | None = None
        self._service_pressure_since: datetime | None = None

    def evaluate(
        self,
        signals: ServiceAugmentationSignals,
        *,
        now: datetime | None = None,
    ) -> ServiceAugmentationState:
        observed_at = _utc(now)
        blockers = _prerequisite_blockers(signals)
        if blockers:
            self._reset_dwell()
            return self._state("BLOCKED", signals, observed_at, blockers)

        resource_pressure = _resource_pressure(signals)
        service_pressure = _service_pressure(signals)
        self._resource_pressure_since = _dwell_start(
            self._resource_pressure_since, resource_pressure, observed_at
        )
        self._service_pressure_since = _dwell_start(
            self._service_pressure_since, service_pressure, observed_at
        )
        resource_elapsed = _elapsed(self._resource_pressure_since, observed_at)
        service_elapsed = _elapsed(self._service_pressure_since, observed_at)
        sustained = (
            resource_pressure
            and service_pressure
            and resource_elapsed >= RESOURCE_PRESSURE_SECONDS
            and service_elapsed >= SERVICE_PRESSURE_SECONDS
        )
        if sustained and not signals.candidate_ready:
            return self._state(
                "BLOCKED",
                signals,
                observed_at,
                ["augmentation_candidate_not_ready"],
            )
        if sustained:
            return self._state(
                "RECOMMENDED",
                signals,
                observed_at,
                ["sustained_resource_and_service_pressure"],
                recommendation="scale-up",
            )
        if resource_pressure or service_pressure:
            reasons = []
            if resource_pressure:
                reasons.append("resource_pressure_observing")
            if service_pressure:
                reasons.append("service_pressure_observing")
            return self._state("OBSERVING", signals, observed_at, reasons)
        return self._state(
            "NORMAL", signals, observed_at, ["within_operating_envelope"]
        )

    def _state(
        self,
        state: str,
        signals: ServiceAugmentationSignals,
        now: datetime,
        reasons: list[str],
        *,
        recommendation: str = "none",
    ) -> ServiceAugmentationState:
        return ServiceAugmentationState(
            generated_at=now,
            state=state,
            recommendation=recommendation,
            apply_state="blocked" if state == "BLOCKED" else "observed-only",
            reason_codes=reasons,
            gates=_gates(signals),
            metrics=ServiceAugmentationMetrics(
                cpu_percent=_percent(signals.cpu_ratio),
                memory_percent=_percent(signals.memory_ratio),
                processing_latency_p95_ms=signals.processing_latency_p95_ms,
                backlog=signals.backlog,
                throughput_per_second=signals.throughput_per_second,
            ),
            dwell=ServiceAugmentationDwell(
                resource_pressure_seconds=_elapsed(
                    self._resource_pressure_since, now
                ),
                service_pressure_seconds=_elapsed(
                    self._service_pressure_since, now
                ),
            ),
            observation=ServiceAugmentationObservation(
                source=signals.observation_source,
                scope=signals.observation_scope,
            ),
            candidate=ServiceAugmentationCandidate(ready=signals.candidate_ready),
        )

    def _reset_dwell(self) -> None:
        self._resource_pressure_since = None
        self._service_pressure_since = None


def build_service_augmentation_signals(
    demo: ServiceDemoState,
    resource_profile: dict | None,
    *,
    candidate_ready: bool,
    now: datetime | None = None,
) -> ServiceAugmentationSignals:
    observed_at = _utc(now)
    profile = resource_profile or {}
    current = _mapping(profile.get("current_usage"))
    limits = _mapping(_mapping(profile.get("resource_requirements")).get("limits"))
    coverage = _number(current.get("usage_coverage_ratio"))
    cpu_usage: float | None = None
    memory_usage: float | None = None
    source = "unavailable"
    scope = "unknown"

    if (
        coverage > 0
        and _fresh(profile.get("generated_at"), observed_at)
        and _optional_number(current.get("cpu_cores")) is not None
        and _optional_number(current.get("memory_working_set_mib")) is not None
    ):
        cpu_usage = _optional_number(current.get("cpu_cores"))
        memory_usage = _optional_number(current.get("memory_working_set_mib"))
        source = "container-cadvisor"
        scope = "container"
    else:
        process = demo.process_resources
        if (
            process is not None
            and process.metrics_valid
            and _fresh(process.observed_at, observed_at)
        ):
            cpu_usage = process.cpu_cores
            memory_usage = process.memory_rss_mib
            source = process.source
            scope = process.scope

    cpu_limit = _optional_number(limits.get("cpu_cores"))
    memory_limit = _optional_number(limits.get("memory_mib"))
    cpu_ratio = _ratio(cpu_usage, cpu_limit)
    memory_ratio = _ratio(memory_usage, memory_limit)
    performance = demo.performance
    performance_valid = bool(
        performance is not None
        and performance.metrics_valid
        and _fresh(performance.observed_at, observed_at)
    )
    return ServiceAugmentationSignals(
        input_valid=bool(
            demo.mode == "live"
            and demo.input_state == "fresh"
            and demo.latest is not None
            and demo.latest.input_contract == "okdong.pump-motor.telemetry/v1"
        ),
        model_ready=demo.model_state == "ready",
        performance_valid=performance_valid,
        resource_valid=bool(cpu_ratio is not None and memory_ratio is not None),
        cpu_ratio=cpu_ratio,
        memory_ratio=memory_ratio,
        processing_latency_p95_ms=(
            performance.processing_latency_p95_ms if performance is not None else 0
        ),
        backlog=performance.backlog if performance is not None else 0,
        throughput_per_second=(
            performance.throughput_per_second if performance is not None else 0
        ),
        candidate_ready=candidate_ready,
        observation_source=source,
        observation_scope=scope,
    )


def _prerequisite_blockers(signals: ServiceAugmentationSignals) -> list[str]:
    blockers = []
    if not signals.input_valid:
        blockers.append("input_invalid_or_stale")
    if not signals.model_ready:
        blockers.append("model_not_ready")
    if not signals.performance_valid:
        blockers.append("performance_observation_unavailable")
    if not signals.resource_valid:
        blockers.append("resource_observation_unavailable")
    return blockers


def _gates(signals: ServiceAugmentationSignals) -> list[ServiceAugmentationGate]:
    return [
        ServiceAugmentationGate(id="input", label="입력", passed=signals.input_valid, reason="fresh" if signals.input_valid else "invalid_or_stale"),
        ServiceAugmentationGate(id="model", label="모델", passed=signals.model_ready, reason="ready" if signals.model_ready else "not_ready"),
        ServiceAugmentationGate(id="performance", label="서비스 지표", passed=signals.performance_valid, reason="fresh" if signals.performance_valid else "unavailable"),
        ServiceAugmentationGate(id="resources", label="자원 지표", passed=signals.resource_valid, reason=signals.observation_source),
        ServiceAugmentationGate(id="candidate", label="server1 후보", passed=signals.candidate_ready, reason="ready" if signals.candidate_ready else "not_ready"),
    ]


def _resource_pressure(signals: ServiceAugmentationSignals) -> bool:
    return bool(
        (signals.cpu_ratio is not None and signals.cpu_ratio >= CPU_PRESSURE_RATIO)
        or (
            signals.memory_ratio is not None
            and signals.memory_ratio >= MEMORY_PRESSURE_RATIO
        )
    )


def _service_pressure(signals: ServiceAugmentationSignals) -> bool:
    return bool(
        signals.processing_latency_p95_ms >= LATENCY_PRESSURE_MS
        or signals.backlog > 0
        or signals.throughput_per_second < THROUGHPUT_FLOOR_PER_SECOND
    )


def _dwell_start(
    current: datetime | None, active: bool, now: datetime
) -> datetime | None:
    return (current or now) if active else None


def _elapsed(start: datetime | None, now: datetime) -> int:
    return max(0, int((now - start).total_seconds())) if start is not None else 0


def _fresh(value: object, now: datetime) -> bool:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    return _elapsed(_utc(timestamp), now) <= METRIC_FRESH_SECONDS


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float:
    return _optional_number(value) or 0.0


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _percent(value: float | None) -> float | None:
    return round(value * 100, 1) if value is not None else None


def _utc(value: datetime | None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        return selected.replace(tzinfo=timezone.utc)
    return selected.astimezone(timezone.utc)
