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
from .adapter_catalog import AdapterCatalog
from .adapter_controller_client import AdapterControllerClient
from .adapter_runtime_service import AdapterRuntimeManagementService
from .connection_management import ConnectionManagementService
from .device_management import DeviceManagementService
from .device_management_api import create_device_management_router
from .device_management_edgex import EdgeXManagementClient
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
)
from .operator_assistant import degraded_operator_chat_response, operator_assistant_from_dashboard
from .runtime_augmentation import RuntimeAugmentationState
from .runtime_augmentation_api import RuntimeAugmentationQuery, runtime_resource_augmentation_state
from .service_demo import (
    ServiceDemoClient,
    ServiceDemoError,
    degraded_service_demo_state,
)
from .service_demo_models import ServiceDemoState
from .service import StateAggregatorService
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
service_demo_client = ServiceDemoClient(
    settings.sensor_anomaly_demo_url,
    settings.sensor_anomaly_demo_timeout_seconds,
)
management_catalog = AdapterCatalog.load(settings.adapter_catalog_path)
management_client = EdgeXManagementClient(
    settings.edgex_core_metadata_url,
    settings.edgex_timeout_seconds,
)
management_service = DeviceManagementService(
    management_catalog,
    management_client,
    service.edgex,
    hmac_key=settings.device_management_hmac_key or "disabled-management",
    operation_limit=settings.device_management_operation_limit,
)
runtime_management_service = None
connection_management_service = None
if settings.adapter_runtime_management_enabled:
    if not settings.adapter_controller_internal_hmac_key:
        raise ValueError(
            "Adapter Controller internal HMAC key is required when runtime management is enabled"
        )
    adapter_controller_client = AdapterControllerClient(
        settings.adapter_controller_url,
        settings.adapter_controller_internal_hmac_key,
        settings.adapter_controller_timeout_seconds,
    )
    runtime_management_service = AdapterRuntimeManagementService(
        adapter_controller_client,
        management_client,
    )
    connection_management_service = ConnectionManagementService(
        runtime_management_service,
        management_service,
        hmac_key=(
            settings.device_management_hmac_key
            or settings.adapter_controller_internal_hmac_key
        ),
        operation_limit=settings.device_management_operation_limit,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await service.start()
    yield
    await service.stop()


app = FastAPI(title="state-aggregator", version="0.1.0", lifespan=lifespan)
app.include_router(
    create_device_management_router(
        settings,
        management_service,
        runtime_service=runtime_management_service,
        connection_service=connection_management_service,
    )
)
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


@app.get("/state/service-demo", response_model=ServiceDemoState)
async def get_service_demo() -> ServiceDemoState:
    try:
        return await service_demo_client.get_state()
    except ServiceDemoError as exc:
        return degraded_service_demo_state(exc)


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


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics() -> PlainTextResponse:
    payload = render_metrics(
        node_states=service.get_nodes(),
        workflow_states=service.get_workflows(),
        summary=service.get_summary(),
    )
    return PlainTextResponse(
        content=payload,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/internal/refresh")
async def refresh_nodes():
    return await service.refresh_nodes()
# trigger cds
