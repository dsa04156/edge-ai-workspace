from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from .config import Settings
from .models import ResultEnvelope, ServiceStatus
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
    ) -> ResultEnvelope:
        rows = selected_runtime.results(limit)
        return ResultEnvelope(count=len(rows), results=rows)

    return application


app = create_app()
