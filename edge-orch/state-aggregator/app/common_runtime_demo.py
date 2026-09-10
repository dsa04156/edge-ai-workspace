"""Token-free, same-origin access to explicitly opted-in RuntimeService demos."""
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field


class DemoItem(BaseModel):
    name: str
    uid: str
    label: str
    inputPreview: str
    maxRequests: int
    concurrency: int
    pressureSeconds: float
    recoverySeconds: float
    available: bool
    retryAfterSeconds: int = 0


class DemoRoute(BaseModel):
    at: float
    node: str
    role: str
    reason: str | None = None


class DemoReceipt(BaseModel):
    id: str
    state: str
    status: int | None = None
    target: str | None = None
    elapsedMilliseconds: float | None = None


class DemoRun(BaseModel):
    id: str
    uid: str
    name: str
    label: str
    mode: Literal["single", "round-trip"]
    phase: Literal["Running", "Stopping", "Stopped", "Completed", "Incomplete", "Interrupted"]
    stage: str
    createdAt: float
    finishedAt: float | None = None
    sent: int
    succeeded: int
    failed: int
    unknown: int
    lastResult: str | None = None
    routeHistory: list[DemoRoute]
    recentRequests: list[DemoReceipt]
    startNode: str
    startRole: str
    currentNode: str | None = None
    returned: bool
    retiring: int
    reason: str | None = None
    stopRequested: bool


class DemoState(BaseModel):
    enabled: bool = True
    items: list[DemoItem] = Field(default_factory=list)
    runs: list[DemoRun] = Field(default_factory=list)
    observedAt: float
    observation_error: str | None = None


class DemoStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    mode: Literal["single", "round-trip"]


class DemoStop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")


def create_common_demo_router(settings, *, transport=None, clock=time.time):
    router = APIRouter()
    enabled = getattr(settings, "common_runtime_demo_enabled", False)

    def require_enabled():
        if not enabled:
            raise HTTPException(403, "common_runtime_demo_disabled")

    def authorize(request):
        require_enabled()
        if (request.headers.get("origin") != str(request.base_url).rstrip("/")
                or request.headers.get("x-runtime-demo") != "1"
                or request.headers.get("content-type", "").split(";")[0] != "application/json"):
            raise HTTPException(403, "same_origin_demo_action_required")

    async def upstream(method, path, body=None, params=None):
        try:
            async with httpx.AsyncClient(transport=transport, timeout=4, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, settings.common_runtime_url.rstrip("/") + path,
                                                json=body, params=params)
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("invalid_demo_response")
            if response.status_code >= 400:
                raise HTTPException(response.status_code if response.status_code < 500 else 503,
                                    str(data.get("detail", "demo_request_rejected"))[:160])
            response.raise_for_status()
            return data
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "demo_source_unavailable") from None

    @router.get("/state/runtime-demos", response_model=DemoState)
    async def state(response: Response):
        response.headers["Cache-Control"] = "no-store"
        if not enabled:
            return DemoState(enabled=False, observedAt=clock())
        try:
            return DemoState.model_validate(await upstream("GET", "/demos"))
        except (HTTPException, ValueError):
            return DemoState(observedAt=clock(), observation_error="demo_source_unavailable")

    @router.get("/state/runtime-demos/{name}/runs/{run_id}", response_model=DemoRun)
    async def get_run(response: Response, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$"),
                      run_id: str = Path(pattern=r"^[A-Za-z0-9_-]{8,80}$"),
                      serviceUid: str = Query(pattern=r"^[A-Za-z0-9-]{1,80}$")):
        require_enabled()
        response.headers["Cache-Control"] = "no-store"
        try:
            return DemoRun.model_validate(await upstream("GET", f"/demos/{name}/runs/{run_id}", params={"serviceUid": serviceUid}))
        except ValueError:
            raise HTTPException(503, "demo_response_invalid") from None

    @router.post("/api/runtime-demos/{name}/runs/{run_id}", status_code=202, response_model=DemoRun)
    async def start(body: DemoStart, request: Request, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$"),
                    run_id: str = Path(pattern=r"^[A-Za-z0-9_-]{8,80}$")):
        authorize(request)
        try:
            return DemoRun.model_validate(await upstream("POST", f"/demos/{name}/runs/{run_id}", body.model_dump()))
        except ValueError:
            raise HTTPException(503, "demo_response_invalid") from None

    @router.post("/api/runtime-demos/{name}/runs/{run_id}/stop", response_model=DemoRun)
    async def stop(body: DemoStop, request: Request, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$"),
                   run_id: str = Path(pattern=r"^[A-Za-z0-9_-]{8,80}$")):
        authorize(request)
        try:
            return DemoRun.model_validate(await upstream("POST", f"/demos/{name}/runs/{run_id}/stop", body.model_dump()))
        except ValueError:
            raise HTTPException(503, "demo_response_invalid") from None

    return router
