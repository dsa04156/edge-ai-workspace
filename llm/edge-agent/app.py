from __future__ import annotations

import inspect
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.factory import create_agents
from tools.k8s_tools import get_gpu_status, get_k8s_events, get_k8s_nodes, get_k8s_pods
from tools.kubeedge_tools import get_kubeedge_devices
from tools.mqtt_tools import get_mqtt_status
from tools.prometheus_tools import query_prometheus
from workflows.approval_store import ApprovalStore


app = FastAPI(title="KubeEdge Edge AI Operations Agent", version="0.1.0")
approval_store = ApprovalStore()
agents = create_agents()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    plan_id: str | None = None
    approval_required: bool = False


class ApprovalResponse(BaseModel):
    response: str
    plan_id: str
    approval_required: bool = False
    status: str


def _needs_plan(message: str) -> bool:
    keywords = (
        "계획",
        "제안",
        "오프로딩",
        "재배치",
        "scale",
        "scale-out",
        "스케일",
        "복구",
        "recovery",
        "rollout",
        "배포",
        "느린",
        "장애",
        "병목",
    )
    lower_message = message.lower()
    return any(keyword in lower_message for keyword in keywords)


async def _run_agent(agent_name: str, prompt: str) -> str | None:
    agent = agents.get(agent_name)
    if agent is None:
        return None
    try:
        for method_name in ("run", "invoke", "complete"):
            method = getattr(agent, method_name, None)
            if method is None:
                continue
            result = method(prompt)
            if inspect.isawaitable(result):
                result = await result
            return str(result)
    except Exception:
        return None
    return None


def _collect_read_only_context() -> dict[str, Any]:
    return {
        "nodes": get_k8s_nodes(),
        "pods": get_k8s_pods(),
        "events": get_k8s_events(),
        "gpu": get_gpu_status(),
        "devices": get_kubeedge_devices(),
        "mqtt": get_mqtt_status(),
        "metrics": {
            "cpu": query_prometheus(
                'sum(rate(container_cpu_usage_seconds_total{container!="POD"}[5m]))'
            ),
            "memory": query_prometheus(
                'sum(container_memory_working_set_bytes{container!="POD"})'
            ),
            "network": query_prometheus(
                "sum(rate(container_network_receive_bytes_total[5m]))"
            ),
        },
    }


def _make_plan(message: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "Edge AI 서비스 상태를 읽기 전용으로 확인한 뒤, 승인 기반 조치 후보를 제안합니다.",
        "requested_by": message,
        "steps": [
            {
                "order": 1,
                "agent": "Status Agent",
                "action": "Node, Pod, Event, GPU 상태를 확인하고 비정상 상태를 분류합니다.",
                "execution": "read_only",
            },
            {
                "order": 2,
                "agent": "Metrics Agent",
                "action": "Prometheus에서 CPU, Memory, GPU, Network, RTT, Throughput 지표를 비교합니다.",
                "execution": "read_only",
            },
            {
                "order": 3,
                "agent": "Device Agent",
                "action": "KubeEdge Device와 Device Twin 상태를 확인합니다.",
                "execution": "read_only",
            },
            {
                "order": 4,
                "agent": "Diagnosis Agent",
                "action": "RTSP AI 서비스 지연의 원인이 리소스 부족, 네트워크, 장치 상태, Pod 재시작 중 어디에 가까운지 진단합니다.",
                "execution": "analysis_only",
            },
            {
                "order": 5,
                "agent": "Planner Agent",
                "action": "오프로딩, 재배치, Scale-Out, Recovery 후보를 생성합니다.",
                "execution": "approval_required_no_execution",
            },
        ],
        "guardrails": [
            "초기 버전에서는 kubectl apply/delete/scale/rollout/restart/patch/label/annotate를 실행하지 않습니다.",
            "승인 API는 상태만 approved_not_executed로 변경하며 실제 Executor를 호출하지 않습니다.",
        ],
        "context_snapshot": context,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    context = _collect_read_only_context()
    plan_id = None
    approval_required = False

    agent_response = await _run_agent(
        "coordinator",
        f"""
사용자 요청: {request.message}
읽기 전용 운영 컨텍스트: {context}
한국어로 답변하고, 실제 변경 명령은 실행하지 마세요.
""",
    )

    if _needs_plan(request.message):
        plan = _make_plan(request.message, context)
        record = approval_store.create_plan(request.message, plan)
        plan_id = record["plan_id"]
        approval_required = True
        fallback = (
            "요청을 분석했습니다. 현재 버전은 운영 변경을 즉시 실행하지 않으며, "
            f"읽기 전용 점검과 조치 후보를 승인 대기 계획으로 저장했습니다. plan_id={plan_id}"
        )
    else:
        fallback = (
            "요청을 읽기 전용으로 처리했습니다. Kubernetes, KubeEdge Device, Prometheus, MQTT "
            "상태 조회 도구를 사용해 상태를 종합할 수 있습니다."
        )

    return ChatResponse(
        response=agent_response or fallback,
        plan_id=plan_id,
        approval_required=approval_required,
    )


@app.post("/plans/{plan_id}/approve", response_model=ApprovalResponse)
def approve_plan(plan_id: str) -> ApprovalResponse:
    record = approval_store.approve_plan(plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="plan_id를 찾을 수 없습니다.")
    return ApprovalResponse(
        response=(
            "계획이 승인 상태로 변경되었습니다. 초기 버전에서는 안전을 위해 실제 "
            "kubectl apply/delete/scale/rollout 등 운영 변경은 실행하지 않습니다."
        ),
        plan_id=plan_id,
        approval_required=False,
        status=record["status"],
    )
