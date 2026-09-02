from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .config import Settings
from .contracts import contract_schemas
from .inference_api import (
    InferenceEngine,
    InferenceInputError,
    InferenceModelVersionMismatch,
    InferenceRequestConflict,
)
from .models import (
    AlertEnvelope,
    InferenceRequest,
    InferenceResponse,
    InferenceRoutingChangeRequest,
    InferenceRoutingPreflight,
    InferenceRoutingStatus,
    ResultEnvelope,
    ServiceStatus,
    StorageStatus,
)
from .runtime import AnomalyRuntime, build_runtime


def create_app(
    runtime: AnomalyRuntime | None = None,
    settings: Settings | None = None,
    inference_engine: InferenceEngine | None = None,
) -> FastAPI:
    selected_settings = settings or Settings.from_env()
    selected_runtime = runtime
    selected_inference_engine = inference_engine
    if (
        selected_inference_engine is None
        and selected_settings.service_role == "inference-server"
    ):
        selected_inference_engine = InferenceEngine(selected_settings)
    if selected_runtime is None and selected_settings.service_role == "edge-worker":
        selected_runtime = build_runtime(selected_settings)
    if (
        selected_runtime is None
        and selected_settings.service_role == "inference-server"
        and selected_settings.inference_warmup_source_enabled
        and selected_inference_engine is not None
    ):
        selected_runtime = build_runtime(
            selected_settings,
            model_adapter=selected_inference_engine.model_adapter,
        )

    def require_runtime() -> AnomalyRuntime:
        if selected_runtime is None:
            raise HTTPException(status_code=404, detail="edge worker API is not enabled")
        return selected_runtime

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if selected_runtime is not None:
            await selected_runtime.start()
        try:
            yield
        finally:
            if selected_runtime is not None:
                await selected_runtime.stop()

    application = FastAPI(
        title="sensor-anomaly-demo",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        if selected_settings.service_role == "inference-server":
            if (
                selected_settings.inference_warmup_source_enabled
                and (selected_runtime is None or not selected_runtime.worker_started)
            ):
                raise HTTPException(
                    status_code=503,
                    detail="inference warm-up worker is not running",
                )
            return {"status": "ok", "role": "inference-server"}
        if selected_runtime is None or not selected_runtime.worker_started:
            raise HTTPException(status_code=503, detail="polling worker is not running")
        return {"status": "ok"}

    @application.get("/readyz")
    async def readyz() -> dict[str, str]:
        if selected_settings.service_role == "inference-server":
            if (
                selected_settings.inference_warmup_source_enabled
                and (selected_runtime is None or not selected_runtime.worker_started)
            ):
                raise HTTPException(
                    status_code=503,
                    detail="inference warm-up worker is not running",
                )
            return {"status": "ready", "role": "inference-server"}
        if selected_runtime is None or not selected_runtime.worker_started:
            raise HTTPException(status_code=503, detail="polling worker is not running")
        return {"status": "ready"}

    @application.get("/api/v1/augmentation-readyz")
    async def augmentation_readyz() -> dict[str, str]:
        if selected_settings.service_role == "inference-server":
            if selected_inference_engine is None or not selected_inference_engine.ready:
                raise HTTPException(
                    status_code=503,
                    detail="the inference model is not ready",
                )
            return {
                "status": "ready",
                "capability": "sensor-anomaly-inference",
                "role": "inference-server",
                "modelVersion": selected_inference_engine.model_adapter.version,
                "modelBackend": selected_inference_engine.model_adapter.backend,
                "accelerator": selected_inference_engine.model_adapter.accelerator,
                "acceleratorDevice": selected_inference_engine.model_adapter.accelerator_device,
            }
        state = require_runtime().status()
        if state.input_state != "fresh" or state.model_state != "ready":
            raise HTTPException(
                status_code=503,
                detail="fresh input and a ready model are required",
            )
        return {"status": "ready", "capability": "sensor-anomaly-inference"}

    @application.get(
        "/api/v1/inference-routing/preflight",
        response_model=InferenceRoutingPreflight,
    )
    async def inference_routing_preflight() -> InferenceRoutingPreflight:
        runtime_instance = require_runtime()
        if selected_settings.remote_inference_mode != "approved":
            raise HTTPException(
                status_code=409,
                detail="remote inference routing is not approved for this workload",
            )
        return await runtime_instance.inference_router.preflight()

    @application.post("/infer", response_model=InferenceResponse)
    @application.post("/api/v1/inference", response_model=InferenceResponse)
    async def inference(request: InferenceRequest) -> InferenceResponse:
        if (
            selected_settings.service_role != "inference-server"
            or selected_inference_engine is None
        ):
            raise HTTPException(status_code=404, detail="inference API is not enabled")
        try:
            return selected_inference_engine.infer(request)
        except InferenceRequestConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InferenceModelVersionMismatch as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InferenceInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.post(
        "/api/v1/inference-routing",
        response_model=InferenceRoutingStatus,
    )
    async def change_inference_routing(
        request: InferenceRoutingChangeRequest,
        approval_id: str | None = Header(
            default=None,
            alias="X-Offload-Approval",
        ),
    ) -> InferenceRoutingStatus:
        runtime_instance = require_runtime()
        if selected_settings.remote_inference_mode != "approved":
            raise HTTPException(
                status_code=409,
                detail="remote inference routing is not approved for this workload",
            )
        if (
            approval_id is None
            or approval_id != selected_settings.remote_inference_control_token
        ):
            raise HTTPException(
                status_code=403,
                detail="a valid offload approval is required",
            )
        try:
            if request.mode == "REMOTE":
                return runtime_instance.inference_router.activate_remote(
                    selected_settings.remote_inference_approval_id or ""
                )
            return runtime_instance.inference_router.activate_local()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get("/api/v1/status", response_model=ServiceStatus)
    async def status() -> ServiceStatus:
        return require_runtime().status()

    @application.get("/api/v1/results", response_model=ResultEnvelope)
    async def results(
        limit: int = Query(default=100, ge=1, le=1_000),
        anomaly: bool | None = Query(default=None),
        from_origin: int | None = Query(default=None, alias="fromOrigin", ge=1),
        to_origin: int | None = Query(default=None, alias="toOrigin", ge=1),
    ) -> ResultEnvelope:
        if (
            from_origin is not None
            and to_origin is not None
            and from_origin > to_origin
        ):
            raise HTTPException(
                status_code=422,
                detail="fromOrigin must not exceed toOrigin",
            )
        rows = require_runtime().results(
            limit,
            anomaly=anomaly,
            from_origin=from_origin,
            to_origin=to_origin,
        )
        return ResultEnvelope(count=len(rows), results=rows)

    @application.get("/api/v1/alerts", response_model=AlertEnvelope)
    async def alerts(
        limit: int = Query(default=100, ge=1, le=1_000),
        status: Literal["open", "closed"] | None = Query(default=None),
    ) -> AlertEnvelope:
        rows = require_runtime().alerts(limit, status=status)
        return AlertEnvelope(count=len(rows), alerts=rows)

    @application.get("/api/v1/storage", response_model=StorageStatus)
    async def storage() -> StorageStatus:
        return require_runtime().storage_status()

    @application.get("/api/v1/contracts")
    async def contracts() -> dict[str, dict]:
        return contract_schemas()

    @application.get("/api/v1/contracts/{contract_name}")
    async def contract(contract_name: str) -> dict:
        schemas = contract_schemas()
        if contract_name not in schemas:
            raise HTTPException(status_code=404, detail="contract was not found")
        return schemas[contract_name]

    @application.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> PlainTextResponse:
        state = require_runtime().status()
        performance = state.performance
        resources = state.process_resources
        routing = state.inference_routing
        inference_mode_value = {
            "LOCAL": 0,
            "REMOTE": 1,
            "LOCAL_FALLBACK": 2,
        }[routing.inference_mode]
        lines = [
            "# HELP sensor_anomaly_processing_latency_p95_ms Five-minute processing latency p95.",
            "# TYPE sensor_anomaly_processing_latency_p95_ms gauge",
            f"sensor_anomaly_processing_latency_p95_ms {performance.processing_latency_p95_ms}",
            "# HELP sensor_anomaly_backlog Pending frames awaiting join or alignment.",
            "# TYPE sensor_anomaly_backlog gauge",
            f"sensor_anomaly_backlog {performance.backlog}",
            "# HELP sensor_anomaly_throughput_per_second Processed inference results per second.",
            "# TYPE sensor_anomaly_throughput_per_second gauge",
            f"sensor_anomaly_throughput_per_second {performance.throughput_per_second}",
            "# HELP sensor_anomaly_performance_metrics_valid Whether the service SLI window is usable.",
            "# TYPE sensor_anomaly_performance_metrics_valid gauge",
            f"sensor_anomaly_performance_metrics_valid {1 if performance.metrics_valid else 0}",
            "# HELP sensor_anomaly_process_cpu_cores Main process CPU cores used over the latest observation interval.",
            "# TYPE sensor_anomaly_process_cpu_cores gauge",
            f"sensor_anomaly_process_cpu_cores {resources.cpu_cores if resources.cpu_cores is not None else 'NaN'}",
            "# HELP sensor_anomaly_process_resident_memory_bytes Main process resident memory.",
            "# TYPE sensor_anomaly_process_resident_memory_bytes gauge",
            f"sensor_anomaly_process_resident_memory_bytes {resources.memory_rss_mib * 1024 * 1024 if resources.memory_rss_mib is not None else 'NaN'}",
            "# HELP sensor_anomaly_process_resource_metrics_valid Whether interval CPU and current RSS are both available.",
            "# TYPE sensor_anomaly_process_resource_metrics_valid gauge",
            f"sensor_anomaly_process_resource_metrics_valid {1 if resources.metrics_valid else 0}",
            "# HELP sensor_anomaly_inference_mode Current inference execution mode: 0 local, 1 remote, 2 fallback.",
            "# TYPE sensor_anomaly_inference_mode gauge",
            f"sensor_anomaly_inference_mode {inference_mode_value}",
            "# HELP sensor_anomaly_remote_inference_success_ratio Successful remote inference requests divided by attempts.",
            "# TYPE sensor_anomaly_remote_inference_success_ratio gauge",
            f"sensor_anomaly_remote_inference_success_ratio {routing.offload_success_rate if routing.offload_success_rate is not None else 'NaN'}",
            "# HELP sensor_anomaly_remote_inference_fallback_total Number of per-request local fallbacks.",
            "# TYPE sensor_anomaly_remote_inference_fallback_total counter",
            f"sensor_anomaly_remote_inference_fallback_total {routing.fallback_count}",
            "# HELP sensor_anomaly_inference_total_latency_ms Latest authoritative inference latency.",
            "# TYPE sensor_anomaly_inference_total_latency_ms gauge",
            f"sensor_anomaly_inference_total_latency_ms {routing.total_latency_ms if routing.total_latency_ms is not None else 'NaN'}",
            "# HELP sensor_anomaly_remote_network_latency_ms Latest remote round-trip latency excluding reported server processing.",
            "# TYPE sensor_anomaly_remote_network_latency_ms gauge",
            f"sensor_anomaly_remote_network_latency_ms {routing.network_latency_ms if routing.network_latency_ms is not None else 'NaN'}",
            "# HELP sensor_anomaly_remote_processing_latency_ms Latest remote server processing latency.",
            "# TYPE sensor_anomaly_remote_processing_latency_ms gauge",
            f"sensor_anomaly_remote_processing_latency_ms {routing.remote_processing_ms if routing.remote_processing_ms is not None else 'NaN'}",
        ]
        return PlainTextResponse(
            content="\n".join(lines) + "\n",
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return application


app = create_app()
