from __future__ import annotations

import asyncio
import logging

from .config import Settings, load_instance_map
from .models import NodeState, SummaryState, WorkflowEvent, WorkflowState
from .normalizer import build_summary, normalize_node_state, normalize_workflow_state
from .prometheus import PrometheusClient
from .storage import StateStore
from .kube import KubeClient

logger = logging.getLogger(__name__)


class StateAggregatorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Keep fallback instance map for now, but it will be overridden by KubeClient
        self.instance_map = load_instance_map(settings.instance_map_path)
        self.store = StateStore(settings.data_dir)
        self.prometheus = PrometheusClient(settings.prometheus_url, self.instance_map)
        self.kube = KubeClient()
        self._poller_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._poller_task is None:
            self._poller_task = asyncio.create_task(self._poll_prometheus())

    async def stop(self) -> None:
        if self._poller_task is None:
            return
        self._poller_task.cancel()
        try:
            await self._poller_task
        except asyncio.CancelledError:
            pass
        self._poller_task = None

    async def _poll_prometheus(self) -> None:
        while True:
            try:
                await self.refresh_nodes()
            except Exception:
                logger.exception("Failed to refresh Prometheus node metrics")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def refresh_nodes(self) -> list[NodeState]:
        # Dynamically discover nodes from K8s API
        new_map = await self.kube.get_node_map()
        if new_map:
            self.prometheus.instance_map = new_map
            
        raw_nodes = await self.prometheus.collect_node_metrics()
        states = [normalize_node_state(item) for item in raw_nodes]
        for state in states:
            self.store.upsert_node_state(state)
        return states

    def record_workflow_event(self, event: WorkflowEvent) -> WorkflowState:
        previous = self.store.workflows.get(event.workflow_id)
        workflow_state = normalize_workflow_state(event, previous)
        self.store.record_workflow_event(event, workflow_state)
        return workflow_state

    def get_nodes(self) -> list[NodeState]:
        return self.store.get_node_states()

    def get_node(self, hostname: str) -> NodeState | None:
        return self.store.nodes.get(hostname)

    def get_workflows(self) -> list[WorkflowState]:
        return self.store.get_workflow_states()

    def get_workflow(self, workflow_id: str) -> WorkflowState | None:
        return self.store.workflows.get(workflow_id)

    def get_summary(self) -> SummaryState:
        return build_summary(self.get_nodes(), self.get_workflows())
