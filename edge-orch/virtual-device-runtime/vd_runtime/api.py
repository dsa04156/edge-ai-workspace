from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .model import ModelAdapter, load_adapter


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    clientId: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    features: list[Annotated[float, Field(strict=True, ge=0, le=30, allow_inf_nan=False)]] = Field(min_length=4, max_length=4)


class Runtime:
    def __init__(self, adapter: ModelAdapter | None = None):
        self.device_id = os.getenv("VD_ID", "vd-demo-001")
        self.pod_uid = os.getenv("POD_UID") or None
        self.boot_id = str(uuid.uuid4())
        self.started_at = now()
        self.adapter = adapter
        self.error = None
        if adapter is None:
            try:
                self.adapter = load_adapter(
                    os.getenv("MODEL_ADAPTER", "nearest-centroid"),
                    Path(os.getenv("MODEL_PATH", str(Path(__file__).parents[1] / "models/iris-centroids.json"))),
                )
            except Exception as exc:
                self.error = f"model_load_failed: {type(exc).__name__}: {exc}"
        self.draining = False
        self.in_flight = self.succeeded = self.failed = self.rejected = 0
        self.last_processed_at = self.last_success = None
        self.last_cpu = time.process_time()
        self.last_clock = time.monotonic()
        self.cpu_cores = None
        self.cpu_observed_at = None

    @property
    def ready(self) -> bool:
        return self.adapter is not None and self.error is None and not self.draining

    def model(self) -> dict:
        return {"id": getattr(self.adapter, "model_id", None),
                "version": getattr(self.adapter, "version", None),
                "sha256": getattr(self.adapter, "digest", None)}

    def status(self) -> dict:
        clock, cpu = time.monotonic(), time.process_time()
        if clock - self.last_clock >= 0.1:
            self.cpu_cores = max(0.0, (cpu - self.last_cpu) / (clock - self.last_clock))
            self.last_clock, self.last_cpu = clock, cpu
            self.cpu_observed_at = now()
        rss, usage_error = None, None
        try:
            rss = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError) as exc:
            usage_error = f"rss_unavailable: {type(exc).__name__}"
        return {
            "virtualDeviceId": self.device_id, "podUid": self.pod_uid, "bootId": self.boot_id,
            "startedAt": self.started_at, "observedAt": now(), "model": self.model(),
            "modelReady": self.ready, "draining": self.draining, "inFlight": self.in_flight,
            "succeeded": self.succeeded, "failed": self.failed, "rejected": self.rejected,
            "lastProcessedAt": self.last_processed_at, "lastSuccess": self.last_success,
            "error": self.error, "counterScope": "process_boot",
            "usage": {"scope": "main_process", "cpuCores": self.cpu_cores,
                      "cpuObservedAt": self.cpu_observed_at, "memoryBytes": rss,
                      "observedAt": now(), "error": usage_error},
        }

    async def infer(self, request: InferenceRequest) -> dict:
        if not self.ready:
            self.rejected += 1
            raise HTTPException(503, detail="draining" if self.draining else self.error or "model_not_ready")
        if self.in_flight >= 8:
            self.rejected += 1
            raise HTTPException(429, detail="in_flight_limit")
        self.in_flight += 1
        started = time.monotonic()
        task = asyncio.create_task(asyncio.to_thread(self.adapter.infer, request.features))
        try:
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                # Do not report a released request while its model thread still runs.
                result = await task
            json.dumps(result, allow_nan=False)
            response = {
                "virtualDeviceId": self.device_id, "podUid": self.pod_uid, "bootId": self.boot_id,
                "requestId": request.requestId, "clientId": request.clientId, "model": self.model(),
                "inputSha256": hashlib.sha256(json.dumps(request.features, separators=(",", ":")).encode()).hexdigest(),
                "result": result, "completedAt": now(),
                "processingMs": (time.monotonic() - started) * 1000,
            }
            self.succeeded += 1
            self.last_success = response
            return response
        except Exception as exc:
            self.failed += 1
            self.error = f"model_inference_failed: {type(exc).__name__}"
            raise HTTPException(503, detail=self.error) from exc
        finally:
            self.last_processed_at = now()
            self.in_flight -= 1


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or Runtime()

    @asynccontextmanager
    async def lifespan(app):
        yield
        runtime.draining = True
        while runtime.in_flight:
            await asyncio.sleep(0.01)

    app = FastAPI(title="Container virtual device", lifespan=lifespan)
    app.state.runtime = runtime

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, exc):
        runtime.rejected += 1
        return JSONResponse(status_code=422, content={"detail": "invalid requestId/clientId or four finite features (0..30 cm)"})

    @app.get("/healthz")
    async def health():
        return {"healthy": True}

    @app.get("/readyz")
    async def ready():
        return JSONResponse(status_code=200 if runtime.ready else 503,
                            content={"ready": runtime.ready, "error": runtime.error, "draining": runtime.draining})

    @app.get("/status")
    async def status():
        return runtime.status()

    @app.post("/infer")
    async def infer(request: InferenceRequest):
        return await runtime.infer(request)

    return app
