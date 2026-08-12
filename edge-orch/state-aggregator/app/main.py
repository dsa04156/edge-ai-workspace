from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .augmentation_crds import (
    AugmentationCrdReader,
    AugmentationResourceCrdState,
    DeviceAugmentationCrdState,
)
from .config import Settings
from .edgex import EdgeXError
from .metrics import render_metrics
from .models import (
    CostModelState,
    DashboardState,
    DeviceState,
    OperatorAssistantState,
    OperatorChatRequest,
    OperatorChatResponse,
    SummaryState,
    TelemetryPoint,
    WorkflowEvent,
    WorkflowState,
    ProjectionError,
    VirtualDeviceCollection,
    VirtualDeviceView,
)
from .operator_assistant import degraded_operator_chat_response, operator_assistant_from_dashboard
from .runtime_augmentation import RuntimeAugmentationState
from .runtime_augmentation_api import RuntimeAugmentationQuery, runtime_resource_augmentation_state
from .resource_pool import ResourcePoolState, build_resource_pool_state
from .service import StateAggregatorService
from .virtual_device_bindings import BindingConfigError, load_virtual_device_bindings
from .virtual_resource_registry import RESOURCE_REGISTRY
from .virtual_resources import (
    JsonMap,
    VirtualResourceProfile,
    VirtualResourceState,
    VirtualResourceTwin,
    build_virtual_resource_state,
)

settings = Settings()
service = StateAggregatorService(settings)
augmentation_crds = AugmentationCrdReader()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.virtual_device_projection_enabled and service.bindings is None:
        path = settings.virtual_device_bindings_path
        if path is None:
            raise BindingConfigError(
                "virtual_device_bindings_path is required when projection is enabled"
            )
        service.bindings = load_virtual_device_bindings(path)
    await service.start()
    try:
        yield
    finally:
        await service.stop()


app = FastAPI(title="state-aggregator", version="0.1.0", lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    if (STATIC_DIR / "index.html").exists():
        return FileResponse(STATIC_DIR / "index.html")
    return {"service": "state-aggregator", "dashboard": "/dashboard"}


@app.get("/dashboard")
async def dashboard():
    if not (STATIC_DIR / "index.html").exists():
        raise HTTPException(status_code=404, detail="Dashboard assets not found")
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/workflow-event", response_model=WorkflowState)
async def post_workflow_event(event: WorkflowEvent) -> WorkflowState:
    return service.record_workflow_event(event)


@app.get("/state/nodes")
async def get_nodes():
    return service.get_nodes()


@app.get("/state/devices", response_model=list[DeviceState])
async def get_devices() -> list[DeviceState]:
    return await service.get_devices()


@app.get("/state/devices/{device_id}/telemetry", response_model=list[TelemetryPoint])
async def get_device_telemetry(
    device_id: str,
    window: str = Query(default="-30m", pattern=r"^-[1-9][0-9]*[smhdw]$"),
    limit: int = Query(default=300, ge=1, le=1000),
) -> list[TelemetryPoint]:
    return await service.get_device_telemetry_history(
        device_id=device_id, window=window, limit=limit
    )


@app.get("/state/dashboard", response_model=DashboardState)
async def get_dashboard() -> DashboardState:
    return await _dashboard_state()


def _resource_observation_error_state(exc: httpx.HTTPError) -> JsonMap:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recorded_at": None,
        "recording_backend": "influxdb",
        "recording_mode": service.settings.resource_profile_recording_mode,
        "recording_interval_seconds": service.settings.resource_profile_record_interval_seconds,
        "last_record_result": service._last_resource_record_result,
        "profile_scope": "running_service_resource_requirements",
        "observation_error": f"service resource observation unavailable: {exc.__class__.__name__}",
        "summary": {
            "profile_count": 0,
            "running_pod_count": 0,
            "container_count": 0,
        },
        "service_resource_profiles": [],
    }


async def _dashboard_state() -> DashboardState:
    nodes = service.get_nodes()
    device_observation_error: str | None = None
    try:
        devices = await service.get_devices()
    except EdgeXError as exc:
        devices = []
        device_observation_error = (
            f"EdgeX device observation unavailable: {exc.__class__.__name__}"
        )
    workflows = service.get_workflows()
    kpis = service._build_dashboard_kpis(nodes, devices, workflows)
    try:
        resource_state = await service.get_resource_profile_state()
    except httpx.HTTPError as exc:
        resource_state = _resource_observation_error_state(exc)
    kpis.update(service._build_resource_profile_kpis(resource_state))
    return DashboardState(
        generated_at=datetime.now(timezone.utc),
        nodes=nodes,
        devices=devices,
        workflows=workflows,
        summary=service.get_summary(),
        kpis=kpis,
        resource_profiles=resource_state,
        device_observation_error=device_observation_error,
    )



@app.get("/state/operator-assistant", response_model=OperatorAssistantState)
async def get_operator_assistant() -> OperatorAssistantState:
    return operator_assistant_from_dashboard(await _dashboard_state())


@app.post("/state/operator-chat", response_model=OperatorChatResponse)
async def post_operator_chat(request: OperatorChatRequest) -> OperatorChatResponse:
    try:
        return await service.chat_with_operator_assistant(request)
    except httpx.HTTPError:
        assistant = operator_assistant_from_dashboard(await _dashboard_state())
        return degraded_operator_chat_response(settings.qwen_model, assistant)


@app.get("/state/node/{hostname}")
async def get_node(hostname: str):
    node = service.get_node(hostname)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@app.get("/state/workflows")
async def get_workflows():
    return service.get_workflows()


@app.get("/state/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    workflow = service.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@app.get("/state/summary", response_model=SummaryState)
async def get_summary() -> SummaryState:
    return service.get_summary()


@app.get("/state/cost-model", response_model=CostModelState)
async def get_cost_model() -> CostModelState:
    return service.get_cost_model()


@app.get("/state/resource-profiles")
async def get_resource_profiles(refresh: bool = False):
    return await service.get_resource_profile_state(refresh=refresh)


@app.get("/state/service-resource-profiles")
async def get_service_resource_profiles(refresh: bool = False, namespace: str | None = None, service_name: str | None = Query(default=None, alias="service")):
    state = await service.get_resource_profile_state(refresh=refresh)
    profiles = state.get("service_resource_profiles") or []
    if namespace:
        profiles = [item for item in profiles if item.get("namespace") == namespace]
    if service_name:
        profiles = [item for item in profiles if item.get("service") == service_name]
    return {
        "generated_at": state.get("generated_at"),
        "recorded_at": state.get("recorded_at"),
        "recording_backend": state.get("recording_backend"),
        "recording_mode": state.get("recording_mode"),
        "recording_interval_seconds": state.get("recording_interval_seconds"),
        "last_record_result": state.get("last_record_result"),
        "profile_scope": state.get("profile_scope"),
        "summary": state.get("summary"),
        "service_resource_profiles": profiles,
    }


async def _virtual_resource_state(refresh: bool = False) -> VirtualResourceState:
    observation_error: str | None = None
    try:
        resource_state = await service.get_resource_profile_state(refresh=refresh)
    except httpx.HTTPError as exc:
        observation_error = f"service resource observation unavailable: {exc.__class__.__name__}"
        resource_state = {}
    profiles = resource_state.get("service_resource_profiles") or []
    return build_virtual_resource_state(
        registry=RESOURCE_REGISTRY,
        service_resource_profiles=profiles,
        nodes=service.get_nodes(),
        observation_error=observation_error,
    )


@app.get("/state/virtual-resources", response_model=VirtualResourceState)
async def get_virtual_resources(refresh: bool = False) -> VirtualResourceState:
    return await _virtual_resource_state(refresh=refresh)


@app.get("/state/resource-pool", response_model=ResourcePoolState)
async def get_resource_pool(refresh: bool = False) -> ResourcePoolState:
    now = datetime.now(timezone.utc)
    virtual_devices = VirtualDeviceCollection(
        projection_enabled=False,
        generated_at=now,
        observation_time=now,
        config_revision="",
    )
    if settings.virtual_device_projection_enabled:
        try:
            virtual_devices = await service.get_virtual_devices()
        except EdgeXError as exc:
            virtual_devices = VirtualDeviceCollection(
                projection_enabled=True,
                generated_at=now,
                observation_time=now,
                config_revision="",
                observation_error=ProjectionError(
                    code="authority_inventory_unavailable",
                    upstream="edgex",
                    operation=exc.operation,
                    identity=exc.identity[:128] if exc.identity else None,
                    retryable=exc.retryable,
                    status_code=exc.status_code,
                ),
            )
    try:
        profile_state = await service.get_resource_profile_state(refresh=refresh)
    except httpx.HTTPError:
        profile_state = {}
    virtual_resources = build_virtual_resource_state(
        registry=RESOURCE_REGISTRY,
        service_resource_profiles=profile_state.get("service_resource_profiles") or [],
        nodes=service.get_nodes(),
        observation_error=profile_state.get("observation_error"),
    )
    return build_resource_pool_state(
        virtual_devices=virtual_devices,
        nodes=service.get_nodes(),
        virtual_resources=virtual_resources,
        service_resource_profiles=profile_state.get("service_resource_profiles") or [],
    )


@app.get("/state/virtual-resources/{resource_id}", response_model=VirtualResourceProfile)
async def get_virtual_resource(resource_id: str, refresh: bool = False) -> VirtualResourceProfile:
    state = await _virtual_resource_state(refresh=refresh)
    for resource in state.resources:
        if resource.id == resource_id:
            return resource
    raise HTTPException(status_code=404, detail="Virtual resource not found")


@app.get("/state/virtual-resources/{resource_id}/twin", response_model=VirtualResourceTwin)
async def get_virtual_resource_twin(resource_id: str, refresh: bool = False) -> VirtualResourceTwin:
    resource = await get_virtual_resource(resource_id=resource_id, refresh=refresh)
    return resource.twin


@app.get("/state/augmentation-resources", response_model=AugmentationResourceCrdState)
async def get_augmentation_resources() -> AugmentationResourceCrdState:
    return await augmentation_crds.get_augmentation_resources()


@app.get("/state/device-augmentations", response_model=DeviceAugmentationCrdState)
async def get_device_augmentations(namespace: str = "default") -> DeviceAugmentationCrdState:
    return await augmentation_crds.get_device_augmentations(namespace=namespace)


@app.get("/state/runtime-resource-augmentation", response_model=RuntimeAugmentationState)
async def get_runtime_resource_augmentation(refresh: bool = False, namespace: str = "default", mode: str = "observed") -> RuntimeAugmentationState:
    query = RuntimeAugmentationQuery(refresh=refresh, namespace=namespace, mode=mode)
    return await runtime_resource_augmentation_state(service=service, crds=augmentation_crds, query=query)


@app.post("/state/service-resource-profiles/record")
async def record_service_resource_profiles(
    window: str = Query(default="10m", pattern=r"^[1-9][0-9]*[smhdw]$"),
):
    return await service.record_service_resource_profiles(window=window)


def _projection_http_error(
    code: str,
    *,
    status_code: int,
    exc: Exception | None = None,
) -> None:
    detail = ProjectionError(
        code=code,
        upstream="edgex" if isinstance(exc, EdgeXError) else None,
        operation=exc.operation if isinstance(exc, EdgeXError) else None,
        identity=(
            exc.identity[:128]
            if isinstance(exc, EdgeXError) and exc.identity
            else None
        ),
        retryable=exc.retryable if isinstance(exc, EdgeXError) else False,
        status_code=exc.status_code if isinstance(exc, EdgeXError) else None,
    )
    raise HTTPException(status_code=status_code, detail=detail.model_dump())


def _authority_http_error(exc: EdgeXError) -> None:
    if exc.status_code in {401, 403}:
        _projection_http_error(
            "authority_access_denied", status_code=503, exc=exc
        )
    code = {
        "profile": "authority_profile_unavailable",
        "events": "authority_event_unavailable",
    }.get(exc.operation, "authority_inventory_unavailable")
    _projection_http_error(code, status_code=503, exc=exc)


@app.get("/state/virtual-devices", response_model=VirtualDeviceCollection)
async def get_global_virtual_devices() -> VirtualDeviceCollection:
    if not settings.virtual_device_projection_enabled:
        now = datetime.now(timezone.utc)
        return VirtualDeviceCollection(
            projection_enabled=False,
            generated_at=now,
            observation_time=now,
            config_revision="",
        )
    try:
        return await service.get_virtual_devices()
    except EdgeXError as exc:
        _authority_http_error(exc)


@app.get(
    "/state/virtual-devices/{virtual_device_id}",
    response_model=VirtualDeviceView,
)
async def get_global_virtual_device(virtual_device_id: str) -> VirtualDeviceView:
    if not settings.virtual_device_projection_enabled:
        _projection_http_error("projection_not_active", status_code=404)
    try:
        item = await service.get_virtual_device(virtual_device_id)
    except EdgeXError as exc:
        _authority_http_error(exc)
    if item is None:
        _projection_http_error(
            "virtual_device_not_configured", status_code=404
        )
    return item

@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> PlainTextResponse:
    payload = render_metrics(
        node_states=service.get_nodes(),
        workflow_states=service.get_workflows(),
        summary=service.get_summary(),
        projection_observation=service._projection_observation,
        projection_enabled=settings.virtual_device_projection_enabled,
        device_snapshot=service.device_snapshot_diagnostics(),
    )
    return PlainTextResponse(
        content=payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

def create_app(
    injected_settings: Settings,
    *,
    dependencies: dict[str, object] | None = None,
) -> FastAPI:
    """Build an injectable projection boundary without changing the default app."""
    dependencies = dependencies or {}
    injected_service = dependencies.get("service")
    if not isinstance(injected_service, StateAggregatorService):
        injected_service = StateAggregatorService(
            injected_settings,
            edgex=dependencies.get("edgex"),
            clock=dependencies.get("clock"),
        )

    @asynccontextmanager
    async def injected_lifespan(application: FastAPI):
        if injected_settings.virtual_device_projection_enabled:
            if injected_service.bindings is None:
                path = injected_settings.virtual_device_bindings_path
                if path is None:
                    raise BindingConfigError("virtual-device bindings path is required")
                injected_service.bindings = load_virtual_device_bindings(
                    path,
                    allow_empty_for_tests=bool(dependencies.get("allow_empty_bindings")),
                )
        await injected_service.start()
        try:
            yield
        finally:
            await injected_service.stop()

    injected_app = FastAPI(
        title="state-aggregator",
        version="0.1.0",
        lifespan=injected_lifespan,
    )


    @injected_app.get("/state/virtual-devices", response_model=VirtualDeviceCollection)
    async def get_virtual_devices() -> VirtualDeviceCollection:
        if not injected_settings.virtual_device_projection_enabled:
            now = datetime.now(timezone.utc)
            return VirtualDeviceCollection(
                projection_enabled=False,
                generated_at=now,
                observation_time=now,
                config_revision="",
            )
        try:
            return await injected_service.get_virtual_devices()
        except EdgeXError as exc:
            _authority_http_error(exc)

    @injected_app.get(
        "/state/virtual-devices/{virtual_device_id}",
        response_model=VirtualDeviceView,
    )
    async def get_virtual_device(virtual_device_id: str) -> VirtualDeviceView:
        if not injected_settings.virtual_device_projection_enabled:
            _projection_http_error("projection_not_active", status_code=404)
        try:
            item = await injected_service.get_virtual_device(virtual_device_id)
        except EdgeXError as exc:
            _authority_http_error(exc)
        if item is None:
            _projection_http_error(
                "virtual_device_not_configured", status_code=404
            )
        return item

    @injected_app.get("/metrics", response_class=PlainTextResponse)
    async def injected_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            content=render_metrics(
                node_states=injected_service.get_nodes(),
                workflow_states=injected_service.get_workflows(),
                summary=injected_service.get_summary(),
                projection_observation=injected_service._projection_observation,
                projection_enabled=injected_settings.virtual_device_projection_enabled,
                device_snapshot=injected_service.device_snapshot_diagnostics(),
            ),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return injected_app

@app.post("/internal/refresh")
async def refresh_nodes():
    return await service.refresh_nodes()
