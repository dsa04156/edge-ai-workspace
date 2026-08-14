from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .adapter_catalog import AdapterCatalog
from .adapter_controller_client import AdapterControllerClient
from .adapter_runtime_service import AdapterRuntimeManagementService
from .config import Settings
from .connection_management import ConnectionManagementService
from .device_discovery import DeviceDiscoveryManagementService
from .device_management import DeviceManagementService
from .device_management_api import create_device_management_router
from .device_management_edgex import EdgeXManagementClient, EdgeXManagementError
from .device_twins import DeviceTwinState, build_device_twin_state
from .edgex import EdgeXError
from .json_types import JsonMap
from .metrics import render_metrics
from .models import (
    CostModelState,
    DashboardState,
    DeviceProfileContract,
    DeviceResourceContract,
    DeviceState,
    OperatorAssistantState,
    OperatorChatRequest,
    OperatorChatResponse,
    SummaryState,
    TelemetryPoint,
    WorkflowEvent,
    WorkflowState,
)
from .operator_assistant import (
    degraded_operator_chat_response,
    operator_assistant_from_dashboard,
)
from .service import StateAggregatorService
from .service_catalog import ServiceCatalog
from .service_augmentation import (
    ServiceAugmentationEvaluator,
    build_service_augmentation_signals,
)
from .service_demo import (
    ServiceDemoClient,
    ServiceDemoError,
    degraded_service_demo_alerts,
    degraded_service_demo_results,
    degraded_service_demo_state,
)
from .service_demo_models import (
    DeployedServiceItem,
    DeployedServiceState,
    ServiceDemoAlertState,
    ServiceDemoResultState,
    ServiceDemoState,
)

settings = Settings()
service = StateAggregatorService(settings)
service_demo_client = ServiceDemoClient(
    settings.sensor_anomaly_demo_url,
    settings.sensor_anomaly_demo_timeout_seconds,
)
service_catalog = ServiceCatalog.load(settings.service_catalog_path)
service_augmentation_evaluator = ServiceAugmentationEvaluator()
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
device_discovery_management_service = None
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
    if settings.device_discovery_management_enabled:
        device_discovery_management_service = DeviceDiscoveryManagementService(
            adapter_controller_client
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
        discovery_service=device_discovery_management_service,
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


def _device_profile_contract(profile: JsonMap) -> DeviceProfileContract:
    resources: list[DeviceResourceContract] = []
    raw_resources = profile.get("deviceResources")
    if isinstance(raw_resources, list):
        for raw_resource in raw_resources:
            if not isinstance(raw_resource, dict):
                continue
            name = raw_resource.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            properties = raw_resource.get("properties")
            if not isinstance(properties, dict):
                properties = {}
            value_type = properties.get("valueType")
            read_write = properties.get("readWrite")
            units = properties.get("units")
            resources.append(
                DeviceResourceContract(
                    name=name.strip(),
                    description=(
                        str(raw_resource.get("description")).strip() or None
                        if raw_resource.get("description") is not None
                        else None
                    ),
                    value_type=(
                        value_type.strip()
                        if isinstance(value_type, str) and value_type.strip()
                        else "Unknown"
                    ),
                    read_write=(
                        read_write.strip()
                        if isinstance(read_write, str) and read_write.strip()
                        else "R"
                    ),
                    units=(
                        units.strip()
                        if isinstance(units, str) and units.strip()
                        else None
                    ),
                )
            )
    labels = profile.get("labels")
    return DeviceProfileContract(
        name=str(profile.get("name") or "").strip(),
        description=str(profile.get("description") or "").strip() or None,
        manufacturer=str(profile.get("manufacturer") or "").strip() or None,
        model=str(profile.get("model") or "").strip() or None,
        labels=(
            [item.strip() for item in labels if isinstance(item, str) and item.strip()]
            if isinstance(labels, list)
            else []
        ),
        resources=resources,
    )


@app.get("/state/device-profiles", response_model=list[DeviceProfileContract])
async def get_device_profiles() -> list[DeviceProfileContract]:
    try:
        profiles = await management_client.list_profiles()
    except EdgeXManagementError as exc:
        raise HTTPException(
            status_code=502,
            detail="EdgeX Device Profile 계약을 조회할 수 없습니다.",
        ) from exc
    contracts = [
        _device_profile_contract(profile)
        for profile in profiles
        if isinstance(profile, dict) and str(profile.get("name") or "").strip()
    ]
    return sorted(contracts, key=lambda profile: profile.name.casefold())


@app.get("/state/service-demo", response_model=ServiceDemoState)
async def get_service_demo() -> ServiceDemoState:
    try:
        demo = await service_demo_client.get_state()
    except ServiceDemoError as exc:
        demo = degraded_service_demo_state(exc)
    try:
        resource_state = await service.get_resource_profile_state()
        profiles = resource_state.get("service_resource_profiles") or []
    except Exception:
        profiles = []
    source_profile = next(
        (
            profile
            for profile in profiles
            if profile.get("namespace") == "edgex-edge"
            and profile.get("service") == "sensor-anomaly-demo"
        ),
        None,
    )
    candidate_profile = next(
        (
            profile
            for profile in profiles
            if profile.get("namespace") == "edgex-edge"
            and profile.get("service") == "sensor-anomaly-inference-server1"
        ),
        None,
    )
    candidate_ready = bool(
        candidate_profile
        and int(candidate_profile.get("ready_pod_count") or 0) > 0
    )
    signals = build_service_augmentation_signals(
        demo,
        source_profile,
        candidate_ready=candidate_ready,
    )
    return demo.model_copy(
        update={"augmentation": service_augmentation_evaluator.evaluate(signals)}
    )


def _deployed_service_state(demo: ServiceDemoState) -> DeployedServiceState:
    descriptor = service_catalog.require("sensor-anomaly-demo")
    model_version = demo.model.version if demo.model is not None else None
    if model_version is None and demo.latest is not None:
        model_version = demo.latest.model_version
    vibration_model = demo.model.components.get("vibration") if demo.model else None
    temperature_model = demo.model.components.get("temperature") if demo.model else None
    weights = demo.model.weights if demo.model else None
    design_contract = descriptor.design_contract.model_copy(
        update={
            "pipeline_algorithm": (
                demo.model.algorithm
                if demo.model is not None
                else descriptor.design_contract.pipeline_algorithm
            ),
            "vibration_algorithm": (
                vibration_model.algorithm
                if vibration_model is not None
                else descriptor.design_contract.vibration_algorithm
            ),
            "temperature_algorithm": (
                temperature_model.algorithm
                if temperature_model is not None
                else descriptor.design_contract.temperature_algorithm
            ),
            "warmup_samples": (
                demo.model.warmup_samples
                if demo.model is not None
                else descriptor.design_contract.warmup_samples
            ),
            "threshold": (
                demo.model.threshold
                if demo.model is not None
                else descriptor.design_contract.threshold
            ),
            "vibration_weight": (
                weights.vibration
                if weights is not None
                else descriptor.design_contract.vibration_weight
            ),
            "temperature_weight": (
                weights.temperature
                if weights is not None
                else descriptor.design_contract.temperature_weight
            ),
        }
    )
    current_service = DeployedServiceItem(
        service_id=descriptor.service_id,
        display_name=descriptor.display_name,
        description=descriptor.description,
        category=descriptor.category,
        lifecycle=descriptor.lifecycle,
        execution_mode=descriptor.execution_mode,
        mode=demo.mode,
        status=demo.status,
        input_state=demo.input_state,
        model_state=demo.model_state,
        node=demo.binding.node,
        physical_source=demo.binding.physical_source,
        device_service=demo.binding.device_service,
        input_devices=demo.binding.devices,
        model_version=model_version,
        latest_observed_at=(
            demo.latest.observed_at if demo.latest is not None else None
        ),
        inference_target=(
            demo.latest.inference_target
            if demo.latest is not None
            else demo.inference_routing.effective_target
        ),
        observation_error=demo.observation_error,
        design_contract=design_contract,
        catalog_version=service_catalog.version,
        definition_source=service_catalog.source,
        descriptor=descriptor.model_dump(
            exclude={"design_contract"},
            by_alias=True,
        ),
    )
    catalog_only_services = [
        DeployedServiceItem(
            service_id=item.service_id,
            display_name=item.display_name,
            description=item.description,
            category=item.category,
            lifecycle=item.lifecycle,
            execution_mode=item.execution_mode,
            mode="unavailable",
            status="degraded",
            input_state="unobserved",
            model_state="unobserved",
            node=next(
                (
                    target.node
                    for target in item.graph.targets
                    if target.slot == "Device1"
                ),
                "unobserved",
            ),
            physical_source="unobserved",
            device_service="unobserved",
            input_devices=[
                binding.device_name for binding in item.design_contract.inputs
            ],
            observation_error="service runtime adapter is not connected",
            design_contract=item.design_contract,
            catalog_version=service_catalog.version,
            definition_source=service_catalog.source,
            descriptor=item.model_dump(exclude={"design_contract"}, by_alias=True),
        )
        for item in service_catalog.services
        if item.service_id != descriptor.service_id
    ]
    return DeployedServiceState(
        generated_at=datetime.now(timezone.utc),
        services=[current_service, *catalog_only_services],
    )


@app.get("/state/services", response_model=DeployedServiceState)
async def get_deployed_services() -> DeployedServiceState:
    return _deployed_service_state(await get_service_demo())


@app.get("/state/services/{service_id}", response_model=DeployedServiceItem)
async def get_deployed_service(service_id: str) -> DeployedServiceItem:
    deployed = _deployed_service_state(await get_service_demo())
    match = next(
        (item for item in deployed.services if item.service_id == service_id),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="service is not registered")
    return match


@app.get("/state/service-demo/results", response_model=ServiceDemoResultState)
async def get_service_demo_results(
    limit: int = Query(default=100, ge=1, le=1_000),
    anomaly: bool | None = Query(default=None),
) -> ServiceDemoResultState:
    try:
        return await service_demo_client.get_results(
            limit=limit,
            anomaly=anomaly,
        )
    except ServiceDemoError as exc:
        return degraded_service_demo_results(exc)


@app.get("/state/service-demo/alerts", response_model=ServiceDemoAlertState)
async def get_service_demo_alerts(
    limit: int = Query(default=20, ge=1, le=100),
) -> ServiceDemoAlertState:
    try:
        return await service_demo_client.get_alerts(limit=limit)
    except ServiceDemoError as exc:
        return degraded_service_demo_alerts(exc)


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


@app.get("/state/device-twins", response_model=DeviceTwinState)
async def get_device_twins() -> DeviceTwinState:
    observation_errors: list[str] = []
    try:
        devices = await service.get_devices()
    except EdgeXError as exc:
        devices = []
        observation_errors.append(
            f"EdgeX device observation unavailable: {exc.__class__.__name__}"
        )

    try:
        demo_state = await service_demo_client.get_state()
    except ServiceDemoError as exc:
        demo_state = degraded_service_demo_state(exc)
        observation_errors.append(
            f"AI service observation unavailable: {exc.__class__.__name__}"
        )
    deployed_services = _deployed_service_state(demo_state)

    return build_device_twin_state(
        devices=devices,
        deployed_services=deployed_services.services,
        observation_errors=observation_errors,
    )


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
