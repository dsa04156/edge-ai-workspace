"""Reviewed, declarative HTTP service contract; never accepts arbitrary Pod specs."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from kubernetes.utils.quantity import parse_quantity
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WorkloadRef(Contract):
    namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


class ResidentRuntime(Contract):
    protocol: Literal["llama-worker-v1"]
    namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    service: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    selector: dict[str, str] = Field(min_length=1)
    container: str = Field(min_length=1, max_length=63)
    # Explicit handoff: refuse lifecycle calls while any previous controller runs.
    previousControllers: list[WorkloadRef] = Field(min_length=1, max_length=8)


class InferenceContract(Contract):
    modelDigest: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt: str = Field(min_length=1, max_length=4096)
    maxTokens: int = Field(ge=1, le=256)


class Variant(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,30}$")
    image: str = Field(pattern=r"^[^\s]+@sha256:[0-9a-f]{64}$")
    architecture: Literal["arm64", "amd64"]
    backend: str = Field(min_length=1, max_length=64)
    nodeSelector: dict[str, str] = Field(default_factory=dict)
    runtimeClassName: str | None = None
    requests: dict[str, str]
    limits: dict[str, str]
    # Reviewed concurrency qualification, not inferred from device names or RAM.
    maxInFlight: int = Field(ge=1, le=256)
    qualification: str = Field(min_length=1, max_length=256)
    resident: ResidentRuntime | None = None
    qualifiedRps: float | None = Field(default=None, gt=0, le=100000)
    qualifiedP95Milliseconds: float | None = Field(default=None, gt=0, le=300000)

    @model_validator(mode="after")
    def valid_resources(self):
        if not {"cpu", "memory"} <= self.requests.keys():
            raise ValueError("cpu and memory requests required")
        for key, value in self.requests.items():
            q = parse_quantity(value)
            if not q.is_finite() or q <= 0 or key not in self.limits or q > parse_quantity(self.limits[key]):
                raise ValueError("positive requests <= limits required")
            if key not in {"cpu", "memory", "ephemeral-storage"}:
                if "/" not in key or q != int(q) or q != parse_quantity(self.limits[key]):
                    raise ValueError("extended resources need equal integer requests and limits")
        if self.requests.keys() != self.limits.keys():
            raise ValueError("declare requests for every limited resource")
        if self.nodeSelector.get("kubernetes.io/arch", self.architecture) != self.architecture:
            raise ValueError("conflicting architecture selector")
        return self


class LatencyPolicy(Contract):
    maxP95Milliseconds: float = Field(gt=0, le=300000)
    returnP95Milliseconds: float = Field(gt=0, le=300000)
    windowSeconds: float = Field(default=60, ge=5, le=600)
    minSamples: int = Field(default=20, ge=3, le=1024)
    breachSeconds: float = Field(default=10, ge=1, le=3600)

    @model_validator(mode="after")
    def hysteresis(self):
        if self.returnP95Milliseconds >= self.maxP95Milliseconds:
            raise ValueError("return latency must be below breach threshold")
        return self


class AugmentationStage(Contract):
    variant: str = Field(min_length=1, max_length=31)
    label: str = Field(min_length=1, max_length=40)


class Policy(Contract):
    stages: list[AugmentationStage] = Field(default_factory=list, max_length=32)
    mode: Literal["automatic", "preferred"] = "automatic"
    approvalRequired: bool = False
    preferredRole: Literal["edge", "server"] = "edge"
    allowedRoles: list[Literal["edge", "server"]] = Field(default_factory=lambda: ["edge", "server"], min_length=1)
    nodeSelector: dict[str, str] = Field(default_factory=dict)
    highWatermark: float = Field(default=0.8, gt=0, le=1)
    lowWatermark: float = Field(default=0.2, ge=0, lt=1)
    pressureSeconds: float = Field(default=10, ge=1, le=3600)
    returnSeconds: float = Field(default=60, ge=1, le=86400)
    cooldownSeconds: float = Field(default=30, ge=1, le=86400)
    prepareTimeoutSeconds: float = Field(default=180, ge=5, le=1800)
    latency: LatencyPolicy | None = None

    @model_validator(mode="after")
    def thresholds(self):
        if self.lowWatermark >= self.highWatermark or self.preferredRole not in self.allowedRoles:
            raise ValueError("invalid hysteresis or preferred role")
        return self


class DemoContract(Contract):
    label: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]
    maxRequests: int = Field(default=512, ge=1, le=512)
    concurrency: int = Field(default=6, ge=1, le=8)
    pressureSeconds: float = Field(default=25, ge=1, le=40)
    recoverySeconds: float = Field(default=120, ge=1, le=120)
    recoveryIntervalSeconds: float = Field(default=1, ge=.5, le=10)


class ServiceSpec(Contract):
    execution: Literal["http-json-v1"] = "http-json-v1"
    ioContract: str = Field(min_length=1, max_length=128)
    port: int = Field(default=8080, ge=1024, le=65535)
    readyPath: str = "/ready"
    requestPath: str = "/infer"
    timeoutSeconds: float = Field(default=30, ge=1, le=300)
    maxBodyBytes: int = Field(default=65536, ge=1, le=1048576)
    variants: list[Variant] = Field(min_length=1, max_length=32)
    policy: Policy = Field(default_factory=Policy)
    suspended: bool = False
    inference: InferenceContract | None = None
    demo: DemoContract | None = None

    @field_validator("readyPath", "requestPath")
    @classmethod
    def relative_path(cls, value):
        if not re.fullmatch(r"/[A-Za-z0-9_/-]*", value) or ".." in value or "//" in value:
            raise ValueError("fixed relative HTTP path required")
        return value

    @model_validator(mode="after")
    def unique_variants(self):
        if self.policy.approvalRequired and (not self.inference or not self.demo):
            raise ValueError("approval requires an opted-in AI inference demo")
        if len({v.name for v in self.variants}) != len(self.variants):
            raise ValueError("duplicate variant")
        if self.policy.stages:
            ordered = [s.variant for s in self.policy.stages]
            if (not self.policy.approvalRequired or not self.inference
                    or len(ordered) != len(set(ordered))
                    or set(ordered) != {v.name for v in self.variants}):
                raise ValueError("stages require an approval-enabled AI service and each variant exactly once")
            variants = {v.name: v for v in self.variants}
            capacities = [variants[name].qualifiedRps for name in ordered]
            if (any(value is None for value in capacities)
                    or any(a >= b for a, b in zip(capacities, capacities[1:]))):
                raise ValueError("stages require strictly increasing qualified request rates")
        if any(v.resident for v in self.variants):
            if not self.inference or not all(v.resident for v in self.variants):
                raise ValueError("resident Llama variants require one common inference contract")
        elif self.inference:
            raise ValueError("inference contract is only consumed by the resident Llama adapter")
        if self.demo:
            if self.timeoutSeconds > 30 or len(json.dumps(self.demo.payload, allow_nan=False).encode()) > min(self.maxBodyBytes, 65536):
                raise ValueError("demo requires timeout <= 30s and a bounded JSON input")
            if self.inference and self.demo.payload != {"prompt": self.inference.prompt, "max_tokens": self.inference.maxTokens}:
                raise ValueError("demo input must match the qualified inference contract")
        return self


def revision(spec: ServiceSpec, variant: Variant, node: str) -> str:
    # Policy-only edits do not replace healthy workload revisions.
    variant_data = variant.model_dump()
    variant_data.pop("qualifiedP95Milliseconds")  # Measurement metadata does not replace a Pod.
    if variant.resident is None:
        variant_data.pop("resident")
    if variant.qualifiedRps is None:
        variant_data.pop("qualifiedRps")
    content = {"variant": variant_data, "node": node, "port": spec.port,
               "readyPath": spec.readyPath, "ioContract": spec.ioContract}
    if variant.resident:
        content["inference"] = spec.inference.model_dump()
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:12]
