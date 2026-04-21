from __future__ import annotations

from fastapi import FastAPI

from .api_models import (
    AggregatorSummary,
    PlacementDecisionRequest,
    PlacementDecisionResponse,
    ReplanWorkflowRequest,
    ReplanWorkflowResponse,
)
from .config import Settings
from .service import PlacementService

settings = Settings()
service = PlacementService(settings)

app = FastAPI(title="placement-engine", version="0.1.0")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/state/nodes", response_model=AggregatorSummary)
async def get_nodes():
    node_states = await service.get_node_states()
    return AggregatorSummary(node_states=node_states, source=settings.state_aggregator_url)


@app.post("/placement/decide", response_model=PlacementDecisionResponse)
async def placement_decide(request: PlacementDecisionRequest) -> PlacementDecisionResponse:
    decision = await service.decide(request)
    return PlacementDecisionResponse(decision=decision)


@app.post("/placement/replan", response_model=ReplanWorkflowResponse)
async def placement_replan(request: ReplanWorkflowRequest) -> ReplanWorkflowResponse:
    decisions = await service.replan(request)
    return ReplanWorkflowResponse(decisions=decisions)
