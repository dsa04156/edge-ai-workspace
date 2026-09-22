"""Same-origin adapter for bounded runtime-owner settings, never direct K8s writes."""
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field


class PolicySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["automatic", "preferred", "approval"]
    preferredRole: Literal["edge", "server"]
    nodeName: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{0,252}$")
    highWatermark: float = Field(gt=0, le=1)
    lowWatermark: float = Field(ge=0, lt=1)
    pressureSeconds: float = Field(ge=1, le=3600)
    returnSeconds: float = Field(ge=1, le=86400)
    cooldownSeconds: float = Field(ge=1, le=86400)


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    specRevision: str = Field(pattern=r"^[a-f0-9]{64}$")
    settings: PolicySettings


class DefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    specRevision: str = Field(pattern=r"^[a-f0-9]{64}$")
    spec: dict


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    spec: dict


class Constraints(BaseModel):
    modes: list[Literal["automatic", "preferred", "approval"]]
    roles: list[Literal["edge", "server"]]
    nodes: list[str]
    nodeSelectionAllowed: bool


class Variant(BaseModel):
    name: str
    image: str
    architecture: str
    requests: dict[str, str]
    limits: dict[str, str]


class SettingsView(BaseModel):
    uid: str
    name: str
    specRevision: str
    observedAt: float
    editable: bool
    reason: str | None = None
    settings: PolicySettings
    constraints: Constraints
    variants: list[Variant]
    spec: dict | None = None
    definitionEditable: bool = False
    definitionReason: str | None = None


def create_service_settings_router(settings, *, transport=None):
    router = APIRouter()

    def enabled():
        if not getattr(settings, "common_runtime_demo_enabled", False):
            raise HTTPException(403, "common_runtime_demo_disabled")

    def same_origin(request):
        enabled()
        if (request.headers.get("origin") != str(request.base_url).rstrip("/")
                or request.headers.get("x-runtime-demo") != "1"
                or request.headers.get("content-type", "").split(";")[0] != "application/json"):
            raise HTTPException(403, "same_origin_settings_action_required")

    async def forward(method, name, uid, body=None, suffix="settings"):
        try:
            async with httpx.AsyncClient(transport=transport, timeout=5, trust_env=False, follow_redirects=False) as client:
                path = "/services/registration" if method == "POST" else f"/services/{name}/{suffix}"
                response = await client.request(method, settings.common_runtime_url.rstrip("/") + path,
                    params={"serviceUid": uid} if method == "GET" else None, json=body)
            if response.status_code >= 400:
                data = response.json()
                raise HTTPException(response.status_code if response.status_code < 500 else 503,
                                    str(data.get("detail", "settings_request_rejected"))[:160])
            response.raise_for_status()
            value = SettingsView.model_validate(response.json())
            if (uid is not None and value.uid != uid) or value.name != name or not value.uid: raise ValueError("identity mismatch")
            return value
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise HTTPException(503, "settings_source_unavailable") from None

    @router.post("/api/service-virtual-devices/registration", response_model=SettingsView, status_code=201)
    async def register(body: RegistrationRequest, request: Request, response: Response):
        same_origin(request); response.headers["Cache-Control"] = "no-store"
        return await forward("POST", body.name, None, body.model_dump())

    @router.put("/api/service-virtual-devices/{name}/definition", response_model=SettingsView)
    async def definition(body: DefinitionRequest, request: Request, response: Response,
                         name: str = Path(pattern=r"^[a-z0-9-]{1,63}$")):
        same_origin(request); response.headers["Cache-Control"] = "no-store"
        return await forward("PUT", name, body.serviceUid, body.model_dump(), "definition")

    @router.get("/api/service-virtual-devices/{name}/settings", response_model=SettingsView)
    async def read(response: Response, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$"),
                   serviceUid: str = Query(pattern=r"^[A-Za-z0-9-]{1,80}$")):
        enabled(); response.headers["Cache-Control"] = "no-store"
        return await forward("GET", name, serviceUid)

    @router.put("/api/service-virtual-devices/{name}/settings", response_model=SettingsView)
    async def save(body: SettingsRequest, request: Request, response: Response,
                   name: str = Path(pattern=r"^[a-z0-9-]{1,63}$")):
        same_origin(request)
        response.headers["Cache-Control"] = "no-store"
        return await forward("PUT", name, body.serviceUid, body.model_dump())

    return router
