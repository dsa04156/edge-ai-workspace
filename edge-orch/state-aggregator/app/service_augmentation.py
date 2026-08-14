from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .augmentation_crds import AugmentationResourceCrd
from .service_demo_models import ServiceDemoState


AugmentationStateName = Literal[
    "NORMAL",
    "OBSERVING",
    "RECOMMENDED",
    "AUGMENTED",
    "COOLDOWN",
    "BLOCKED",
]
Recommendation = Literal["none", "scale-up", "scale-down"]
ApplyState = Literal["observed-only", "blocked"]
ResourceMetricSource = Literal[
    "prometheus-node",
    "prometheus-container",
    "unavailable",
]
ServiceMetricSource = Literal["service-api", "unavailable"]

RESOURCE_PRESSURE_SECONDS = 300
SERVICE_PRESSURE_SECONDS = 180
SCALE_DOWN_SECONDS = 900
COOLDOWN_SECONDS = 900
CPU_PRESSURE_RATIO = 0.85
MEMORY_PRESSURE_RATIO = 0.85
SCALE_DOWN_RATIO = 0.60
LATENCY_PRESSURE_MS = 500.0
THROUGHPUT_FLOOR_PER_SECOND = 1.0
METRIC_FRESH_SECONDS = 60
SERVER1_NODE = "etri-ser0001-cg0msb"


@dataclass(frozen=True)
class ServiceAugmentationSignals:
    input_valid: bool
    input_reason: str
    model_ready: bool
    metrics_valid: bool
    metrics_reason: str
    resource_metric_source: ResourceMetricSource
    service_metric_source: ServiceMetricSource
    cpu_ratio: float
    memory_ratio: float
    gpu_pressure: bool
    gpu_percent: float | None
    processing_latency_p95_ms: float
    backlog: int
    throughput_per_second: float
    server1_pod_ready: bool
    server1_endpoint_ready: bool
    server1_model_ready: bool
    server1_resource_available: bool


class EvaluationGate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    passed: bool
    reason: str


class PressureDwell(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_pressure_seconds: int = Field(ge=0)
    resource_pressure_required_seconds: int = RESOURCE_PRESSURE_SECONDS
    service_pressure_seconds: int = Field(ge=0)
    service_pressure_required_seconds: int = SERVICE_PRESSURE_SECONDS
    scale_down_seconds: int = Field(ge=0)
    scale_down_required_seconds: int = SCALE_DOWN_SECONDS


class AugmentationMetricSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    cpu_percent: float = Field(ge=0)
    memory_percent: float = Field(ge=0)
    input_source: Literal["edgex-core-data"] = "edgex-core-data"
    resource_metric_source: ResourceMetricSource
    service_metric_source: ServiceMetricSource
    gpu_pressure: bool
    gpu_percent: float | None = Field(default=None, ge=0)
    processing_latency_p95_ms: float = Field(ge=0)
    backlog: int = Field(ge=0)
    throughput_per_second: float = Field(ge=0)


class AugmentationPerformanceComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    before: AugmentationMetricSnapshot | None = None
    after: AugmentationMetricSnapshot | None = None


class AugmentationTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    occurred_at: datetime
    from_state: AugmentationStateName
    to_state: AugmentationStateName
    reason: str


class ServiceAugmentationState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    service: Literal["sensor-anomaly-demo"] = "sensor-anomaly-demo"
    mode: Literal["observed-only"] = "observed-only"
    state: AugmentationStateName
    recommendation: Recommendation
    apply_state: ApplyState
    reason_codes: list[str] = Field(default_factory=list)
    gates: list[EvaluationGate] = Field(default_factory=list)
    metrics: AugmentationMetricSnapshot
    dwell: PressureDwell
    state_path: list[AugmentationStateName] = [
        "NORMAL",
        "OBSERVING",
        "RECOMMENDED",
        "AUGMENTED",
        "COOLDOWN",
        "NORMAL",
    ]
    anomaly_signal_used: Literal[False] = False
    performance_comparison: AugmentationPerformanceComparison = Field(
        default_factory=AugmentationPerformanceComparison
    )
    transitions: list[AugmentationTransition] = Field(default_factory=list)


class ServiceAugmentationEvaluator:
    def __init__(self) -> None:
        self.state: AugmentationStateName = "NORMAL"
        self._resource_pressure_since: datetime | None = None
        self._service_pressure_since: datetime | None = None
        self._scale_down_since: datetime | None = None
        self._last_augmented_at: datetime | None = None
        self._cooldown_since: datetime | None = None
        self._before_metrics: AugmentationMetricSnapshot | None = None
        self._after_metrics: AugmentationMetricSnapshot | None = None
        self._transitions: list[AugmentationTransition] = []

    def evaluate(
        self,
        signals: ServiceAugmentationSignals,
        *,
        now: datetime | None = None,
    ) -> ServiceAugmentationState:
        observed_at = _utc(now)
        blockers = _blockers(signals)
        if blockers:
            self._reset_pressure_dwell()
            self._transition("BLOCKED", observed_at, blockers[0])
            return self._state(signals, observed_at, "none", blockers)

        if self.state == "COOLDOWN":
            elapsed = _elapsed(self._cooldown_since, observed_at)
            if elapsed >= COOLDOWN_SECONDS:
                self._transition("NORMAL", observed_at, "cooldown_complete")
                self._cooldown_since = None
            return self._state(signals, observed_at, "none", ["cooldown_active"] if self.state == "COOLDOWN" else ["within_operating_envelope"])

        if self.state == "AUGMENTED":
            scale_down = _scale_down_condition(signals)
            self._scale_down_since = _dwell_start(self._scale_down_since, scale_down, observed_at)
            scale_down_elapsed = _elapsed(self._scale_down_since, observed_at)
            cooldown_elapsed = _elapsed(self._last_augmented_at, observed_at)
            if scale_down_elapsed >= SCALE_DOWN_SECONDS and cooldown_elapsed >= COOLDOWN_SECONDS:
                self._transition("COOLDOWN", observed_at, "scale_down_envelope_sustained")
                self._cooldown_since = observed_at
                return self._state(signals, observed_at, "scale-down", ["scale_down_recommended"])
            return self._state(signals, observed_at, "none", ["augmentation_active"])

        resource_pressure = _resource_pressure(signals)
        service_pressure = _service_pressure(signals)
        self._resource_pressure_since = _dwell_start(
            self._resource_pressure_since,
            resource_pressure,
            observed_at,
        )
        self._service_pressure_since = _dwell_start(
            self._service_pressure_since,
            service_pressure,
            observed_at,
        )
        resource_elapsed = _elapsed(self._resource_pressure_since, observed_at)
        service_elapsed = _elapsed(self._service_pressure_since, observed_at)

        if (
            resource_pressure
            and service_pressure
            and resource_elapsed >= RESOURCE_PRESSURE_SECONDS
            and service_elapsed >= SERVICE_PRESSURE_SECONDS
        ):
            self._transition("RECOMMENDED", observed_at, "sustained_resource_and_service_pressure")
            return self._state(
                signals,
                observed_at,
                "scale-up",
                ["sustained_resource_and_service_pressure"],
            )
        if resource_pressure or service_pressure:
            self._transition("OBSERVING", observed_at, "pressure_dwell_in_progress")
            reasons = []
            if resource_pressure:
                reasons.append("resource_pressure_observing")
            if service_pressure:
                reasons.append("service_pressure_observing")
            return self._state(signals, observed_at, "none", reasons)

        self._transition("NORMAL", observed_at, "pressure_cleared")
        return self._state(signals, observed_at, "none", ["within_operating_envelope"])

    def mark_augmented(self, *, now: datetime | None = None) -> None:
        if self.state != "RECOMMENDED":
            raise ValueError("augmentation can only follow a recommendation")
        observed_at = _utc(now)
        self._last_augmented_at = observed_at
        self._scale_down_since = None
        self._transition("AUGMENTED", observed_at, "approved_augmentation_observed")

    def _state(
        self,
        signals: ServiceAugmentationSignals,
        now: datetime,
        recommendation: Recommendation,
        reasons: list[str],
    ) -> ServiceAugmentationState:
        metric_snapshot = AugmentationMetricSnapshot(
            cpu_percent=round(signals.cpu_ratio * 100, 1),
            memory_percent=round(signals.memory_ratio * 100, 1),
            resource_metric_source=signals.resource_metric_source,
            service_metric_source=signals.service_metric_source,
            gpu_pressure=signals.gpu_pressure,
            gpu_percent=signals.gpu_percent,
            processing_latency_p95_ms=signals.processing_latency_p95_ms,
            backlog=signals.backlog,
            throughput_per_second=signals.throughput_per_second,
        )
        if self.state == "RECOMMENDED" and self._before_metrics is None:
            self._before_metrics = metric_snapshot
        if self.state == "AUGMENTED" and self._after_metrics is None:
            self._after_metrics = metric_snapshot
        return ServiceAugmentationState(
            generated_at=now,
            state=self.state,
            recommendation=recommendation,
            apply_state="blocked" if self.state == "BLOCKED" else "observed-only",
            reason_codes=reasons,
            gates=_gates(signals),
            metrics=metric_snapshot,
            dwell=PressureDwell(
                resource_pressure_seconds=_elapsed(self._resource_pressure_since, now),
                service_pressure_seconds=_elapsed(self._service_pressure_since, now),
                scale_down_seconds=_elapsed(self._scale_down_since, now),
            ),
            performance_comparison=AugmentationPerformanceComparison(
                before=self._before_metrics,
                after=self._after_metrics,
            ),
            transitions=self._transitions[-12:],
        )

    def _transition(self, state: AugmentationStateName, now: datetime, reason: str) -> None:
        if state == self.state:
            return
        previous = self.state
        if state == "RECOMMENDED":
            self._before_metrics = None
            self._after_metrics = None
        self.state = state
        self._transitions.append(
            AugmentationTransition(
                occurred_at=now,
                from_state=previous,
                to_state=state,
                reason=reason,
            )
        )

    def _reset_pressure_dwell(self) -> None:
        self._resource_pressure_since = None
        self._service_pressure_since = None


def build_service_augmentation_signals(
    demo: ServiceDemoState,
    resource_profile: dict | None,
    server1: AugmentationResourceCrd | None,
    *,
    now: datetime | None = None,
    source_node_metrics: dict | None = None,
    source_node_observed_at: datetime | str | None = None,
) -> ServiceAugmentationSignals:
    observed_at = _utc(now)
    input_valid, input_reason = _input_gate(demo)
    profile = resource_profile or {}
    current_usage = _mapping(profile.get("current_usage"))
    limits = _mapping(_mapping(profile.get("resource_requirements")).get("limits"))
    performance = demo.performance
    profile_fresh = _timestamp_fresh(profile.get("generated_at"), observed_at)
    coverage = _number(current_usage.get("usage_coverage_ratio"))
    profile_metrics_valid = bool(
        profile_fresh
        and coverage > 0
        and _number(limits.get("cpu_cores")) > 0
        and _number(limits.get("memory_mib")) > 0
    )
    node_metrics = _mapping(source_node_metrics)
    node_cpu_ratio = _observed_ratio(node_metrics.get("cpu_utilization"))
    node_memory_ratio = _observed_ratio(node_metrics.get("memory_usage_ratio"))
    node_metrics_valid = bool(
        _timestamp_fresh(source_node_observed_at, observed_at)
        and _number(node_metrics.get("up")) >= 0.5
        and node_cpu_ratio is not None
        and node_memory_ratio is not None
    )
    service_metrics_valid = bool(
        performance is not None
        and performance.metrics_valid
        and _timestamp_fresh(performance.observed_at, observed_at)
    )
    resource_metrics_valid = node_metrics_valid or profile_metrics_valid
    metrics_valid = service_metrics_valid and resource_metrics_valid
    if not service_metrics_valid:
        metrics_reason = "service_metrics_invalid_or_stale"
    elif not resource_metrics_valid:
        metrics_reason = "resource_metrics_invalid_or_stale"
    else:
        metrics_reason = "metrics_fresh"
    if node_metrics_valid:
        cpu_ratio = node_cpu_ratio or 0.0
        memory_ratio = node_memory_ratio or 0.0
        resource_metric_source: ResourceMetricSource = "prometheus-node"
    elif profile_metrics_valid:
        cpu_ratio = _ratio(current_usage.get("cpu_cores"), limits.get("cpu_cores"))
        memory_ratio = _ratio(
            current_usage.get("memory_working_set_mib"),
            limits.get("memory_mib"),
        )
        resource_metric_source = "prometheus-container"
    else:
        cpu_ratio = 0.0
        memory_ratio = 0.0
        resource_metric_source = "unavailable"
    source_gpu_ratio = _source_gpu_ratio(node_metrics) if node_metrics_valid else None
    pod_ready = bool(
        server1 is not None
        and server1.phase == "Available"
        and server1.observed_instances > 0
    )
    endpoint_ready = bool(server1 is not None and server1.endpoint_ready)
    model_ready = _condition_true(server1, "ModelReady", endpoint_ready)
    resource_available = bool(
        server1 is not None
        and server1.free_instances > 0
        and server1.binding_state in {"available", "free", "unbound"}
    )
    return ServiceAugmentationSignals(
        input_valid=input_valid,
        input_reason=input_reason,
        model_ready=demo.model_state == "ready",
        metrics_valid=metrics_valid,
        metrics_reason=metrics_reason,
        resource_metric_source=resource_metric_source,
        service_metric_source="service-api" if service_metrics_valid else "unavailable",
        cpu_ratio=cpu_ratio,
        memory_ratio=memory_ratio,
        gpu_pressure=(
            source_gpu_ratio is not None
            and source_gpu_ratio >= CPU_PRESSURE_RATIO
        ),
        gpu_percent=(
            round(source_gpu_ratio * 100, 1)
            if source_gpu_ratio is not None
            else None
        ),
        processing_latency_p95_ms=(
            performance.processing_latency_p95_ms if performance is not None else 0
        ),
        backlog=performance.backlog if performance is not None else 0,
        throughput_per_second=(
            performance.throughput_per_second if performance is not None else 0
        ),
        server1_pod_ready=pod_ready,
        server1_endpoint_ready=endpoint_ready,
        server1_model_ready=model_ready,
        server1_resource_available=resource_available,
    )


def select_server1_candidate(
    resources: list[AugmentationResourceCrd],
) -> AugmentationResourceCrd | None:
    return next(
        (
            resource
            for resource in resources
            if resource.node.casefold() == SERVER1_NODE
            and "anomaly_model" in resource.capabilities
        ),
        None,
    )


def _input_gate(demo: ServiceDemoState) -> tuple[bool, str]:
    if demo.mode != "live" or demo.input_state == "error":
        return False, "sensor_disconnected"
    if demo.input_state == "stale":
        return False, "sensor_stale"
    if demo.input_state != "fresh" or demo.latest is None:
        return False, "required_input_missing"
    if demo.latest.input_contract != "okdong.pump-motor.telemetry/v1":
        return False, "input_schema_invalid"
    if demo.latest.temperature_features is None:
        return False, "required_input_missing"
    return True, "input_ready"


def _blockers(signals: ServiceAugmentationSignals) -> list[str]:
    blockers: list[str] = []
    if not signals.input_valid:
        blockers.append(signals.input_reason)
    if not signals.model_ready:
        blockers.append("model_not_ready")
    if not signals.metrics_valid:
        blockers.append(signals.metrics_reason)
    if not signals.server1_pod_ready:
        blockers.append("server1_pod_not_ready")
    if not signals.server1_endpoint_ready:
        blockers.append("server1_endpoint_not_ready")
    if not signals.server1_model_ready:
        blockers.append("server1_model_not_ready")
    if not signals.server1_resource_available:
        blockers.append("server1_resource_insufficient")
    return blockers


def _gates(signals: ServiceAugmentationSignals) -> list[EvaluationGate]:
    return [
        EvaluationGate(id="input", label="센서 입력", passed=signals.input_valid, reason=signals.input_reason),
        EvaluationGate(id="model", label="Edge 모델", passed=signals.model_ready, reason="model_ready" if signals.model_ready else "model_not_ready"),
        EvaluationGate(id="metrics", label="운영 메트릭", passed=signals.metrics_valid, reason=signals.metrics_reason),
        EvaluationGate(id="server1-pod", label="server1 Pod", passed=signals.server1_pod_ready, reason="pod_ready" if signals.server1_pod_ready else "server1_pod_not_ready"),
        EvaluationGate(id="server1-endpoint", label="server1 endpoint", passed=signals.server1_endpoint_ready, reason="endpoint_ready" if signals.server1_endpoint_ready else "server1_endpoint_not_ready"),
        EvaluationGate(id="server1-model", label="server1 모델", passed=signals.server1_model_ready, reason="model_ready" if signals.server1_model_ready else "server1_model_not_ready"),
        EvaluationGate(id="server1-resource", label="server1 여유 자원", passed=signals.server1_resource_available, reason="resource_available" if signals.server1_resource_available else "server1_resource_insufficient"),
    ]


def _resource_pressure(signals: ServiceAugmentationSignals) -> bool:
    return (
        signals.cpu_ratio >= CPU_PRESSURE_RATIO
        or signals.memory_ratio >= MEMORY_PRESSURE_RATIO
        or signals.gpu_pressure
    )


def _service_pressure(signals: ServiceAugmentationSignals) -> bool:
    return (
        signals.processing_latency_p95_ms >= LATENCY_PRESSURE_MS
        or signals.backlog > 0
        or signals.throughput_per_second < THROUGHPUT_FLOOR_PER_SECOND
    )


def _scale_down_condition(signals: ServiceAugmentationSignals) -> bool:
    return (
        signals.cpu_ratio < SCALE_DOWN_RATIO
        and signals.memory_ratio < SCALE_DOWN_RATIO
        and signals.processing_latency_p95_ms < LATENCY_PRESSURE_MS
        and signals.backlog == 0
    )


def _dwell_start(current: datetime | None, active: bool, now: datetime) -> datetime | None:
    if not active:
        return None
    return current or now


def _elapsed(start: datetime | None, now: datetime) -> int:
    if start is None:
        return 0
    return max(0, int((now - start).total_seconds()))


def _timestamp_fresh(value: object, now: datetime) -> bool:
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


def _condition_true(
    resource: AugmentationResourceCrd | None,
    condition_type: str,
    default: bool,
) -> bool:
    if resource is None:
        return False
    condition = next(
        (item for item in resource.conditions if item.type == condition_type),
        None,
    )
    return condition.status == "True" if condition is not None else default


def _ratio(numerator: object, denominator: object) -> float:
    bottom = _number(denominator)
    return _number(numerator) / bottom if bottom > 0 else 0.0


def _number(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _observed_ratio(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if ratio < 0 or ratio > 1:
        return None
    return ratio


def _source_gpu_ratio(metrics: dict) -> float | None:
    values = [
        _observed_ratio(metrics.get("gpu_utilization")),
        _observed_ratio(metrics.get("gpu_memory_usage_ratio")),
    ]
    observed = [value for value in values if value is not None]
    return max(observed) if observed else None


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _utc(value: datetime | None) -> datetime:
    selected = value or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        return selected.replace(tzinfo=timezone.utc)
    return selected.astimezone(timezone.utc)
