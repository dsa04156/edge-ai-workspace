from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Literal, Protocol

from .model_adapter import ModelDecision
from .models import AccelerationFrame, AxisSample


InferenceExecutionMode = Literal["local", "remote", "fallback"]


@dataclass(frozen=True)
class InferenceExecutionRequest:
    service_id: str
    request_id: str
    timestamp: datetime
    model_version: str
    source_node: str
    frame: AccelerationFrame
    temperature: AxisSample


@dataclass(frozen=True)
class InferenceExecutionResult:
    decision: ModelDecision
    request_id: str
    execution_mode: InferenceExecutionMode
    model_version: str
    source_node: str
    remote_node: str | None = None
    local_latency_ms: float | None = None
    network_latency_ms: float | None = None
    remote_processing_ms: float | None = None
    total_latency_ms: float | None = None
    fallback: bool = False
    reason_code: str | None = None


class InferenceExecutor(Protocol):
    async def execute(
        self,
        request: InferenceExecutionRequest,
    ) -> InferenceExecutionResult: ...


class LocalInferenceExecutor:
    """Executes the existing model adapter without changing its algorithm."""

    def __init__(
        self,
        infer: Callable[[], ModelDecision | None],
        *,
        fallback: bool = False,
        reason_code: str | None = None,
        elapsed_before_local_ms: float = 0.0,
    ) -> None:
        self._infer = infer
        self._fallback = fallback
        self._reason_code = reason_code
        self._elapsed_before_local_ms = max(0.0, elapsed_before_local_ms)

    async def execute(
        self,
        request: InferenceExecutionRequest,
    ) -> InferenceExecutionResult:
        started = time.perf_counter()
        decision = self._infer()
        if decision is None:
            raise RuntimeError("local_inference_input_unavailable")
        local_latency_ms = (time.perf_counter() - started) * 1_000
        return InferenceExecutionResult(
            decision=decision,
            request_id=request.request_id,
            execution_mode="fallback" if self._fallback else "local",
            model_version=request.model_version,
            source_node=request.source_node,
            local_latency_ms=round(local_latency_ms, 6),
            total_latency_ms=round(
                self._elapsed_before_local_ms + local_latency_ms,
                6,
            ),
            fallback=self._fallback,
            reason_code=self._reason_code,
        )


class RemoteInferenceTransport(Protocol):
    async def execute(
        self,
        request: InferenceExecutionRequest,
    ) -> InferenceExecutionResult: ...


class RemoteInferenceExecutor:
    """Runs only the approved remote transport; fallback stays in the router."""

    def __init__(self, transport: RemoteInferenceTransport) -> None:
        self._transport = transport

    async def execute(
        self,
        request: InferenceExecutionRequest,
    ) -> InferenceExecutionResult:
        return await self._transport.execute(request)
