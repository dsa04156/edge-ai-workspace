from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from .config import Settings
from .contracts import contract_schemas
from .models import (
    AlertEnvelope,
    ResultEnvelope,
    ServiceStatus,
    StorageStatus,
)
from .runtime import AnomalyRuntime, build_runtime


def create_app(
    runtime: AnomalyRuntime | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    selected_settings = settings or Settings.from_env()
    selected_runtime = runtime or build_runtime(selected_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await selected_runtime.start()
        try:
            yield
        finally:
            await selected_runtime.stop()

    application = FastAPI(
        title="sensor-anomaly-demo",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        if not selected_runtime.worker_started:
            raise HTTPException(status_code=503, detail="polling worker is not running")
        return {"status": "ok"}

    @application.get("/readyz")
    async def readyz() -> dict[str, str]:
        if not selected_runtime.worker_started:
            raise HTTPException(status_code=503, detail="polling worker is not running")
        return {"status": "ready"}

    @application.get("/api/v1/status", response_model=ServiceStatus)
    async def status() -> ServiceStatus:
        return selected_runtime.status()

    @application.get("/api/v1/results", response_model=ResultEnvelope)
    async def results(
        limit: int = Query(default=100, ge=1, le=1_000),
        anomaly: bool | None = Query(default=None),
        from_origin: int | None = Query(default=None, alias="fromOrigin", ge=1),
        to_origin: int | None = Query(default=None, alias="toOrigin", ge=1),
    ) -> ResultEnvelope:
        if (
            from_origin is not None
            and to_origin is not None
            and from_origin > to_origin
        ):
            raise HTTPException(
                status_code=422,
                detail="fromOrigin must not exceed toOrigin",
            )
        rows = selected_runtime.results(
            limit,
            anomaly=anomaly,
            from_origin=from_origin,
            to_origin=to_origin,
        )
        return ResultEnvelope(count=len(rows), results=rows)

    @application.get("/api/v1/alerts", response_model=AlertEnvelope)
    async def alerts(
        limit: int = Query(default=100, ge=1, le=1_000),
        status: Literal["open", "closed"] | None = Query(default=None),
    ) -> AlertEnvelope:
        rows = selected_runtime.alerts(limit, status=status)
        return AlertEnvelope(count=len(rows), alerts=rows)

    @application.get("/api/v1/storage", response_model=StorageStatus)
    async def storage() -> StorageStatus:
        return selected_runtime.storage_status()

    @application.get("/api/v1/contracts")
    async def contracts() -> dict[str, dict]:
        return contract_schemas()

    @application.get("/api/v1/contracts/{contract_name}")
    async def contract(contract_name: str) -> dict:
        schemas = contract_schemas()
        if contract_name not in schemas:
            raise HTTPException(status_code=404, detail="contract was not found")
        return schemas[contract_name]

    return application


app = create_app()
