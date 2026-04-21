from __future__ import annotations

import httpx

from .api_models import PlacementDecisionRequest, ReplanWorkflowRequest
from .config import Settings
from .engine import decide_stage_placement, replan_workflow
from .models import NodeState, PlacementDecision


class PlacementService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_node_states(self) -> list[NodeState]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.settings.state_aggregator_url}/state/nodes")
            response.raise_for_status()
            payload = response.json()
        return [NodeState(**item) for item in payload]

    async def decide(self, request: PlacementDecisionRequest) -> PlacementDecision:
        node_states = request.node_states or await self.get_node_states()
        return decide_stage_placement(
            workflow_id=request.workflow_id,
            stage_id=request.stage_id,
            node_profiles=request.node_profiles,
            node_states=node_states,
            stage_metadata=request.stage_metadata,
            current_placement=request.current_placement,
            workflow_type=request.workflow_type,
        )

    async def replan(self, request: ReplanWorkflowRequest) -> list[PlacementDecision]:
        node_states = request.node_states or await self.get_node_states()
        return replan_workflow(
            workflow_id=request.workflow_id,
            stages=[item.model_dump() for item in request.stages],
            node_profiles=request.node_profiles,
            node_states=node_states,
            current_placement=request.current_placement,
            workflow_type=request.workflow_type,
        )
