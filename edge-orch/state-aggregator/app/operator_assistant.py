from __future__ import annotations

from datetime import datetime, timezone

from .models import DashboardState, DeviceState, OperatorAssistantState, OperatorChatResponse
from .virtual_resources import JsonMap

SOURCE_ENDPOINTS = ["/state/dashboard", "/state/devices", "/state/nodes", "/state/summary", "/state/virtual-resources"]
GUARDRAILS = [
    "read-only endpoint: EdgeX 및 Kubernetes 리소스를 수정하지 않는다.",
    "운영자에게 점검 순서만 제안하고 명령 또는 제어를 실행하지 않는다.",
    "Kubernetes node_name은 진단 정보이며 물리 device availability 판단에 사용하지 않는다.",
]


def operator_assistant_from_dashboard(dashboard: DashboardState) -> OperatorAssistantState:
    kpis = dashboard.kpis
    registered = int(kpis.get("registered_device_count", len(dashboard.devices)) or 0)
    available = int(kpis.get("available_device_count", 0) or 0)
    focus_count = int(kpis.get("operator_focus_count", 0) or 0)
    focus_devices = _focus_devices(dashboard)
    return OperatorAssistantState(
        generated_at=datetime.now(timezone.utc),
        summary_ko=(
            "EdgeX 기반 read-only 운영 보조 요약입니다. "
            f"Core Metadata 등록 device {registered}개 중 available device {available}개, "
            f"우선 점검 대상 {focus_count}개입니다. "
            f"Core Data event freshness 비율은 {kpis.get('core_data_freshness_ratio', 0)}입니다."
        ),
        focus_devices=focus_devices,
        recommended_actions=_recommended_actions(focus_devices),
        guardrails=GUARDRAILS,
        source_endpoints=SOURCE_ENDPOINTS,
    )


def degraded_operator_chat_response(model: str, assistant: OperatorAssistantState) -> OperatorChatResponse:
    return OperatorChatResponse(
        model=model,
        answer="dashboard 상태는 읽을 수 있지만 service resource observation이 degraded 상태입니다. observation_error를 먼저 확인해 주세요.",
        source_endpoints=assistant.source_endpoints,
        guardrails=assistant.guardrails,
        upstream_status="degraded_observation",
    )


def _focus_devices(dashboard: DashboardState) -> list[JsonMap]:
    focused: list[JsonMap] = []
    for device in dashboard.devices:
        status, reason = _device_health(device)
        if status not in {"degraded", "unavailable"}:
            continue
        focused.append(
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
    return focused[:10]


def _recommended_actions(focus_devices: list[JsonMap]) -> list[str]:
    actions: list[str] = []
    for device in focus_devices:
        name = str(device.get("name") or "unknown-device")
        if str(device.get("admin_state", "")).upper() == "LOCKED":
            actions.append(f"{name}: Core Metadata adminState 잠금 정책을 확인한다.")
        if not device.get("device_service_available", False):
            actions.append(f"{name}: EdgeX device service와 operatingState를 확인한다.")
        if device.get("telemetry_freshness") != "fresh":
            actions.append(f"{name}: Core Data 최신 event와 device service 수집 경로를 확인한다.")
    return actions[:10] or ["현재 우선 점검 대상이 없으므로 EdgeX KPI를 확인한다."]


def _device_health(device: DeviceState) -> tuple[str, str]:
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
