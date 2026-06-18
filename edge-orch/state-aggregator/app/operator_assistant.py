from __future__ import annotations

from datetime import datetime, timezone

from .models import DashboardState, OperatorAssistantState, OperatorChatResponse
from .virtual_resources import JsonMap

SOURCE_ENDPOINTS = ["/state/dashboard", "/state/devices", "/state/nodes", "/state/summary", "/state/virtual-resources"]
GUARDRAILS = [
    "read-only endpoint: Kubernetes 리소스, Device CR, command topic을 수정하지 않는다.",
    "운영자에게 점검 순서만 제안하고 rollout/delete/apply 같은 조치는 실행하지 않는다.",
    "workflow/offloading/agent-assisted planning 판단으로 해석하지 않는다.",
]


def operator_assistant_from_dashboard(dashboard: DashboardState) -> OperatorAssistantState:
    kpis = dashboard.kpis
    registered = int(kpis.get("registered_device_count", len(dashboard.devices)) or 0)
    live = int(kpis.get("live_device_count", 0) or 0)
    focus_count = int(kpis.get("operator_focus_count", 0) or 0)
    service_bound = int(kpis.get("service_bound_device_count", 0) or 0)
    focus_devices = _focus_devices(dashboard)
    return OperatorAssistantState(
        generated_at=datetime.now(timezone.utc),
        summary_ko=(
            "Kagenti 연동 PoC용 read-only 운영 보조 요약입니다. "
            f"등록 device {registered}개 중 live device {live}개, "
            f"서비스 데모 연결 device {service_bound}개, 우선 점검 대상 {focus_count}개입니다. "
            f"telemetry configured 비율은 {kpis.get('device_telemetry_ratio', 0)}이고, "
            f"실제 센서 데이터 freshness 비율은 {kpis.get('sensor_data_freshness_ratio', 0)}입니다."
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
    return [
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


def _recommended_actions(focus_devices: list[JsonMap]) -> list[str]:
    actions: list[str] = []
    for device in focus_devices:
        name = str(device.get("name") or "unknown-device")
        if not device.get("node_ready", False):
            actions.append(f"{name}: 할당 node Ready 상태와 edgecore/cloudcore 연결을 먼저 확인한다.")
        if not device.get("mapper_running", False):
            actions.append(f"{name}: mqttvirtual mapper pod Running 여부와 node 배치를 확인한다.")
        if not device.get("telemetry_fresh", False):
            actions.append(f"{name}: sensor data freshness는 availability 판단과 별도 KPI다. EdgeX/collector/MQTT/DB 적재 경로를 별도 확인한다.")
        if device.get("telemetry_fresh") and not device.get("device_status_fresh", False):
            actions.append(f"{name}: DeviceStatus snapshot 대상 property와 mapper allowlist 정책을 확인한다.")
    return actions[:10] or ["현재 우선 점검 대상이 없으므로 dashboard KPI와 service demo group만 확인한다."]
