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


class RuntimeItem(BaseModel):
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
    observation_error: str | None = None


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
