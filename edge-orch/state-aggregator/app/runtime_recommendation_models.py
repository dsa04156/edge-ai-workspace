from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .models import PlacementSelectionResult, SchedulingModel


RuntimeRecommendationState = Literal[
    "NORMAL",
    "OBSERVING",
    "AUGMENT_RECOMMENDED",
    "REPLACE_RECOMMENDED",
    "BLOCKED",
]
RuntimeRecommendationAction = Literal["none", "augment", "replace"]


class RuntimeRecommendationPolicy(SchedulingModel):
    enabled: bool = True
    architecture: str = Field(min_length=1, max_length=64)
    accelerator: str | None = Field(default=None, min_length=1, max_length=128)
    accelerator_units: dict[str, float] = Field(default_factory=dict)
    cpu_high_ratio: float = Field(default=0.85, gt=0, le=1)
    cpu_recovery_ratio: float = Field(default=0.70, ge=0, lt=1)
    memory_high_ratio: float = Field(default=0.85, gt=0, le=1)
    memory_recovery_ratio: float = Field(default=0.70, ge=0, lt=1)
    latency_high_ms: float = Field(default=4000, gt=0)
    latency_recovery_ms: float = Field(default=2500, ge=0)
    throughput_floor_per_second: float = Field(default=0.8, ge=0)
    throughput_recovery_per_second: float = Field(default=1.0, ge=0)
    backlog_high: int = Field(default=1, ge=1)
    backlog_recovery: int = Field(default=0, ge=0)
    resource_dwell_seconds: int = Field(default=300, ge=0, le=86400)
    service_dwell_seconds: int = Field(default=180, ge=0, le=86400)
    replacement_dwell_seconds: int = Field(default=60, ge=0, le=86400)
    recovery_dwell_seconds: int = Field(default=120, ge=0, le=86400)
    cooldown_seconds: int = Field(default=600, ge=0, le=604800)
    metric_fresh_seconds: int = Field(default=60, ge=1, le=3600)
    max_restart_count: int = Field(default=3, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_hysteresis(self) -> "RuntimeRecommendationPolicy":
        if self.cpu_recovery_ratio >= self.cpu_high_ratio:
            raise ValueError("cpuRecoveryRatio must be lower than cpuHighRatio")
        if self.memory_recovery_ratio >= self.memory_high_ratio:
            raise ValueError("memoryRecoveryRatio must be lower than memoryHighRatio")
        if self.latency_recovery_ms >= self.latency_high_ms:
            raise ValueError("latencyRecoveryMs must be lower than latencyHighMs")
        if self.throughput_recovery_per_second < self.throughput_floor_per_second:
            raise ValueError(
                "throughputRecoveryPerSecond must be at least throughputFloorPerSecond"
            )
        if self.backlog_recovery >= self.backlog_high:
            raise ValueError("backlogRecovery must be lower than backlogHigh")
        return self


class RuntimeRecommendationMetrics(SchedulingModel):
    cpu_ratio: float | None = Field(default=None, ge=0)
    memory_ratio: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    backlog: int | None = Field(default=None, ge=0)
    throughput_per_second: float | None = Field(default=None, ge=0)
    desired_replicas: int = Field(default=0, ge=0)
    ready_replicas: int = Field(default=0, ge=0)
    pod_restart_count: int = Field(default=0, ge=0)


class RuntimeRecommendationDwell(SchedulingModel):
    resource_pressure_seconds: int = Field(default=0, ge=0)
    resource_required_seconds: int = Field(default=0, ge=0)
    service_pressure_seconds: int = Field(default=0, ge=0)
    service_required_seconds: int = Field(default=0, ge=0)
    runtime_failure_seconds: int = Field(default=0, ge=0)
    replacement_required_seconds: int = Field(default=0, ge=0)
    recovery_seconds: int = Field(default=0, ge=0)
    recovery_required_seconds: int = Field(default=0, ge=0)


class RuntimeRecommendationTarget(SchedulingModel):
    action: RuntimeRecommendationAction = "none"
    selected_node: str | None = None
    selected_score: float | None = Field(default=None, ge=0, le=100)


class RuntimeRecommendationDecision(SchedulingModel):
    service_id: str
    namespace: str
    workload_kind: Literal["Deployment", "StatefulSet"]
    workload_name: str
    current_nodes: list[str] = Field(default_factory=list)
    state: RuntimeRecommendationState
    previous_state: RuntimeRecommendationState | None = None
    reason_codes: list[str] = Field(default_factory=list)
    metrics: RuntimeRecommendationMetrics
    dwell: RuntimeRecommendationDwell
    cooldown_remaining_seconds: int = Field(default=0, ge=0)
    recommendation: RuntimeRecommendationTarget = Field(
        default_factory=RuntimeRecommendationTarget
    )
    placement: PlacementSelectionResult | None = None
    observation_source: str
    observation_scope: str
    observed_at: datetime
    mode: Literal["read_only"] = "read_only"


class RuntimeRecommendationList(SchedulingModel):
    generated_at: datetime
    items: list[RuntimeRecommendationDecision] = Field(default_factory=list)
    mode: Literal["read_only"] = "read_only"


class RuntimeRecommendationHistoryEntry(SchedulingModel):
    sequence: int = Field(ge=1)
    recorded_at: datetime
    previous_state: RuntimeRecommendationState | None = None
    state: RuntimeRecommendationState
    decision: RuntimeRecommendationDecision


class RuntimeRecommendationHistory(SchedulingModel):
    service_id: str
    generated_at: datetime
    items: list[RuntimeRecommendationHistoryEntry] = Field(default_factory=list)
    mode: Literal["read_only"] = "read_only"
