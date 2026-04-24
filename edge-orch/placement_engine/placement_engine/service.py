from __future__ import annotations

import httpx

from .api_models import CostModelSnapshot, PlacementDecisionRequest, ReplanWorkflowRequest
from .config import Settings
from .engine import decide_stage_placement, replan_workflow
from .models import MigrationCostStats, NodeState, PlacementDecision, StageCostStats


class PlacementService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_node_states(self) -> list[NodeState]:
        snapshot = await self.get_cost_model()
        return snapshot.node_states

    async def get_cost_model(self) -> CostModelSnapshot:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.settings.state_aggregator_url}/state/cost-model")
            response.raise_for_status()
            payload = response.json()
        payload.setdefault("source", self.settings.state_aggregator_url)
        return CostModelSnapshot(**payload)

    async def decide(self, request: PlacementDecisionRequest) -> PlacementDecision:
        snapshot = None
        if request.node_states is None:
            snapshot = await self.get_cost_model()
        node_states = request.node_states or (snapshot.node_states if snapshot is not None else [])
        stage_cost_stats = request.stage_cost_stats or (snapshot.stage_cost_stats if snapshot is not None else [])
        migration_cost_stats = request.migration_cost_stats or (
            snapshot.migration_cost_stats if snapshot is not None else []
        )
        return decide_stage_placement(
            workflow_id=request.workflow_id,
            stage_id=request.stage_id,
            node_profiles=request.node_profiles,
            node_states=node_states,
            stage_cost_stats=stage_cost_stats,
            migration_cost_stats=migration_cost_stats,
            stage_metadata=request.stage_metadata,
            current_placement=request.current_placement,
            workflow_type=request.workflow_type,
        )

    async def replan(self, request: ReplanWorkflowRequest) -> list[PlacementDecision]:
        snapshot = None
        if request.node_states is None:
            snapshot = await self.get_cost_model()
        node_states = request.node_states or (snapshot.node_states if snapshot is not None else [])
        stage_cost_stats = request.stage_cost_stats or (snapshot.stage_cost_stats if snapshot is not None else [])
        migration_cost_stats = request.migration_cost_stats or (
            snapshot.migration_cost_stats if snapshot is not None else []
        )
        return replan_workflow(
            workflow_id=request.workflow_id,
            stages=[item.model_dump() for item in request.stages],
            node_profiles=request.node_profiles,
            node_states=node_states,
            stage_cost_stats=stage_cost_stats,
            migration_cost_stats=migration_cost_stats,
            current_placement=request.current_placement,
            workflow_type=request.workflow_type,
        )
