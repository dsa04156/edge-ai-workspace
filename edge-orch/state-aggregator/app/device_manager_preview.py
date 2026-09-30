"""Local NEXUS preview: local profile metadata and deployed dashboard reads."""
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .device_manager import DeviceSources, create_device_manager_router
from .kube import KubeClient

STATIC = Path(__file__).parent / "static"


def create_app(settings=None, *, sources=None, read_transport=None):
    settings = settings or Settings()
    if not settings.device_manager_read_base_url:
        raise ValueError("NEXUS preview requires DEVICE_MANAGER_READ_BASE_URL")
    if sources is None:
        sources = DeviceSources(settings, SimpleNamespace(kube=KubeClient()))
    app = FastAPI(title="NEXUS local preview", version="0.1.0")
    app.include_router(create_device_manager_router(settings, None, sources=sources))
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    @app.get("/dashboard")
    async def index():
        return FileResponse(STATIC / "nexus/index.html",
                            headers={"Cache-Control": "no-store"})

    async def read_dashboard(request: Request, path: str):
        # Fixed origin, GET only. Never forward credentials, writes or redirects.
        if path.startswith("v1/device-manager"):
            raise HTTPException(404)
        base = settings.device_manager_read_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=15, transport=read_transport,
                                         follow_redirects=False) as client:
                upstream = await client.get(base + request.url.path,
                                            params=request.query_params)
        except httpx.HTTPError as exc:
            raise HTTPException(502, "기존 대시보드 조회 원본에 연결할 수 없습니다.") from exc
        return Response(upstream.content, status_code=upstream.status_code,
                        headers={"Content-Type": upstream.headers.get("content-type", "application/json"),
                                 "Cache-Control": "no-store"})

    app.add_api_route("/api/{path:path}", read_dashboard, methods=["GET"])
    app.add_api_route("/state/{path:path}", read_dashboard, methods=["GET"])
    return app
