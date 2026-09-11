"""Read-only projection of the common RuntimeService operator, separate from EdgeX."""
from __future__ import annotations

import time
from typing import Literal

import httpx
from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field


class RuntimeHealth(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    ready: bool
    inFlight: int = Field(ge=0)
    modelVramMiB: float | None = Field(default=None, ge=0)
    nodeState: str | None = None


class Observation(BaseModel):
    at: float
    health: RuntimeHealth | None = None


class RuntimeTarget(BaseModel):
    name: str
    node: str
    role: str
    variant: str
    capacity: int
    observation: Observation | None = None
    resident: dict | None = Field(default=None, exclude=True)
    memoryOnlyRelease: bool = False


class Transition(BaseModel):
    fromNode: str | None = None
    toNode: str
    at: float
    reason: str


class Release(BaseModel):
    node: str
    at: float
    modelVramMiB: float = Field(ge=0)
    reservationRetained: bool


class Exclusion(BaseModel):
    node: str
    variant: str
    reasons: list[str]


class RuntimeCandidate(BaseModel):
    node: str
    variant: str
    role: str


class LatencyObservation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    at: float
    target: str
    samples: int = Field(ge=0)
    successfulSamples: int = Field(ge=0)
    failures: int = Field(ge=0)
    p95Milliseconds: float | None = Field(default=None, ge=0)
    valid: bool
    reason: str
    maxP95Milliseconds: float = Field(gt=0)
    returnP95Milliseconds: float = Field(gt=0)
    windowSeconds: float = Field(gt=0)
    scope: Literal["gateway_queue_and_worker_response"]
    processLocal: bool
    completedRps: float | None = Field(default=None, ge=0)
    arrivalRps: float | None = Field(default=None, ge=0)
    failureRatio: float | None = Field(default=None, ge=0, le=1)


class RuntimeLoad(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    inFlightAndPending: int = Field(ge=0)
    utilization: float = Field(ge=0)
    pending: int | None = Field(default=None, ge=0)
    inFlight: int | None = Field(default=None, ge=0)
    capacity: int | None = None
    qualifiedRps: float | None = None
    at: float | None = None


class AugmentationProposal(BaseModel):
    id: str
    createdAt: float
    expiresAt: float
    sourceNode: str
    node: str
    role: str
    variant: str
    reason: str
    qualifiedRps: float | None = None
    qualifiedP95Milliseconds: float | None = None
    status: str | None = None
    approvedAt: float | None = None
    startedAt: float | None = None
    finishedAt: float | None = None


class AugmentationStage(BaseModel):
    step: int
    label: str
    variant: str
    node: str | None = None
    eligible: bool
    qualifiedRps: float | None = None
    qualifiedP95Milliseconds: float | None = None


class RuntimeItem(BaseModel):
    augmentationStages: list[AugmentationStage] = Field(default_factory=list)
    name: str
    uid: str
    phase: str
    reason: str | None = None
    serving: bool = False
    checkedAt: float | None = None
    active: RuntimeTarget | None = None
    target: RuntimeTarget | None = None
    retiring: list[RuntimeTarget] = Field(default_factory=list)
    lastTransition: Transition | None = None
    lastRelease: Release | None = None
    excludedCandidates: list[Exclusion] = Field(default_factory=list)
    eligibleCandidates: list[RuntimeCandidate] = Field(default_factory=list)
    observation_error: str | None = None
    latency: LatencyObservation | None = None
    load: RuntimeLoad | None = None
    approvalRequired: bool = False
    aiInference: bool = False
    proposal: AugmentationProposal | None = None
    lastApproval: AugmentationProposal | None = None


class RuntimeState(BaseModel):
    schema_version: Literal["edgeai.common-runtime/v1"] = "edgeai.common-runtime/v1"
    source: Literal["kubernetes-runtime-operator"] = "kubernetes-runtime-operator"
    observed_at: float
    snapshot_age_seconds: float | None = None
    observation_error: str | None = None
    services: list[RuntimeItem] = Field(default_factory=list)


def project(payload: dict, now: float) -> RuntimeState:
    age = payload["snapshotAgeSeconds"]
    if type(age) not in (int, float) or not 0 <= age < float("inf"):
        raise ValueError("invalid_snapshot_age")
    result = RuntimeState(observed_at=now, snapshot_age_seconds=age)
    if age >= 15 or payload.get("lastError"):
        result.observation_error = "runtime_snapshot_stale" if age >= 15 else "runtime_operator_error"
    for raw in payload["services"]:
        item = RuntimeItem.model_validate(raw)
        if item.phase in {"Deleted", "Missing"}:
            continue
        current = item.checkedAt is not None and 0 <= now - item.checkedAt < 15
        if result.observation_error or not current:
            item.observation_error = result.observation_error or "runtime_service_observation_stale"
            item.serving = False
            item.load = None
            item.proposal = None
            item.eligibleCandidates = []
            for stage in item.augmentationStages:
                stage.eligible = False
        if item.load and (item.load.at is None or not 0 <= now - item.load.at < 15):
            item.load = None
        if (item.latency and (item.observation_error or not item.active
                or item.latency.target != item.active.name or not 0 <= now - item.latency.at < 15)):
            item.latency = None
        for target in [item.active, item.target, *item.retiring]:
            if target:
                target.memoryOnlyRelease = target.resident is not None
                if (item.observation_error or not target.observation
                        or not 0 <= now - target.observation.at < 15):
                    target.observation = None
        result.services.append(item)
    return result


def create_common_runtime_router(settings, *, transport=None, clock=time.time):
    router = APIRouter()

    @router.get("/state/runtime-services", response_model=RuntimeState)
    async def read_runtime(response: Response):
        response.headers["Cache-Control"] = "no-store"
        try:
            async with httpx.AsyncClient(transport=transport, timeout=3, follow_redirects=False,
                                         trust_env=False) as client:
                upstream = await client.get(settings.common_runtime_url.rstrip("/") + "/services")
                upstream.raise_for_status()
                return project(upstream.json(), clock())
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return RuntimeState(observed_at=clock(), observation_error="runtime_source_unavailable")

    return router
