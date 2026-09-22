"""Service identity projection: one registered RuntimeService, one virtual device.

Execution targets are operator revisions, NOT Kubernetes Pod observations.
This adapter never discovers services from arbitrary Pods or mutates runtimes.
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from .common_runtime import RuntimeContractSummary, RuntimeState, read_runtime_state


class ServiceLocation(BaseModel):
    revision: str
    node: str
    role: Literal["active", "preparing", "retiring"]
    ready: bool | None = None
    in_flight: int | None = None
    observed_at: float | None = None
    resident: bool = False


class ServiceDevice(BaseModel):
    id: str
    service_uid: str
    service_name: str
    namespace: str = "platform-runtime"
    service_kind: Literal["ai", "service", "test"]
    state: Literal["running", "starting", "stopping", "stopped", "blocked", "unknown"]
    serving: bool | None = None
    checked_at: float | None = None
    observation_error: str | None = None
    contract: RuntimeContractSummary | None = None
    locations: list[ServiceLocation] = Field(default_factory=list)


class ServiceDeviceState(BaseModel):
    schema_version: Literal["edgeai.service-virtual-devices/v1"] = "edgeai.service-virtual-devices/v1"
    source: Literal["kubernetes-runtime-operator"] = "kubernetes-runtime-operator"
    observed_at: float
    max_age_seconds: int = 15
    observation_error: str | None = None
    total: int | None = None
    running: int | None = None
    devices: list[ServiceDevice] = Field(default_factory=list)


def project_service_devices(snapshot: RuntimeState, now: float, namespace: str = "platform-runtime") -> ServiceDeviceState:
    result = ServiceDeviceState(observed_at=snapshot.observed_at,
                                observation_error=snapshot.observation_error)
    if not 0 <= now - snapshot.observed_at < 15:
        result.observation_error = "runtime_snapshot_stale"
    for service in snapshot.services:
        if service.phase in {"Deleted", "Missing"}:
            continue
        error = result.observation_error or service.observation_error
        if service.checkedAt is None or not 0 <= now - service.checkedAt < 15:
            error = error or "runtime_service_observation_stale"
        active_health = service.active.observation.health if service.active and service.active.observation else None
        active_current = bool(service.active and service.active.observation
                              and 0 <= now - service.active.observation.at < 15)
        serving = bool(service.serving and active_current and active_health and active_health.ready)
        state = "unknown"
        if not error:
            if service.phase == "Suspended" and not any([service.active, service.target, *service.retiring]):
                state = "stopped"
            elif service.phase == "Draining":
                state = "stopping"
            elif serving:
                state = "running"
            elif service.phase in {"Preparing", "Reconciling"}:
                state = "starting"
            elif service.phase == "Blocked":
                state = "blocked"
        row = ServiceDevice(id="runtime:" + service.uid, service_uid=service.uid,
                            service_name=service.name, namespace=namespace, service_kind=service.serviceKind,
                            state=state, serving=None if error or state == "unknown" else serving,
                            checked_at=service.checkedAt, observation_error=error,
                            contract=service.contractSummary)
        if not error:
            for role, targets in [("active", [service.active]), ("preparing", [service.target]),
                                  ("retiring", service.retiring)]:
                for target in targets:
                    if target is None:
                        continue
                    observation = target.observation
                    current = bool(observation and 0 <= now - observation.at < 15)
                    health = observation.health if current else None
                    row.locations.append(ServiceLocation(revision=target.name, node=target.node,
                        role=role, ready=health.ready if health else None,
                        in_flight=health.inFlight if health else None,
                        observed_at=observation.at if current else None,
                        resident=target.memoryOnlyRelease))
        result.devices.append(row)
    if not result.observation_error:
        result.total = len(result.devices)
        if all(d.serving is not None for d in result.devices):
            result.running = sum(d.serving for d in result.devices)
    return result


def create_service_virtual_device_router(settings, *, transport=None, clock=time.time, reader=None):
    router = APIRouter()
    lock = asyncio.Lock()
    previous: RuntimeState | None = None

    @router.get("/api/service-virtual-devices", response_model=ServiceDeviceState)
    async def read_service_devices(response: Response):
        nonlocal previous
        response.headers["Cache-Control"] = "no-store"
        async with lock:
            snapshot = (await reader() if reader else
                        await read_runtime_state(settings, transport=transport, clock=clock))
            if snapshot.observation_error == "runtime_source_unavailable" and previous is not None:
                snapshot = previous.model_copy(deep=True, update={
                    "observed_at": clock(), "observation_error": snapshot.observation_error})
            elif not snapshot.observation_error:
                previous = snapshot.model_copy(deep=True)
            return project_service_devices(snapshot, clock(), getattr(settings, "common_runtime_namespace", "platform-runtime"))

    return router
