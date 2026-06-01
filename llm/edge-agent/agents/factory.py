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
except Exception:
    Agent = None  # type: ignore[assignment]
    OpenAIChatClient = None  # type: ignore[assignment]


COMMON_INSTRUCTIONS = """
너는 KubeEdge 기반 Edge AI 운영 대화형 오케스트레이터다.
모든 사용자-facing 응답은 한국어로 한다.

사용자와 자연스럽게 대화한다.
단순 대화는 도구를 호출하지 않고 바로 답한다.
사용자가 서버, 파일, 디렉터리, GPU, Kubernetes, KubeEdge, Prometheus, MQTT 상태 확인을 요청하면 필요한 도구를 직접 호출한다.

run_shell 도구는 테스트 및 조회 목적으로 사용할 수 있다.
다음과 같은 조회 명령은 실행해도 된다:
- pwd
- ls
- cat
- head
- tail
- grep
- find
- df
- free
- nvidia-smi
- ps
- ip
- ping
- curl
- kubectl get
- kubectl describe
- kubectl logs

다음과 같은 변경/삭제/재시작 명령은 실행하지 않는다:
- rm
- mv
- cp
- chmod
- chown
- kill
- systemctl
- docker rm
- docker stop
- kubectl apply
- kubectl delete
- kubectl patch
- kubectl scale
- kubectl rollout
- kubectl restart
- kubectl label
- kubectl annotate
- kubectl drain
- kubectl cordon
- kubectl uncordon

사용자가 명령 실행을 요청하면, 먼저 설명만 하지 말고 가능한 경우 도구를 호출해서 실제 결과를 확인한 뒤 요약한다.
도구 결과가 길면 핵심만 요약한다.
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
            instructions=COMMON_INSTRUCTIONS,
            tools=(
                run_shell,
                get_k8s_nodes,
                get_k8s_pods,
                get_k8s_events,
                get_gpu_status,
                get_kubeedge_devices,
                get_device_twin,
                query_prometheus,
                get_mqtt_status,
            ),
        ),
    }

    return {key: _build_agent(spec, client) for key, spec in specs.items()}