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
    OperatorAssistantState,
    SummaryState,
    WorkflowEvent,
    WorkflowState,
)
from .normalizer import build_summary, normalize_node_state, normalize_workflow_state
from .placement_recorder import InfluxResourceProfileRecorder
from .prometheus import PrometheusClient
from .resource_profile import build_service_resource_profiles, summarize_service_resource_profiles
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
        self.resource_recorder = InfluxResourceProfileRecorder(
            settings.influxdb_url,
            settings.influxdb_org,
            settings.influxdb_bucket,
            settings.influxdb_token,
        )
        self._service_resource_profiles: list[dict[str, Any]] = []
        self._last_resource_recorded_at: datetime | None = None
        self._last_resource_record_result = "never_recorded"
        self.kube = KubeClient()
        self._poller_task: asyncio.Task | None = None
        self._device_status_bridge_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._poller_task is None:
            self._poller_task = asyncio.create_task(self._poll_prometheus())
        if self.settings.device_status_bridge_enabled and self._device_status_bridge_task is None:
            self._device_status_bridge_task = asyncio.create_task(self._bridge_device_status_heartbeats())

    async def stop(self) -> None:
        tasks = [task for task in (self._poller_task, self._device_status_bridge_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._poller_task = None
        self._device_status_bridge_task = None

    async def _poll_prometheus(self) -> None:
        while True:
            try:
                await self.refresh_nodes()
            except Exception:
                logger.exception("Failed to refresh Prometheus node metrics")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _bridge_device_status_heartbeats(self) -> None:
        while True:
            try:
                patched = await self.kube.bridge_device_status_heartbeats()
                if patched:
                    logger.info("bridged DeviceStatus heartbeats for %s device(s)", patched)
            except Exception:
                logger.exception("Failed to bridge DeviceStatus heartbeats")
            await asyncio.sleep(self.settings.device_status_bridge_interval_seconds)

    async def refresh_nodes(self) -> list[NodeState]:
        # Dynamically discover nodes from K8s API
        new_map = await self.kube.get_node_map()
        if new_map:
            self.prometheus.instance_map = new_map
            
        raw_nodes = await self.prometheus.collect_node_metrics()
        states = [normalize_node_state(item) for item in raw_nodes]
        for state in states:
            self.store.upsert_node_state(state)
        await self.refresh_service_resource_profiles()
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

    async def refresh_service_resource_profiles(self) -> list[dict[str, Any]]:
        pods = await self.kube.get_running_service_pods()
        usage_samples = await self.prometheus.collect_service_resource_usage()
        self._service_resource_profiles = build_service_resource_profiles(pods, usage_samples)
        if self.settings.resource_profile_recording_mode == "poll":
            recorded = await self.resource_recorder.record_snapshot(self._service_resource_profiles)
            self._last_resource_record_result = "recorded" if recorded else "failed"
            if recorded:
                self._last_resource_recorded_at = datetime.now(timezone.utc)
        return self._service_resource_profiles

    async def record_service_resource_profiles(self, window: str | None = None) -> dict[str, Any]:
        profile_window = window or self.settings.resource_profile_window
        pods = await self.kube.get_running_service_pods()
        usage_samples = await self.prometheus.collect_service_resource_profile_usage(window=profile_window)
        profiles = build_service_resource_profiles(pods, usage_samples, profile_window=profile_window)
        self._service_resource_profiles = profiles
        if self.settings.resource_profile_recording_mode == "disabled":
            self._last_resource_record_result = "disabled"
            recorded = False
        else:
            recorded = await self.resource_recorder.record_snapshot(profiles)
            self._last_resource_record_result = "recorded" if recorded else "failed"
            if recorded:
                self._last_resource_recorded_at = datetime.now(timezone.utc)
        return {
            "recorded": recorded,
            "recording_backend": "influxdb",
            "recording_mode": self.settings.resource_profile_recording_mode,
            "last_record_result": self._last_resource_record_result,
            "recorded_at": self._last_resource_recorded_at.isoformat() if self._last_resource_recorded_at else None,
            "profile_scope": "running_service_resource_requirements",
            "profile_window": profile_window,
            "summary": summarize_service_resource_profiles(profiles),
            "service_resource_profiles": profiles,
        }

    async def get_resource_profile_state(self, refresh: bool = False) -> dict[str, Any]:
        if refresh or not self._service_resource_profiles:
            await self.refresh_service_resource_profiles()
        summary = summarize_service_resource_profiles(self._service_resource_profiles)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "recorded_at": self._last_resource_recorded_at.isoformat() if self._last_resource_recorded_at else None,
            "recording_backend": "influxdb",
            "recording_mode": self.settings.resource_profile_recording_mode,
            "last_record_result": self._last_resource_record_result,
            "profile_scope": "running_service_resource_requirements",
            "summary": summary,
            "service_resource_profiles": self._service_resource_profiles,
        }

    async def get_device_telemetry_history(self, device_id: str, window: str = "-30m", limit: int = 300) -> list[TelemetrySample]:
        return await self.telemetry.get_history(device_id=device_id, window=window, limit=limit)

    async def get_devices(self) -> list[DeviceState]:
        raw_devices = await self.kube.get_devices()
        raw_statuses = await self.kube.get_device_statuses()
        status_by_device = {
            self._object_key(item): item.get("status", {})
            for item in raw_statuses
            if self._object_key(item)
        }
        node_health = {node.hostname: node.node_health for node in self.get_nodes()}
        node_readiness = await self.kube.get_node_readiness()
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
                node_readiness,
            )
            for item in raw_devices
        ]

    async def get_dashboard(self) -> DashboardState:
        nodes = self.get_nodes()
        devices = await self.get_devices()
        workflows = self.get_workflows()
        summary = build_summary(nodes, workflows)
        kpis = self._build_dashboard_kpis(nodes, devices, workflows)
        resource_state = await self.get_resource_profile_state()
        kpis.update(self._build_resource_profile_kpis(resource_state))
        return DashboardState(
            generated_at=datetime.now(timezone.utc),
            nodes=nodes,
            devices=devices,
            workflows=workflows,
            summary=summary,
            kpis=kpis,
            resource_profiles=resource_state,
        )

    async def get_operator_assistant(self) -> OperatorAssistantState:
        dashboard = await self.get_dashboard()
        kpis = dashboard.kpis
        registered = int(kpis.get("registered_device_count", len(dashboard.devices)) or 0)
        live = int(kpis.get("live_device_count", 0) or 0)
        focus_count = int(kpis.get("operator_focus_count", 0) or 0)
        service_bound = int(kpis.get("service_bound_device_count", 0) or 0)
        telemetry_configured_ratio = kpis.get("device_telemetry_ratio", 0)
        sensor_data_freshness_ratio = kpis.get("sensor_data_freshness_ratio", 0)

        focus_devices = [
            {
                "name": device.name,
                "node_name": device.node_name,
                "status": device.overall_status,
                "reason": device.reason,
                "service_demo_group": device.service_demo_group,
                "telemetry_fresh": device.telemetry_fresh,
                "device_status_fresh": device.device_status_fresh,
                "mapper_running": device.mapper_running,
                "node_ready": device.node_ready,
            }
            for device in dashboard.devices
            if device.overall_status in {"degraded", "unavailable"}
        ][:10]

        summary = (
            "Kagenti 연동 PoC용 read-only 운영 보조 요약입니다. "
            f"등록 device {registered}개 중 live device {live}개, "
            f"서비스 데모 연결 device {service_bound}개, 우선 점검 대상 {focus_count}개입니다. "
            f"telemetry configured 비율은 {telemetry_configured_ratio}이고, 실제 센서 데이터 freshness 비율은 {sensor_data_freshness_ratio}입니다."
        )

        return OperatorAssistantState(
            generated_at=datetime.now(timezone.utc),
            summary_ko=summary,
            focus_devices=focus_devices,
            recommended_actions=self._operator_recommended_actions(focus_devices),
            guardrails=[
                "read-only endpoint: Kubernetes 리소스, Device CR, command topic을 수정하지 않는다.",
                "운영자에게 점검 순서만 제안하고 rollout/delete/apply 같은 조치는 실행하지 않는다.",
                "workflow/offloading/agent-assisted planning 판단으로 해석하지 않는다.",
            ],
            source_endpoints=[
                "/state/dashboard",
                "/state/devices",
                "/state/nodes",
                "/state/summary",
            ],
        )

    def _operator_recommended_actions(self, focus_devices: list[dict[str, Any]]) -> list[str]:
        actions: list[str] = []
        for device in focus_devices:
            name = device.get("name", "unknown-device")
            if not device.get("node_ready", False):
                actions.append(f"{name}: 할당 node Ready 상태와 edgecore/cloudcore 연결을 먼저 확인한다.")
            if not device.get("mapper_running", False):
                actions.append(f"{name}: mqttvirtual mapper pod Running 여부와 node 배치를 확인한다.")
            if not device.get("telemetry_fresh", False):
                actions.append(f"{name}: sensor data freshness는 availability 판단과 별도 KPI다. EdgeX/collector/MQTT/DB 적재 경로를 별도 확인한다.")
            if device.get("telemetry_fresh") and not device.get("device_status_fresh", False):
                actions.append(f"{name}: DeviceStatus snapshot 대상 property와 mapper allowlist 정책을 확인한다.")
        if not actions:
            actions.append("현재 우선 점검 대상이 없으므로 dashboard KPI와 service demo group만 확인한다.")
        return actions[:10]

    def _normalize_device(
        self,
        item: dict[str, Any],
        node_health: dict[str, str],
        workflows: list[WorkflowState],
        mapper_nodes: set[str] | None = None,
        telemetry_samples: dict[str, TelemetrySample] | None = None,
        node_readiness: dict[str, bool] | None = None,
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
        telemetry_enabled = self._is_telemetry_enabled(properties)
        service_demo_group, service_binding_source, service_binding_reason = self._device_service_binding_detail(
            name,
            node_name,
            workflows,
        )
        service_connected = service_demo_group is not None
        device_type = self._classify_device(name, model, protocol)
        telemetry_sample = (telemetry_samples or {}).get(name)
        telemetry_age_seconds = self._telemetry_age_seconds(telemetry_sample)
        telemetry_fresh = (
            telemetry_age_seconds is not None
            and telemetry_age_seconds <= self.settings.telemetry_fresh_seconds
        )
        telemetry_status = self._telemetry_status(telemetry_enabled, telemetry_fresh)
        device_status_last_reported_at = self._device_status_last_reported_at(status_payload)
        device_status_age_seconds = self._age_seconds(device_status_last_reported_at)
        device_status_fresh = (
            device_status_age_seconds is not None
            and device_status_age_seconds <= self.settings.device_status_fresh_seconds
        )
        status_heartbeat_last_seen_at = self._status_heartbeat_last_seen_at(twin, status_payload)
        status_heartbeat_age_seconds = self._age_seconds(status_heartbeat_last_seen_at)
        if status_heartbeat_age_seconds is not None:
            device_status_fresh = status_heartbeat_age_seconds <= self.settings.device_status_fresh_seconds
        mapper_running = protocol != "mqttvirtual" or bool(node_name and node_name in (mapper_nodes or set()))
        node_ready = self._node_ready(node_name, node_health, node_readiness or {})
        kubeedge_state = self._read_status_field(status_payload, ("state", "status", "phase", "connection", "connected"))
        health_value = self._reported_twin_value(twin, "health") or self._read_status_field(status_payload, ("health",))
        online_value = self._reported_twin_value(twin, "online") or self._read_status_field(status_payload, ("online", "connected"))
        severity_value = self._reported_twin_value(twin, "severity")
        health, reason = self._device_health(
            status_payload,
            node_name,
            node_health,
            telemetry_enabled,
            protocol,
            mapper_nodes or set(),
            telemetry_age_seconds,
            device_status_fresh,
            telemetry_fresh,
            mapper_running,
            node_ready,
            health_value,
            online_value,
            severity_value,
            status_heartbeat_age_seconds,
        )
        return DeviceState(
            name=name,
            namespace=namespace,
            device_type=device_type,
            model=model,
            node_name=node_name,
            nodeName=node_name,
            protocol=protocol,
            properties=property_names,
            telemetry_enabled=telemetry_enabled,
            service_connected=service_connected,
            service_demo_group=service_demo_group,
            service_binding_source=service_binding_source,
            service_binding_reason=service_binding_reason,
            status=health,
            status_reason=reason,
            kubeedge_state=kubeedge_state,
            device_status_fresh=device_status_fresh,
            device_status_last_reported_at=device_status_last_reported_at,
            telemetry_fresh=telemetry_fresh,
            telemetry_status=telemetry_status,
            telemetry_last_seen_at=telemetry_sample.timestamp if telemetry_sample else None,
            mapper_running=mapper_running,
            node_ready=node_ready,
            health=health_value,
            severity=severity_value,
            overall_status=health,
            reason=reason,
            telemetry_last_seen=telemetry_sample.timestamp if telemetry_sample else None,
            telemetry_age_seconds=telemetry_age_seconds,
            telemetry_property=telemetry_sample.property if telemetry_sample else None,
            telemetry_value=telemetry_sample.value if telemetry_sample else None,
            twin=twin,
        )

    def _telemetry_status(self, telemetry_enabled: bool, telemetry_fresh: bool) -> str:
        if not telemetry_enabled:
            return "disabled"
        return "fresh" if telemetry_fresh else "stale"

    def _node_ready(
        self,
        node_name: str | None,
        node_health: dict[str, str],
        node_readiness: dict[str, bool],
    ) -> bool:
        if not node_name:
            return False
        if node_readiness.get(node_name) is False:
            return False
        if node_readiness and node_name not in node_readiness:
            return False
        return node_health.get(node_name) != "unavailable"

    def _is_telemetry_enabled(self, properties: list[Any]) -> bool:
        for prop in properties:
            if not isinstance(prop, dict):
                continue
            if prop.get("pushMethod"):
                return True
        return False

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

    def _device_service_binding_detail(
        self,
        device_name: str,
        node_name: str | None,
        workflows: list[WorkflowState],
    ) -> tuple[str | None, str | None, str | None]:
        name = device_name.lower()
        if "vib" in name:
            return (
                "설비 상태 모니터링",
                "device_name_pattern",
                "device name includes vibration service keyword",
            )
        if "act" in name:
            return (
                "command 상태 확인",
                "device_name_pattern",
                "device name includes actuator command service keyword",
            )
        if "env" in name or "temp" in name:
            return (
                "환경 상태 모니터링",
                "device_name_pattern",
                "device name includes environment service keyword",
            )
        if self._device_has_event_binding(device_name, node_name, workflows):
            return (
                "서비스 데모 연결",
                "event_binding",
                "recent service event references this device or node",
            )
        return None, None, None

    def _device_has_event_binding(
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
        device_status_fresh: bool = False,
        telemetry_fresh: bool = False,
        mapper_running: bool = False,
        node_ready: bool = False,
        health_value: str | None = None,
        online_value: str | None = None,
        severity_value: str | None = None,
        status_heartbeat_age_seconds: float | None = None,
    ) -> tuple[str, str]:
        mapper_nodes = mapper_nodes or set()
        if not node_name:
            return "unavailable", "device is not assigned to a node"
        if not node_ready:
            return "unavailable", "assigned node is unavailable"
        live_state = self._read_live_device_state(status_payload)
        if live_state in {"offline", "disconnected", "failed", "unavailable", "false"}:
            return "unavailable", f"device status is {live_state}"
        if health_value and health_value.lower() == "offline":
            return "unavailable", "DeviceStatus health is offline"
        if online_value and online_value.lower() in {"false", "offline", "disconnected", "unavailable"}:
            return "unavailable", "DeviceStatus online is false"
        if protocol == "mqttvirtual" and not mapper_running:
            return "unavailable", "assigned mapper is not running"
        if telemetry_enabled and not telemetry_fresh:
            if telemetry_age_seconds is None:
                return "degraded", "latest telemetry sample is missing"
            return "degraded", "latest telemetry sample is stale"
        if (
            status_heartbeat_age_seconds is not None
            and status_heartbeat_age_seconds > self.settings.device_status_fresh_seconds
        ):
            return "degraded", "status heartbeat is stale"
        if node_health.get(node_name) == "degraded":
            return "degraded", "assigned node is degraded"
        if severity_value and severity_value.lower() == "critical":
            return "degraded", "DeviceStatus severity is critical"
        if health_value and health_value.lower() in {"error", "failed", "degraded", "critical"}:
            return "degraded", f"DeviceStatus health is {health_value.lower()}"
        if telemetry_enabled:
            return "available", "latest telemetry sample is fresh"
        if device_status_fresh:
            return "available", "control/status path is available"
        return "available", "registered control/status path is available"

    def _read_live_device_state(self, status_payload: dict[str, Any]) -> str | None:
        for key in ("status", "phase", "state", "connection", "connected", "health"):
            value = status_payload.get(key)
            if value is None:
                continue
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value).lower()
        return None

    def _read_status_field(self, status_payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
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

    def _device_status_last_reported_at(self, status_payload: dict[str, Any]) -> datetime | None:
        candidates: list[datetime] = []
        last_seen = self._parse_kube_time(status_payload.get("lastOnlineTime"))
        if last_seen is not None:
            candidates.append(last_seen)
        candidates.extend(
            self._reported_twin_timestamps(status_payload.get("twins") or status_payload.get("twin") or {})
        )
        if not candidates:
            return None
        return max(candidates)

    def _status_heartbeat_last_seen_at(self, twin: Any, status_payload: dict[str, Any]) -> datetime | None:
        candidates: list[datetime] = []
        for key in ("statusLastSeen", "controlLastSeen", "mapperLastSeen"):
            direct = self._parse_kube_time(status_payload.get(key))
            if direct is not None:
                candidates.append(direct)
            twin_time = self._reported_twin_timestamp_or_value(twin, key)
            if twin_time is not None:
                candidates.append(twin_time)
        if not candidates:
            return None
        return max(candidates)

    def _reported_twin_timestamp_or_value(self, twin: Any, property_name: str) -> datetime | None:
        if isinstance(twin, list):
            for item in twin:
                if not isinstance(item, dict) or item.get("propertyName") != property_name:
                    continue
                parsed = self._parse_reported_timestamp_or_value(item.get("reported"))
                if parsed is not None:
                    return parsed
            return None
        if not isinstance(twin, dict):
            return None
        value = twin.get(property_name)
        if not isinstance(value, dict):
            return None
        return self._parse_reported_timestamp_or_value(value.get("actual") or value.get("reported"))

    def _parse_reported_timestamp_or_value(self, reported: Any) -> datetime | None:
        if isinstance(reported, dict):
            parsed = self._parse_kube_time(reported.get("value"))
            if parsed is not None:
                return parsed
            return self._parse_kube_time((reported.get("metadata") or {}).get("timestamp"))
        return self._parse_kube_time(reported)

    def _age_seconds(self, timestamp: datetime | None) -> float | None:
        if timestamp is None:
            return None
        age = datetime.now(timezone.utc) - timestamp
        return max(0.0, round(age.total_seconds(), 3))

    def _reported_twin_value(self, twin: Any, property_name: str) -> str | None:
        if isinstance(twin, list):
            for item in twin:
                if not isinstance(item, dict) or item.get("propertyName") != property_name:
                    continue
                reported = item.get("reported")
                if isinstance(reported, dict) and reported.get("value") not in (None, ""):
                    return str(reported.get("value")).lower()
            return None
        if not isinstance(twin, dict):
            return None
        value = twin.get(property_name)
        if not isinstance(value, dict):
            return None
        reported = value.get("reported") or value.get("actual")
        if isinstance(reported, dict) and reported.get("value") not in (None, ""):
            return str(reported.get("value")).lower()
        if reported not in (None, "") and not isinstance(reported, dict):
            return str(reported).lower()
        return None

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
        healthy_devices = [device for device in devices if device.status in {"available", "healthy"}]
        operational_devices = [device for device in devices if device.status != "unavailable"]
        telemetry_devices = [device for device in devices if device.telemetry_enabled]
        fresh_telemetry_devices = [
            device for device in telemetry_devices if device.telemetry_fresh
        ]
        sensor_data_devices = telemetry_devices
        fresh_sensor_data_devices = fresh_telemetry_devices
        fresh_device_status_devices = [device for device in devices if device.device_status_fresh]
        bound_devices = [device for device in devices if device.service_connected]
        risk_workflows = [workflow for workflow in workflows if workflow.sla_risk != "low"]
        unavailable_devices = [device for device in devices if device.status == "unavailable"]
        # operator focus excludes workflow risk: only degraded/unavailable devices and non-healthy nodes.
        focus_devices = [device for device in devices if device.status in {"degraded", "unavailable"}]
        focus_nodes = [node for node in nodes if node.node_health != "healthy"]
        return {
            "node_online_ratio": self._ratio(len(online_nodes), len(nodes)),
            "device_healthy_ratio": self._ratio(len(healthy_devices), len(devices)),
            "device_operational_ratio": self._ratio(len(operational_devices), len(devices)),
            # device_telemetry_ratio is the configured telemetry target ratio (telemetry-enabled devices / total devices)
            "device_telemetry_ratio": self._ratio(len(telemetry_devices), len(devices)),
            # fresh telemetry counts and freshness ratio (fresh telemetry / telemetry-enabled devices)
            "fresh_telemetry_device_count": len(fresh_telemetry_devices),
            "telemetry_freshness_ratio": self._ratio(len(fresh_telemetry_devices), len(telemetry_devices)),
            # sensor data freshness is the primary operations KPI for the current Jetson Arduino data-plane.
            "sensor_data_device_count": len(sensor_data_devices),
            "fresh_sensor_data_device_count": len(fresh_sensor_data_devices),
            "sensor_data_freshness_ratio": self._ratio(len(fresh_sensor_data_devices), len(sensor_data_devices)),
            "device_service_binding_ratio": self._ratio(len(bound_devices), len(devices)),
            "registered_device_count": len(devices),
            "active_node_count": len(online_nodes),
            "operational_device_count": len(operational_devices),
            "live_device_count": len(healthy_devices),
            "telemetry_device_count": len(telemetry_devices),
            "service_bound_device_count": len(bound_devices),
            "sla_risk_workflow_count": len(risk_workflows),
            "unavailable_device_count": len(unavailable_devices),
            # operator focus count: number of degraded/unavailable devices plus non-healthy nodes
            "fresh_device_status_count": len(fresh_device_status_devices),
            "device_status_freshness_ratio": self._ratio(len(fresh_device_status_devices), len(devices)),
            "operator_focus_count": len(focus_devices) + len(focus_nodes),
        }

    def _build_resource_profile_kpis(self, resource_state: dict[str, Any]) -> dict[str, Any]:
        summary = resource_state.get("summary") or {}
        return {
            "service_resource_profile_count": summary.get("profile_count", 0),
            "service_resource_profile_pod_count": summary.get("running_pod_count", 0),
            "service_resource_profile_container_count": summary.get("container_count", 0),
            "service_resource_request_cpu_cores": summary.get("declared_request_cpu_cores", 0),
            "service_resource_request_memory_mib": summary.get("declared_request_memory_mib", 0),
            "service_resource_current_cpu_usage_cores": summary.get("current_cpu_usage_cores", 0),
            "service_resource_current_memory_working_set_mib": summary.get("current_memory_working_set_mib", 0),
            "service_resource_usage_coverage_ratio": summary.get("usage_coverage_ratio", 0),
            "service_resource_limit_gpu_units": summary.get("declared_limit_gpu_units", 0),
            "service_resource_fully_declared_profile_count": summary.get("fully_declared_profile_count", 0),
            "service_resource_partially_declared_profile_count": summary.get("partially_declared_profile_count", 0),
            "service_resource_profile_recorded": resource_state.get("recorded_at") is not None,
        }

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 3)
