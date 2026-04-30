from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .config import Settings, load_instance_map
from .influx import InfluxTelemetryClient, TelemetrySample
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
        self.telemetry = InfluxTelemetryClient(
            settings.influxdb_url,
            settings.influxdb_org,
            settings.influxdb_bucket,
            settings.influxdb_token,
            settings.influxdb_measurement,
            settings.telemetry_query_window,
        )
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
        raw_statuses = await self.kube.get_device_statuses()
        status_by_device = {
            self._object_key(item): item.get("status", {})
            for item in raw_statuses
            if self._object_key(item)
        }
        node_health = {node.hostname: node.node_health for node in self.get_nodes()}
        mapper_nodes = await self.kube.get_running_mapper_nodes()
        telemetry_samples = await self.telemetry.get_latest_by_device()
        workflows = self.get_workflows()
        return [
            self._normalize_device(
                self._merge_device_status(item, status_by_device),
                node_health,
                workflows,
                mapper_nodes,
                telemetry_samples,
            )
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
        telemetry_samples: dict[str, TelemetrySample] | None = None,
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
        twin = self._normalize_twin_payload(status_payload.get("twins") or status_payload.get("twin") or {})
        telemetry_enabled = any(
            isinstance(prop, dict)
            and (bool(prop.get("reportToCloud")) or bool(prop.get("pushMethod")))
            for prop in properties
        )
        service_connected = self._device_has_service_binding(name, node_name, workflows)
        device_type = self._classify_device(name, model, protocol)
        telemetry_sample = (telemetry_samples or {}).get(name)
        telemetry_age_seconds = self._telemetry_age_seconds(telemetry_sample)
        device_status_age_seconds = self._device_status_age_seconds(status_payload)
        health, reason = self._device_health(
            status_payload,
            node_name,
            node_health,
            telemetry_enabled,
            protocol,
            mapper_nodes or set(),
            telemetry_age_seconds,
            device_status_age_seconds,
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
            telemetry_last_seen=telemetry_sample.timestamp if telemetry_sample else None,
            telemetry_age_seconds=telemetry_age_seconds,
            telemetry_property=telemetry_sample.property if telemetry_sample else None,
            telemetry_value=telemetry_sample.value if telemetry_sample else None,
            twin=twin,
        )

    def _object_key(self, item: dict[str, Any]) -> tuple[str, str] | None:
        metadata = item.get("metadata") or {}
        name = metadata.get("name")
        namespace = metadata.get("namespace", "default")
        if not name:
            return None
        return namespace, name

    def _merge_device_status(
        self,
        device: dict[str, Any],
        status_by_device: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        key = self._object_key(device)
        live_status = status_by_device.get(key) if key else None
        if not live_status:
            return device
        merged = dict(device)
        merged["status"] = live_status
        return merged

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
        telemetry_age_seconds: float | None = None,
        device_status_age_seconds: float | None = None,
    ) -> tuple[str, str]:
        mapper_nodes = mapper_nodes or set()
        if node_name and node_health.get(node_name) == "unavailable":
            return "unavailable", "assigned node is unavailable"
        if device_status_age_seconds is not None and device_status_age_seconds > self.settings.telemetry_fresh_seconds:
            return "degraded", f"device status stale: last received {int(device_status_age_seconds)}s ago"
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
        if telemetry_age_seconds is not None:
            if telemetry_age_seconds <= self.settings.telemetry_fresh_seconds:
                return "healthy", f"telemetry received {int(telemetry_age_seconds)}s ago"
            return "degraded", f"telemetry stale: last received {int(telemetry_age_seconds)}s ago"
        if not node_name:
            return "unavailable", "device is not assigned to a node"
        if protocol == "mqttvirtual" and node_name not in mapper_nodes:
            return "unavailable", "assigned mapper is not running"
        if node_health.get(node_name) == "healthy" and telemetry_enabled and protocol == "mqttvirtual":
            return "degraded", "mapper is running but telemetry has not reached InfluxDB"
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
        if isinstance(twin, list):
            for item in twin:
                if not isinstance(item, dict):
                    continue
                reported = item.get("reported")
                if isinstance(reported, dict) and reported.get("value") not in (None, ""):
                    return True
            return False
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

    def _normalize_twin_payload(self, twin: Any) -> dict[str, Any]:
        if isinstance(twin, dict):
            return twin
        if not isinstance(twin, list):
            return {}
        normalized: dict[str, Any] = {}
        for item in twin:
            if not isinstance(item, dict):
                continue
            name = item.get("propertyName")
            if name:
                normalized[name] = {
                    "reported": item.get("reported"),
                    "observedDesired": item.get("observedDesired"),
                }
        return normalized

    def _telemetry_age_seconds(self, sample: TelemetrySample | None) -> float | None:
        if sample is None:
            return None
        age = datetime.now(timezone.utc) - sample.timestamp
        return max(0.0, round(age.total_seconds(), 3))

    def _device_status_age_seconds(self, status_payload: dict[str, Any]) -> float | None:
        candidates: list[datetime] = []
        last_seen = self._parse_kube_time(status_payload.get("lastOnlineTime"))
        if last_seen is not None:
            candidates.append(last_seen)
        candidates.extend(
            self._reported_twin_timestamps(status_payload.get("twins") or status_payload.get("twin") or {})
        )
        if not candidates:
            return None
        age = datetime.now(timezone.utc) - max(candidates)
        return max(0.0, round(age.total_seconds(), 3))

    def _reported_twin_timestamps(self, twin: Any) -> list[datetime]:
        timestamps: list[datetime] = []
        if isinstance(twin, list):
            for item in twin:
                if not isinstance(item, dict):
                    continue
                reported = item.get("reported")
                if isinstance(reported, dict):
                    parsed = self._parse_kube_time((reported.get("metadata") or {}).get("timestamp"))
                    if parsed is not None:
                        timestamps.append(parsed)
            return timestamps
        if not isinstance(twin, dict):
            return timestamps
        for value in twin.values():
            if not isinstance(value, dict):
                continue
            actual = value.get("actual") or value.get("reported")
            if isinstance(actual, dict):
                parsed = self._parse_kube_time((actual.get("metadata") or {}).get("timestamp"))
                if parsed is not None:
                    timestamps.append(parsed)
        return timestamps

    def _parse_kube_time(self, value: Any) -> datetime | None:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp = timestamp / 1000
            try:
                return datetime.fromtimestamp(timestamp, timezone.utc)
            except (OSError, OverflowError, ValueError):
                logger.warning("Failed to parse Kubernetes numeric timestamp: %s", value)
                return None
        if not isinstance(value, str) or not value:
            return None
        if value.isdigit():
            return self._parse_kube_time(int(value))
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            logger.warning("Failed to parse Kubernetes timestamp: %s", value)
            return None

    def _build_dashboard_kpis(
        self,
        nodes: list[NodeState],
        devices: list[DeviceState],
        workflows: list[WorkflowState],
    ) -> dict[str, Any]:
        online_nodes = [node for node in nodes if node.node_health != "unavailable"]
        healthy_devices = [device for device in devices if device.status == "healthy"]
        operational_devices = [device for device in devices if device.status != "unavailable"]
        telemetry_devices = [device for device in devices if device.telemetry_enabled]
        bound_devices = [device for device in devices if device.service_connected]
        risk_workflows = [workflow for workflow in workflows if workflow.sla_risk != "low"]
        unavailable_devices = [device for device in devices if device.status == "unavailable"]
        return {
            "node_online_ratio": self._ratio(len(online_nodes), len(nodes)),
            "device_healthy_ratio": self._ratio(len(healthy_devices), len(devices)),
            "device_operational_ratio": self._ratio(len(operational_devices), len(devices)),
            "device_telemetry_ratio": self._ratio(len(telemetry_devices), len(devices)),
            "device_workflow_binding_ratio": self._ratio(len(bound_devices), len(devices)),
            "registered_device_count": len(devices),
            "active_node_count": len(online_nodes),
            "operational_device_count": len(operational_devices),
            "live_device_count": len(healthy_devices),
            "telemetry_device_count": len(telemetry_devices),
            "workflow_bound_device_count": len(bound_devices),
            "sla_risk_workflow_count": len(risk_workflows),
            "unavailable_device_count": len(unavailable_devices),
            "operator_focus_count": len(risk_workflows)
            + len([node for node in nodes if node.node_health != "healthy"])
            + len(unavailable_devices),
        }

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 3)
