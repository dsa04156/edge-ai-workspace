from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .metrics import render_metrics
from .models import CostModelState, DashboardState, DeviceState, SummaryState, WorkflowEvent, WorkflowState
from .service import StateAggregatorService

settings = Settings()
service = StateAggregatorService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await service.start()
    yield
    await service.stop()


app = FastAPI(title="state-aggregator", version="0.1.0", lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    if (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    return {"service": "state-aggregator", "dashboard": "/dashboard"}


@app.get("/dashboard")
async def dashboard():
    if not (STATIC_DIR / "index.html").exists():
        raise HTTPException(status_code=404, detail="Dashboard assets not found")
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/workflow-event", response_model=WorkflowState)
async def post_workflow_event(event: WorkflowEvent) -> WorkflowState:
    return service.record_workflow_event(event)


@app.get("/state/nodes")
async def get_nodes():
    return service.get_nodes()


@app.get("/state/devices", response_model=list[DeviceState])
async def get_devices() -> list[DeviceState]:
    return await service.get_devices()


@app.get("/state/dashboard", response_model=DashboardState)
async def get_dashboard() -> DashboardState:
    return await service.get_dashboard()


@app.get("/state/node/{hostname}")
async def get_node(hostname: str):
    node = service.get_node(hostname)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@app.get("/state/workflows")
async def get_workflows():
    return service.get_workflows()


@app.get("/state/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    workflow = service.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@app.get("/state/summary", response_model=SummaryState)
async def get_summary() -> SummaryState:
    return service.get_summary()


@app.get("/state/cost-model", response_model=CostModelState)
async def get_cost_model() -> CostModelState:
    return service.get_cost_model()


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> PlainTextResponse:
    payload = render_metrics(
        node_states=service.get_nodes(),
        workflow_states=service.get_workflows(),
        summary=service.get_summary(),
    )
    return PlainTextResponse(
        content=payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/internal/refresh")
async def refresh_nodes():
    return await service.refresh_nodes()
# trigger cds
