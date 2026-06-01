from __future__ import annotations

import os
import inspect
from dataclasses import dataclass
from typing import Any, Callable

from tools.k8s_tools import get_gpu_status, get_k8s_events, get_k8s_nodes, get_k8s_pods
from tools.kubeedge_tools import get_device_twin, get_kubeedge_devices
from tools.mqtt_tools import get_mqtt_status
from tools.prometheus_tools import query_prometheus
from tools.shell_tools import run_shell

try:
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatClient
except Exception:  # pragma: no cover - lets health checks run before deps exist.
    Agent = None  # type: ignore[assignment]
    OpenAIChatClient = None  # type: ignore[assignment]


COMMON_SAFETY_INSTRUCTIONS = """
모든 사용자-facing 응답은 한국어로 한다.
실제 삭제, 재시작, 배포 변경, scale, rollout, apply, delete, patch, label, annotate 명령은 실행하지 않는다.
Planner Agent는 계획만 만들고 즉시 실행하지 않는다. 모든 변경 제안은 사용자 승인 대기 상태로 둔다.
run_shell은 테스트용이며 운영 전 제거 또는 제한 tool로 분리해야 한다.
사용자가 일반 대화를 하면 운영 도구를 호출하지 말고 자연스럽게 대화한다.
도구 결과가 질문과 직접 관련 없으면 답변에 억지로 포함하지 않는다.
"""


@dataclass(frozen=True)
class AgentSpec:
    name: str
    instructions: str
    tools: tuple[Callable[..., Any], ...]


def _chat_client() -> Any:
    if OpenAIChatClient is None:
        return None
    signature = inspect.signature(OpenAIChatClient)
    kwargs: dict[str, Any] = {
        "api_key": os.getenv("OPENAI_API_KEY", "ollama"),
    }
    if "base_url" in signature.parameters:
        kwargs["base_url"] = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    model_id = os.getenv("OPENAI_MODEL_ID", "qwen3:8b")
    if "model_id" in signature.parameters:
        kwargs["model_id"] = model_id
    elif "model" in signature.parameters:
        kwargs["model"] = model_id
    return OpenAIChatClient(**kwargs)


def _build_agent(spec: AgentSpec, client: Any) -> Any:
    if Agent is None or client is None:
        return None
    try:
        return Agent(
            chat_client=client,
            name=spec.name,
            instructions=spec.instructions,
            tools=list(spec.tools),
        )
    except TypeError:
        return Agent(
            client,
            name=spec.name,
            instructions=spec.instructions,
            tools=list(spec.tools),
        )


def create_agents() -> dict[str, Any]:
    client = _chat_client()
    specs = {
        "orchestrator": AgentSpec(
            name="Orchestrator Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + """
        너는 KubeEdge 기반 Edge AI 운영 대화형 오케스트레이터다.

        사용자와 자연스럽게 대화한다.
        항상 모든 도구를 호출하지 않는다.
        단순 질문이면 바로 답한다.
        상태 확인 요청이면 필요한 조회 도구만 호출한다.
        장애, 병목, 지연, 재배치, 오프로딩 요청이면 관련 도구를 순차적으로 호출해 원인을 분석한다.

        사용 가능한 역할:
        - Status Agent 역할: Kubernetes Node, Pod, Event, GPU 상태 확인
        - Metrics Agent 역할: Prometheus 지표 확인
        - Device Agent 역할: KubeEdge Device, Device Twin 확인
        - Diagnosis Agent 역할: 수집 결과 기반 원인 분석
        - Planner Agent 역할: 조치 후보 제안

        중요:
        - 운영 변경은 직접 실행하지 않는다.
        - kubectl apply/delete/scale/rollout/restart/patch/label/annotate는 실행하지 않는다.
        - 필요한 경우 "승인이 필요합니다"라고 말하고 계획만 제시한다.
        - 답변은 한국어로 한다.
        """,
            tools=(
                get_k8s_nodes,
                get_k8s_pods,
                get_k8s_events,
                get_gpu_status,
                get_kubeedge_devices,
                get_device_twin,
                query_prometheus,
                get_mqtt_status,
                run_shell,
            ),
        ),
    }
    return {key: _build_agent(spec, client) for key, spec in specs.items()}
