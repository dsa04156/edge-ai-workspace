from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from .config import Settings
from .metrics import render_metrics
from .models import SummaryState, WorkflowEvent, WorkflowState
from .service import StateAggregatorService

settings = Settings()
service = StateAggregatorService(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await service.start()
    yield
    await service.stop()


app = FastAPI(title="state-aggregator", version="0.1.0", lifespan=lifespan)


@app.post("/workflow-event", response_model=WorkflowState)
async def post_workflow_event(event: WorkflowEvent) -> WorkflowState:
    return service.record_workflow_event(event)


@app.get("/state/nodes")
async def get_nodes():
    return service.get_nodes()


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
