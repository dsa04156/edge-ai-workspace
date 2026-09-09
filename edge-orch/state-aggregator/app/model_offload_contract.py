"""Reviewed worker roles and measured, request-specific offload eligibility."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class ModelWorker(ContractModel):
    node: str = Field(min_length=1)
    role: Literal["edge", "server"]
    endpoint: str
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: str = Field(min_length=1)
    runtime_image: str = Field(pattern=r"^\S+@sha256:[a-f0-9]{64}$")
    runtime_container: str = Field(min_length=1)
    runtime_namespace: str = Field(min_length=1)
    runtime_selector: str = Field(pattern=r"^app=[a-z0-9-]+$")
    capacity_rps: float = Field(gt=0)
    service_ms: float = Field(gt=0)
    low_ttft_ms: float = Field(gt=0)
    activation_ms: float = Field(ge=0)
    max_management_rtt_ms: float = Field(default=2000, gt=0)
    max_ram_percent: float = Field(default=90, gt=0, le=100)

    @field_validator("endpoint")
    @classmethod
    def fixed_service_endpoint(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"http://[a-z0-9-]+\.[a-z0-9-]+\.svc\.cluster\.local:[0-9]{1,5}", value):
            raise ValueError("declared_cluster_service_required")
        if not 0 < int(value.rsplit(":", 1)[1]) < 65536:
            raise ValueError("invalid_service_port")
        return value


class ModelOffloadContract(ContractModel):
    service_id: str = Field(pattern=r"^[a-z0-9-]+$")
    prompt: str = Field(min_length=1, max_length=4096)
    max_tokens: int = Field(ge=1, le=256)
    workers: list[ModelWorker] = Field(min_length=2)
    slo_ms: float = Field(gt=0)
    queue_limit: int = Field(ge=1, le=10000)
    high_ratio: float = Field(default=.85, gt=0, le=1)
    low_ratio: float = Field(default=.60, gt=0, le=1)
    pressure_seconds: float = Field(default=5, gt=0)
    return_seconds: float = Field(default=30, gt=0)
    cooldown_seconds: float = Field(default=60, gt=0)
    idle_seconds: float = Field(default=30, gt=0)
    fresh_seconds: float = Field(default=3, gt=0)
    rate_window_seconds: float = Field(default=10, gt=0)
    min_gain: float = Field(default=.15, ge=0, lt=1)
    action_timeout_seconds: float = Field(default=180, gt=0)

    @model_validator(mode="after")
    def roles_and_model(self) -> ModelOffloadContract:
        if sum(w.role == "edge" for w in self.workers) != 1:
            raise ValueError("exactly_one_edge_required")
        if len({w.node for w in self.workers}) != len(self.workers):
            raise ValueError("duplicate_worker_node")
        if len({w.endpoint for w in self.workers}) != len(self.workers):
            raise ValueError("duplicate_worker_endpoint")
        if len({w.model_digest for w in self.workers}) != 1:
            raise ValueError("same_model_required")
        if self.low_ratio >= self.high_ratio:
            raise ValueError("return_threshold_must_be_lower")
        return self

    @property
    def edge(self) -> ModelWorker:
        return next(w for w in self.workers if w.role == "edge")


def worker_reasons(worker: ModelWorker, sample: dict, now: float,
                   freshness: float, *, ready: bool = False) -> list[str]:
    reasons: list[str] = []
    age = now - sample.get("observed_at", -math.inf)
    if not math.isfinite(age) or not 0 <= age <= freshness:
        reasons.append("worker_observation_stale")
    if sample.get("node_id") != worker.node:
        reasons.append("worker_identity_mismatch")
    if sample.get("model_digest") != worker.model_digest:
        reasons.append("model_digest_mismatch")
    if sample.get("management_runtime_running") is not True:
        reasons.append("worker_management_unavailable")
    if sample.get("model_cached") is not True:
        reasons.append("qualified_model_cache_missing")
    if ready and sample.get("inference_ready") is not True:
        reasons.append("inference_not_ready")
    if ready:
        vram = sample.get("model_vram_mib")
        if not isinstance(vram, (int, float)) or not math.isfinite(vram) or vram <= 0:
            reasons.append("model_gpu_residency_unverified")
    return reasons


def overlap_forecast(contract: ModelOffloadContract, candidate: ModelWorker,
                     rate: float, pending: int, inflight: int) -> dict:
    """Same FCFS arrival/activation boundary as continuity qualification v2.

    service_ms is measured end-to-end from this controller's network location;
    do not replace it with GPU kernel time or transfer another node's evidence.
    """
    activation = candidate.activation_ms / 1000
    horizon = activation + contract.cooldown_seconds
    count = math.floor(horizon * rate)
    if not math.isfinite(rate) or rate <= 0 or pending < 0 or not 1 <= pending + count <= 100000:
        raise ValueError("forecast_outside_qualified_bounds")
    sn, sr = contract.edge.service_ms / 1000, candidate.service_ms / 1000
    original = source = inflight * sn
    remote = activation
    local_total = candidate_total = 0.0
    for index in range(pending + count):
        arrival = 0.0 if index < pending else (index - pending + 1) / rate
        original = max(original, arrival) + sn
        local_total += original - arrival
        if index < pending or arrival < activation:
            source = max(source, arrival) + sn
            complete = source
        else:
            remote = max(remote, arrival) + sr
            complete = remote
        candidate_total += complete - arrival
    return {"gain": 1 - candidate_total / local_total,
            "local_mean_response_ms": 1000 * local_total / (pending + count),
            "candidate_mean_response_ms": 1000 * candidate_total / (pending + count),
            "horizon_seconds": horizon, "rate_rps": rate,
            "assumption": "observed_arrival_rate_persists"}


def recommend_model_offload(contract: ModelOffloadContract, samples: dict[str, dict],
                            now: float, rate: float, pending: int, inflight: int) -> dict:
    """Tier decision first; rank only declared, measured server candidates."""
    edge_reasons = worker_reasons(contract.edge, samples.get(contract.edge.node, {}),
                                  now, contract.fresh_seconds, ready=True)
    if samples.get(contract.edge.node, {}).get("runtime_placement_verified") is not True:
        edge_reasons.append("source_runtime_placement_unverified")
    predicted_ttft = (pending + inflight) * contract.edge.service_ms + contract.edge.low_ttft_ms
    pressure = math.isfinite(rate) and rate >= 0 and (
        rate >= contract.high_ratio * contract.edge.capacity_rps or predicted_ttft > contract.slo_ms)
    result = {"service_id": contract.service_id, "tier": "edge", "selected_node": None,
              "pressure": pressure, "reason_codes": edge_reasons, "candidates": []}
    if edge_reasons or not pressure or rate <= 0:
        return result
    for worker in contract.workers:
        if worker.role != "server":
            continue
        sample = samples.get(worker.node, {})
        reasons = worker_reasons(worker, sample, now, contract.fresh_seconds)
        if sample.get("runtime_placement_verified") is not True:
            reasons.append("runtime_placement_unverified")
        for field, ceiling in (("ram_utilization_percent", worker.max_ram_percent),
                               ("management_rtt_ms", worker.max_management_rtt_ms)):
            value = sample.get(field)
            if (not isinstance(value, (float, int)) or isinstance(value, bool)
                    or not math.isfinite(value) or not 0 <= value <= ceiling):
                reasons.append(f"{field}_unavailable_or_exceeded")
        if sample.get("active_requests") != 0 or sample.get("queue_length") != 0:
            reasons.append("candidate_busy")
        if rate > worker.capacity_rps:
            reasons.append("qualified_capacity_exceeded")
        forecast = None
        if not reasons:
            try:
                forecast = overlap_forecast(contract, worker, rate, pending, inflight)
                if forecast["gain"] < contract.min_gain:
                    reasons.append("insufficient_measured_gain")
            except ValueError:
                reasons.append("forecast_outside_qualified_bounds")
        result["candidates"].append({"node": worker.node, "eligible": not reasons,
                                      "reason_codes": reasons, "forecast": forecast,
                                      "evidence": worker.evidence})
    eligible = [item for item in result["candidates"] if item["eligible"]]
    if eligible:
        selected = min(eligible, key=lambda item: (item["forecast"]["candidate_mean_response_ms"], item["node"]))
        result.update(tier="server", selected_node=selected["node"], reason_codes=["measured_server_gain"])
    else:
        result["reason_codes"] = ["no_eligible_server"]
    return result
