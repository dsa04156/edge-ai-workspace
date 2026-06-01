from __future__ import annotations

import inspect
import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.factory import create_agents
from workflows.approval_store import ApprovalStore


app = FastAPI(title="KubeEdge Edge AI Operations Agent", version="0.1.0")
approval_store = ApprovalStore()
conversation_history: list[dict[str, str]] = []


AGENT_NAMES = ("status", "metrics", "device", "shell", "diagnosis", "planner")


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
    explicit_action_words = ("해줘", "만들어", "작성", "제안", "계획", "복구안", "조치안")
    return any(keyword in lower_message for keyword in keywords) and any(
        word in lower_message for word in explicit_action_words
    )


async def _run_agent(agent_name: str, prompt: str) -> str | None:
    agents = create_agents()
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


def _history_text() -> str:
    recent = conversation_history[-8:]
    return "\n".join(f"{item['role']}: {item['content']}" for item in recent)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _fallback_route(message: str) -> dict[str, Any]:
    lower = message.lower()
    selected: list[str] = []
    if any(word in lower for word in ("노드", "pod", "파드", "이벤트", "gpu", "상태")):
        selected.append("status")
    if any(word in lower for word in ("메트릭", "prometheus", "cpu", "memory", "메모리", "network", "rtt", "throughput")):
        selected.append("metrics")
    if any(word in lower for word in ("device", "디바이스", "twin", "센서", "kubeedge")):
        selected.append("device")
    if any(word in lower for word in ("장애", "느려", "느린", "병목", "원인", "진단")):
        selected.extend(["status", "metrics", "diagnosis"])
    if any(word in lower for word in ("명령", "shell", "로그", "확인해줘")) and "kubectl" in lower:
        selected.append("shell")
    if _needs_plan(message):
        selected.append("planner")

    deduped = [name for name in AGENT_NAMES if name in selected]
    return {
        "mode": "delegate" if deduped else "chat",
        "agents": deduped,
        "reason": "keyword fallback",
        "clarifying_question": "",
    }


async def _orchestrate(message: str) -> dict[str, Any]:
    prompt = f"""
너는 KubeEdge Edge AI 운영 플랫폼의 Orchestrator Agent다.
사용자와 자연스럽게 계속 대화한다.

사용자 최근 대화:
{_history_text()}

현재 사용자 메시지:
{message}

아래 JSON만 출력한다. 설명 문장은 출력하지 않는다.
{{
  "mode": "chat" | "delegate" | "clarify",
  "agents": ["status" | "metrics" | "device" | "shell" | "diagnosis" | "planner"],
  "reason": "짧은 판단 이유",
  "clarifying_question": "mode가 clarify일 때 사용자에게 물을 한 문장"
}}

판단 기준:
- 단순 인사, 개념 질문, 이전 답변에 대한 후속 질문은 mode=chat.
- 운영 상태 조회가 필요할 때만 필요한 하위 Agent를 agents에 넣고 mode=delegate.
- 범위가 너무 넓거나 대상 서비스/namespace/node가 불명확하면 mode=clarify.
- Planner는 사용자가 명시적으로 계획, 조치안, 복구안, 스케일 제안 등을 요구할 때만 선택.
- Shell은 사용자가 명시적으로 제한된 테스트/조회 명령을 요구할 때만 선택.
"""
    result = await _run_agent("coordinator", prompt)
    parsed = _extract_json_object(result or "")
    if not parsed:
        return _fallback_route(message)
    agents = [
        name
        for name in parsed.get("agents", [])
        if isinstance(name, str) and name in AGENT_NAMES
    ]
    mode = parsed.get("mode")
    if mode not in {"chat", "delegate", "clarify"}:
        mode = "delegate" if agents else "chat"
    return {
        "mode": mode,
        "agents": agents,
        "reason": str(parsed.get("reason", "")),
        "clarifying_question": str(parsed.get("clarifying_question", "")),
    }


async def _collect_agent_results(message: str, selected_agents: list[str]) -> dict[str, str]:
    results: dict[str, str] = {}
    for agent_name in selected_agents:
        prompt = f"""
사용자 요청:
{message}

너는 {agent_name} Agent다. 네 책임 범위에 해당하는 정보만 확인하고 한국어로 짧게 요약한다.
질문과 직접 관련 없는 정보는 생략한다.
실제 변경 명령은 실행하지 않는다.
"""
        result = await _run_agent(agent_name, prompt)
        if result:
            results[agent_name] = result
    return results


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
    agent_response = await _run_agent(
        "orchestrator",
        request.message,
    )

    return ChatResponse(
        response=agent_response or "응답 생성에 실패했습니다.",
        plan_id=None,
        approval_required=False,
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
