from __future__ import annotations

import asyncio
import logging
import re

import httpx
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings, load_instance_map
from .edgex import EdgeXClient
from .models import (
    CostModelState,
    DashboardState,
    DeviceState,
    EdgeXDevice,
    NodeState,
    OperatorAssistantState,
    OperatorChatRequest,
    OperatorChatResponse,
    SummaryState,
    TelemetryPoint,
    WorkflowEvent,
    WorkflowState,
)
from .normalizer import build_summary, normalize_node_state, normalize_workflow_state
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
        self.edgex = EdgeXClient(
            settings.edgex_core_metadata_url,
            settings.edgex_core_data_url,
            settings.edgex_timeout_seconds,
        )
        self._service_resource_profiles: list[dict[str, Any]] = []
        self.kube = KubeClient()
        self._poller_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._poller_task is None:
            self._poller_task = asyncio.create_task(self._poll_prometheus())

    async def stop(self) -> None:
        tasks = [task for task in (self._poller_task,) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
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
        current_node_names = {mapping["hostname"] for mapping in new_map.values() if mapping.get("hostname")}
        if new_map:
            self.prometheus.instance_map = new_map

        raw_nodes = await self.prometheus.collect_node_metrics()
        states = [normalize_node_state(item) for item in raw_nodes]
        if current_node_names:
            states = [state for state in states if state.hostname in current_node_names]
        self.store.replace_node_states(states)
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
        return self._service_resource_profiles

    async def get_resource_profile_state(self, refresh: bool = False) -> dict[str, Any]:
        if refresh or not self._service_resource_profiles:
            await self.refresh_service_resource_profiles()
        summary = summarize_service_resource_profiles(self._service_resource_profiles)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile_scope": "running_service_resource_requirements",
            "summary": summary,
            "service_resource_profiles": self._service_resource_profiles,
        }

    async def get_device_telemetry_history(
        self, device_id: str, window: str = "-30m", limit: int = 300
    ) -> list[TelemetryPoint]:
        match = re.fullmatch(r"-([1-9][0-9]*)([smhdw])", window)
        if match is None:
            raise ValueError("window must be a negative duration such as -30m")
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        start = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return await self.edgex.get_event_history(device_id, limit=limit, start=start)

    async def get_devices(self) -> list[DeviceState]:
        inventory = await self.edgex.get_devices()
        latest_events = await asyncio.gather(
            *(self.edgex.get_latest_source_readings(device.name) for device in inventory)
        )
        return [
            self._normalize_edgex_device(device, readings)
            for device, readings in zip(inventory, latest_events)
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
        focus_devices = []
        for device in dashboard.devices:
            status, reason = self._device_health(device)
            if status in {"degraded", "unavailable"}:
                focus_devices.append(
                    {
                        "name": device.name,
                        "node_name": device.node_name,
                        "status": status,
                        "reason": reason,
                        "admin_state": device.admin_state,
                        "operating_state": device.operating_state,
                        "device_service_available": device.device_service_available,
                        "telemetry_freshness": device.telemetry_freshness,
                    }
                )
        kpis = dashboard.kpis
        summary = (
            "EdgeX 기반 read-only 운영 보조 요약입니다. "
            f"Core Metadata 등록 device {len(dashboard.devices)}개 중 "
            f"available device {kpis.get('available_device_count', 0)}개, "
            f"우선 점검 대상 {kpis.get('operator_focus_count', 0)}개입니다. "
            f"Core Data event freshness 비율은 {kpis.get('core_data_freshness_ratio', 0)}입니다."
        )
        return OperatorAssistantState(
            generated_at=datetime.now(timezone.utc),
            summary_ko=summary,
            focus_devices=focus_devices[:10],
            recommended_actions=self._operator_recommended_actions(focus_devices),
            guardrails=[
                "read-only endpoint: EdgeX 및 Kubernetes 리소스를 수정하지 않는다.",
                "운영자에게 점검 순서만 제안하고 명령 또는 제어를 실행하지 않는다.",
                "Kubernetes node_name은 진단 정보이며 물리 device availability 판단에 사용하지 않는다.",
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
            if str(device.get("admin_state", "")).upper() == "LOCKED":
                actions.append(f"{name}: Core Metadata adminState 잠금 정책을 확인한다.")
            if not device.get("device_service_available", False):
                actions.append(f"{name}: EdgeX device service와 operatingState를 확인한다.")
            if device.get("telemetry_freshness") != "fresh":
                actions.append(f"{name}: Core Data 최신 event와 device service 수집 경로를 확인한다.")
        return actions[:10] or ["현재 우선 점검 대상이 없으므로 EdgeX KPI를 확인한다."]

    async def chat_with_operator_assistant(self, request: OperatorChatRequest) -> OperatorChatResponse:
        assistant = await self.get_operator_assistant()
        system_prompt = self._operator_chat_system_prompt(assistant)
        payload = {
            "model": self.settings.qwen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        endpoint = f"{self.settings.qwen_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.settings.qwen_timeout_seconds) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Qwen operator chat request failed: %s", exc)
            return OperatorChatResponse(
                model=self.settings.qwen_model,
                answer="로컬 Qwen 모델에 연결하지 못했습니다. 모델 서버(192.168.0.5:8080) 상태를 확인해 주세요.",
                source_endpoints=assistant.source_endpoints,
                guardrails=assistant.guardrails,
                upstream_status="unavailable",
            )

        answer = self._extract_chat_answer(data)
        return OperatorChatResponse(
            model=self.settings.qwen_model,
            answer=answer or "Qwen 응답이 비어 있습니다. 모델 서버 로그를 확인해 주세요.",
            source_endpoints=assistant.source_endpoints,
            guardrails=assistant.guardrails,
        )

    def _operator_chat_system_prompt(self, assistant: OperatorAssistantState) -> str:
        focus_lines = [
            f"- {item.get('name')}: {item.get('status')} / {item.get('reason')} / node={item.get('node_name')}"
            for item in assistant.focus_devices[:6]
        ]
        actions = "\n".join(f"- {action}" for action in assistant.recommended_actions[:6])
        focus = "\n".join(focus_lines) if focus_lines else "- 현재 우선 점검 device 없음"
        return (
            "You are a read-only Korean operator assistant for an EdgeX physical-device and Kubernetes workload dashboard. "
            "Answer in Korean unless the user asks otherwise. Do not claim you can execute commands. "
            "Return only the concise operator-facing final answer. Never expose chain-of-thought, hidden reasoning, "
            "drafting notes, self-critique, or a 'thinking process'. "
            "Do not suggest Kubernetes apply/delete/rollout, MQTT command publishing, actuator control, dynamic offloading, "
            "or agent-assisted planning as actions. Only explain current dashboard signals and safe inspection order.\n\n"
            f"Dashboard summary: {assistant.summary_ko}\n"
            f"Focus devices:\n{focus}\n"
            f"Recommended safe checks:\n{actions}\n"
            f"Guardrails: {'; '.join(assistant.guardrails)}"
        )

    def _extract_chat_answer(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                content = self._sanitize_operator_chat_answer(content)
                if content:
                    return content
        text = first.get("text")
        return self._sanitize_operator_chat_answer(text) if isinstance(text, str) else ""

    def _sanitize_operator_chat_answer(self, answer: str) -> str:
        sanitized = re.sub(
            r"<think\b[^>]*>.*?</think>",
            "",
            answer,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        if not sanitized:
            return ""

        final_match = re.search(
            r"(?:^|\n)\s*(?:\d+[.)]\s*)?(?:\*\*)?(?:final answer|final response|최종 답변)\s*:?(?:\*\*)?\s*:?\s*",
            sanitized,
            flags=re.IGNORECASE,
        )
        draft_match = re.search(
            r"(?:^|\n)\s*(?:\d+[.)]\s*)?(?:\*\*)?draft\s*:?(?:\*\*)?\s*:?\s*",
            sanitized,
            flags=re.IGNORECASE,
        )
        answer_match = final_match or draft_match
        if answer_match:
            sanitized = sanitized[answer_match.end():]
            next_section = re.search(
                r"\n\s*\d+[.)]\s*(?:\*\*)?(?:check|critique|analysis|reasoning|검토|점검)(?:\*\*)?",
                sanitized,
                flags=re.IGNORECASE,
            )
            if next_section:
                sanitized = sanitized[:next_section.start()]
            return sanitized.strip()

        if re.match(
            r"^\s*(?:here(?:'s| is)\s+)?(?:a\s+)?(?:thinking process|analysis|reasoning|chain[- ]of[- ]thought)\b",
            sanitized,
            flags=re.IGNORECASE,
        ):
            return ""
        return sanitized

    def _normalize_edgex_device(
        self, device: EdgeXDevice, readings: list[TelemetryPoint]
    ) -> DeviceState:
        latest_timestamp = max(
            (reading.timestamp for reading in readings), default=None
        )
        age_seconds = (
            max(0.0, (datetime.now(timezone.utc) - latest_timestamp).total_seconds())
            if latest_timestamp is not None
            else None
        )
        freshness = (
            "no_events"
            if age_seconds is None
            else "fresh"
            if age_seconds <= self.settings.edgex_event_fresh_seconds
            else "stale"
        )
        operating_state = device.operating_state.upper()
        admin_state = device.admin_state.upper()
        connection_state = (
            "disconnected"
            if admin_state == "LOCKED" or operating_state == "DOWN"
            else "connected"
            if operating_state == "UP"
            else "unknown"
        )
        state = DeviceState(
            name=device.name,
            profile_name=device.profile_name,
            device_service_name=device.device_service_name,
            protocol_names=device.protocol_names,
            admin_state=device.admin_state,
            operating_state=device.operating_state,
            connection_state=connection_state,
            device_service_available=operating_state == "UP",
            latest_event_timestamp=latest_timestamp,
            latest_readings=readings,
            telemetry_freshness=freshness,
            node_name=device.node_name,
            physical_device_id=self._identity_tag(
                device.tags, "physicalDeviceId"
            ),
            hardware_binding_id=self._identity_tag(
                device.tags, "hardwareBindingId"
            ),
            controller_candidate_id=self._identity_tag(
                device.tags, "controllerCandidateId"
            ),
        )
        overall_status, reason = self._device_health(state)
        return state.model_copy(
            update={"overall_status": overall_status, "reason": reason}
        )

    @staticmethod
    def _identity_tag(tags: dict[str, Any], name: str) -> str | None:
        value = tags.get(name)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _device_health(self, device: DeviceState) -> tuple[str, str]:
        if device.admin_state.upper() == "LOCKED":
            return "unavailable", "EdgeX adminState is LOCKED"
        operating_state = device.operating_state.upper()
        if operating_state == "DOWN":
            return "unavailable", "EdgeX operatingState is DOWN"
        if operating_state != "UP":
            return "degraded", f"EdgeX operatingState is {operating_state or 'UNKNOWN'}"
        if device.telemetry_freshness == "fresh":
            return "available", "EdgeX device service is UP and latest Core Data event is fresh"
        if device.telemetry_freshness == "stale":
            return "degraded", "EdgeX device service is UP but latest Core Data event is stale"
        return "degraded", "EdgeX device service is UP but no Core Data event is available"

    def _build_dashboard_kpis(
        self,
        nodes: list[NodeState],
        devices: list[DeviceState],
        workflows: list[WorkflowState],
    ) -> dict[str, Any]:
        online_nodes = [node for node in nodes if node.node_health != "unavailable"]
        health = [(device, *self._device_health(device)) for device in devices]
        available_devices = [device for device, status, _ in health if status == "available"]
        degraded_devices = [device for device, status, _ in health if status == "degraded"]
        unavailable_devices = [device for device, status, _ in health if status == "unavailable"]
        connected_devices = [
            device for device in devices if device.connection_state == "connected"
        ]
        service_available_devices = [
            device for device in devices if device.device_service_available
        ]
        event_devices = [
            device for device in devices if device.telemetry_freshness != "no_events"
        ]
        fresh_event_devices = [
            device for device in devices if device.telemetry_freshness == "fresh"
        ]
        stale_event_devices = [
            device for device in devices if device.telemetry_freshness == "stale"
        ]
        risk_workflows = [workflow for workflow in workflows if workflow.sla_risk != "low"]
        return {
            "node_online_ratio": self._ratio(len(online_nodes), len(nodes)),
            "registered_device_count": len(devices),
            "available_device_count": len(available_devices),
            "degraded_device_count": len(degraded_devices),
            "unavailable_device_count": len(unavailable_devices),
            "edgex_connected_device_count": len(connected_devices),
            "edgex_connection_ratio": self._ratio(len(connected_devices), len(devices)),
            "edgex_operating_up_count": sum(
                device.operating_state.upper() == "UP" for device in devices
            ),
            "edgex_operating_down_count": sum(
                device.operating_state.upper() == "DOWN" for device in devices
            ),
            "edgex_operating_unknown_count": sum(
                device.operating_state.upper() not in {"UP", "DOWN"} for device in devices
            ),
            "edgex_admin_unlocked_count": sum(
                device.admin_state.upper() == "UNLOCKED" for device in devices
            ),
            "edgex_admin_locked_count": sum(
                device.admin_state.upper() == "LOCKED" for device in devices
            ),
            "device_service_available_count": len(service_available_devices),
            "device_service_availability_ratio": self._ratio(
                len(service_available_devices), len(devices)
            ),
            "core_data_event_device_count": len(event_devices),
            "fresh_core_data_event_device_count": len(fresh_event_devices),
            "stale_core_data_event_device_count": len(stale_event_devices),
            "core_data_freshness_ratio": self._ratio(
                len(fresh_event_devices), len(devices)
            ),
            "active_node_count": len(online_nodes),
            "sla_risk_workflow_count": len(risk_workflows),
            "operator_focus_count": len(degraded_devices) + len(unavailable_devices),
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
