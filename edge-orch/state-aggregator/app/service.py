from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .config import Settings, load_instance_map
from .models import (
    CostModelState,
    DashboardState,
    DeviceState,
    NodeState,
    SummaryState,
    WorkflowEvent,
    WorkflowState,
)
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

    def get_cost_model(self) -> CostModelState:
        return CostModelState(
            node_states=self.get_nodes(),
            stage_cost_stats=self.store.get_stage_cost_stats(),
            migration_cost_stats=self.store.get_migration_cost_stats(),
        )

    async def get_devices(self) -> list[DeviceState]:
        raw_devices = await self.kube.get_devices()
        node_health = {node.hostname: node.node_health for node in self.get_nodes()}
        mapper_nodes = await self.kube.get_running_mapper_nodes()
        workflows = self.get_workflows()
        return [
            self._normalize_device(item, node_health, workflows, mapper_nodes)
            for item in raw_devices
        ]

    async def get_dashboard(self) -> DashboardState:
        nodes = self.get_nodes()
        devices = await self.get_devices()
        workflows = self.get_workflows()
        summary = build_summary(nodes, workflows)
        kpis = self._build_dashboard_kpis(nodes, devices, workflows)
        return DashboardState(
            generated_at=datetime.now(timezone.utc),
            nodes=nodes,
            devices=devices,
            workflows=workflows,
            summary=summary,
            kpis=kpis,
        )

    def _normalize_device(
        self,
        item: dict[str, Any],
        node_health: dict[str, str],
        workflows: list[WorkflowState],
        mapper_nodes: set[str] | None = None,
    ) -> DeviceState:
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        status_payload = item.get("status", {})
        name = metadata.get("name", "unknown-device")
        namespace = metadata.get("namespace", "default")
        properties = spec.get("properties") or []
        property_names = [prop.get("name") for prop in properties if isinstance(prop, dict) and prop.get("name")]
        node_name = spec.get("nodeName")
        protocol = (spec.get("protocol") or {}).get("protocolName")
        model = (spec.get("deviceModelRef") or {}).get("name")
        twin = status_payload.get("twins") or status_payload.get("twin") or {}
        telemetry_enabled = any(
            isinstance(prop, dict) and bool(prop.get("reportToCloud"))
            for prop in properties
        )
        service_connected = self._device_has_service_binding(name, node_name, workflows)
        device_type = self._classify_device(name, model, protocol)
        health, reason = self._device_health(
            status_payload,
            node_name,
            node_health,
            telemetry_enabled,
            protocol,
            mapper_nodes or set(),
        )
        return DeviceState(
            name=name,
            namespace=namespace,
            device_type=device_type,
            model=model,
            node_name=node_name,
            protocol=protocol,
            properties=property_names,
            telemetry_enabled=telemetry_enabled,
            service_connected=service_connected,
            status=health,
            status_reason=reason,
            twin=twin if isinstance(twin, dict) else {},
        )

    def _device_has_service_binding(
        self,
        device_name: str,
        node_name: str | None,
        workflows: list[WorkflowState],
    ) -> bool:
        for workflow in workflows:
            event = workflow.recent_event
            if event.get("device_id") == device_name or event.get("source_device") == device_name:
                return True
            if node_name and workflow.assigned_node == node_name:
                return True
        return False

    def _classify_device(self, name: str, model: str | None, protocol: str | None) -> str:
        text = " ".join(part for part in [name, model, protocol] if part).lower()
        if "twin" in text:
            return "device_twin"
        if "virtual" in text or "mqttvirtual" in text:
            return "virtual_device"
        if "rpi" in text or "raspi" in text:
            return "sensor_device"
        if "env" in text or "vib" in text or "act" in text:
            return "sensor_device"
        return "physical_device"

    def _device_health(
        self,
        status_payload: dict[str, Any],
        node_name: str | None,
        node_health: dict[str, str],
        telemetry_enabled: bool,
        protocol: str | None = None,
        mapper_nodes: set[str] | None = None,
    ) -> tuple[str, str]:
        mapper_nodes = mapper_nodes or set()
        if node_name and node_health.get(node_name) == "unavailable":
            return "unavailable", "assigned node is unavailable"
        live_state = self._read_live_device_state(status_payload)
        if live_state in {"online", "connected", "healthy", "active", "true"}:
            return "healthy", f"device status is {live_state}"
        if live_state in {"offline", "disconnected", "failed", "unavailable", "false"}:
            return "unavailable", f"device status is {live_state}"
        if node_name and node_health.get(node_name) == "degraded":
            return "degraded", "assigned node is degraded"
        twin = status_payload.get("twins") or status_payload.get("twin") or {}
        if self._has_reported_twin(twin):
            return "healthy", "device twin reported live values"
        if (
            node_name
            and node_health.get(node_name) == "healthy"
            and node_name in mapper_nodes
            and telemetry_enabled
            and protocol == "mqttvirtual"
        ):
            return "healthy", "assigned node and mapper are running"
        if status_payload.get("reportToCloud") is False:
            return "unavailable", "no live report from device twin"
        if not status_payload or set(status_payload).issubset({"reportCycle", "reportToCloud"}):
            return "unavailable", "no live device status reported"
        if not telemetry_enabled:
            return "degraded", "telemetry-to-cloud is disabled"
        return "degraded", "registered but live status is unknown"

    def _read_live_device_state(self, status_payload: dict[str, Any]) -> str | None:
        for key in ("status", "phase", "state", "connection", "connected", "health"):
            value = status_payload.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value).lower()
        return None

    def _has_reported_twin(self, twin: Any) -> bool:
        if not isinstance(twin, dict):
            return False
        for value in twin.values():
            if not isinstance(value, dict):
                continue
            actual = value.get("actual") or value.get("reported")
            if isinstance(actual, dict) and actual.get("value") not in (None, ""):
                return True
            if actual not in (None, "") and not isinstance(actual, dict):
                return True
        return False

    def _build_dashboard_kpis(
        self,
        nodes: list[NodeState],
        devices: list[DeviceState],
        workflows: list[WorkflowState],
    ) -> dict[str, Any]:
        online_nodes = [node for node in nodes if node.node_health != "unavailable"]
        healthy_devices = [device for device in devices if device.status == "healthy"]
        telemetry_devices = [device for device in devices if device.telemetry_enabled]
        bound_devices = [device for device in devices if device.service_connected]
        risk_workflows = [workflow for workflow in workflows if workflow.sla_risk != "low"]
        return {
            "node_online_ratio": self._ratio(len(online_nodes), len(nodes)),
            "device_healthy_ratio": self._ratio(len(healthy_devices), len(devices)),
            "device_telemetry_ratio": self._ratio(len(telemetry_devices), len(devices)),
            "device_workflow_binding_ratio": self._ratio(len(bound_devices), len(devices)),
            "registered_device_count": len(devices),
            "active_node_count": len(online_nodes),
            "telemetry_device_count": len(telemetry_devices),
            "workflow_bound_device_count": len(bound_devices),
            "sla_risk_workflow_count": len(risk_workflows),
            "operator_focus_count": len(risk_workflows)
            + len([node for node in nodes if node.node_health != "healthy"])
            + len([device for device in devices if device.status != "healthy"]),
        }

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 3)
