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
        "coordinator": AgentSpec(
            name="Coordinator Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + """
사용자 요청을 수신하고 Status, Metrics, Device, Diagnosis, Planner 결과를 종합한다.
운영 상태 설명은 간결하고 실행 가능한 한국어로 제공한다.
""",
            tools=(
                get_k8s_nodes,
                get_k8s_pods,
                get_k8s_events,
                get_gpu_status,
                get_kubeedge_devices,
                query_prometheus,
                get_mqtt_status,
            ),
        ),
        "status": AgentSpec(
            name="Status Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + "Kubernetes Node, Pod, Event, GPU 상태를 읽기 전용으로 조회한다.",
            tools=(get_k8s_nodes, get_k8s_pods, get_k8s_events, get_gpu_status),
        ),
        "device": AgentSpec(
            name="Device Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + "KubeEdge Device, Device Twin, Edge Device 상태를 조회한다.",
            tools=(get_kubeedge_devices, get_device_twin),
        ),
        "metrics": AgentSpec(
            name="Metrics Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + "Prometheus Query로 CPU, Memory, GPU, Network, RTT, Throughput을 조회한다.",
            tools=(query_prometheus,),
        ),
        "diagnosis": AgentSpec(
            name="Diagnosis Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + "장애 원인, 병목 원인, 서비스 상태를 진단한다.",
            tools=(get_k8s_nodes, get_k8s_pods, get_k8s_events, query_prometheus),
        ),
        "planner": AgentSpec(
            name="Planner Agent",
            instructions=COMMON_SAFETY_INSTRUCTIONS
            + """
오프로딩, 재배치, Scale-Out, Recovery Plan을 생성한다.
절대 즉시 실행하지 말고 승인 필요 계획만 만든다.
Executor Agent는 초기 버전에서 구현하지 않는다.
""",
            tools=(get_k8s_nodes, get_k8s_pods, query_prometheus, run_shell),
        ),
    }
    return {key: _build_agent(spec, client) for key, spec in specs.items()}
