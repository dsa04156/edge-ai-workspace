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
from .augmentation_crds import (
    AugmentationCrdReader,
    AugmentationResourceCrdState,
    DeviceAugmentationCrdState,
)
from .config import Settings
from .connection_management import ConnectionManagementService
from .device_discovery import DeviceDiscoveryManagementService
from .device_management import DeviceManagementService
from .device_management_api import create_device_management_router
from .device_management_edgex import EdgeXManagementClient, EdgeXManagementError
from .edgex import EdgeXError
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
from .resource_pool import (
    PoolCategory,
    PoolStatus,
    ResourcePoolPlan,
    ResourcePoolPlanRequest,
    ResourcePoolState,
    build_resource_pool_plan,
    build_resource_pool_state,
)
from .runtime_augmentation import RuntimeAugmentationState
from .runtime_augmentation_api import (
    RuntimeAugmentationQuery,
    runtime_resource_augmentation_state,
)
from .service import StateAggregatorService
from .service_augmentation import (
    ServiceAugmentationEvaluator,
    ServiceAugmentationState,
    build_service_augmentation_signals,
    select_server1_candidate,
)
from .service_catalog import ServiceCatalog
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
service_augmentation_evaluator = ServiceAugmentationEvaluator()
service_catalog = ServiceCatalog.load(settings.service_catalog_path)
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
        return await service_demo_client.get_state()
    except ServiceDemoError as exc:
        return degraded_service_demo_state(exc)


@app.get(
    "/state/service-demo/augmentation",
    response_model=ServiceAugmentationState,
)
async def get_service_demo_augmentation(
    refresh: bool = False,
) -> ServiceAugmentationState:
    observed_at = datetime.now(timezone.utc)
    demo = await get_service_demo()
    try:
        resource_state = await service.get_resource_profile_state(refresh=refresh)
    except httpx.HTTPError:
        resource_state = {}
    profiles = resource_state.get("service_resource_profiles")
    profile = next(
        (
            item
            for item in profiles if isinstance(item, dict)
            and item.get("service") == "sensor-anomaly-demo"
        ),
        None,
    ) if isinstance(profiles, list) else None
    resource_state = await augmentation_crds.get_augmentation_resources()
    candidate = select_server1_candidate(resource_state.resources)
    source_node = next(
        (
            node
            for node in service.get_nodes()
            if node.hostname.casefold() == demo.binding.node.casefold()
        ),
        None,
    )
    source_gpu_ratio = None
    if source_node is not None:
        gpu_values = [
            source_node.raw_metrics.get("gpu_utilization"),
            source_node.raw_metrics.get("gpu_memory_usage_ratio"),
        ]
        observed_gpu_values = [
            float(value)
            for value in gpu_values
            if isinstance(value, int | float)
        ]
        if observed_gpu_values:
            source_gpu_ratio = max(observed_gpu_values)
    signals = build_service_augmentation_signals(
        demo,
        profile,
        candidate,
        now=observed_at,
        source_gpu_ratio=source_gpu_ratio,
    )
    return service_augmentation_evaluator.evaluate(signals, now=observed_at)


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


async def _resource_pool_state(
    *,
    refresh: bool = False,
    search: str | None = None,
    category: PoolCategory | None = None,
    status: PoolStatus | None = None,
) -> ResourcePoolState:
    observation_errors: list[str] = []
    try:
        devices = await service.get_devices()
    except EdgeXError as exc:
        devices = []
        observation_errors.append(
            f"EdgeX device observation unavailable: {exc.__class__.__name__}"
        )

    service_observations: dict[str, PoolStatus] = {}
    service_bindings: dict[str, list[str]] = {}
    try:
        demo_state = await service_demo_client.get_state()
        service_bindings["sensor-anomaly-demo"] = demo_state.binding.devices
        service_observations["sensor-anomaly-demo"] = (
            "ready"
            if demo_state.mode == "live"
            and demo_state.input_state == "fresh"
            and demo_state.model_state == "ready"
            else "degraded"
        )
    except ServiceDemoError as exc:
        service_observations["sensor-anomaly-demo"] = "unavailable"
        observation_errors.append(
            f"AI service observation unavailable: {exc.__class__.__name__}"
        )

    virtual_resources = await _virtual_resource_state(refresh=refresh)
    return build_resource_pool_state(
        devices=devices,
        virtual_resources=virtual_resources,
        nodes=service.get_nodes(),
        service_observations=service_observations,
        service_bindings=service_bindings,
        observation_errors=observation_errors,
        search=search,
        category=category,
        status=status,
    )


@app.get("/state/resource-pool", response_model=ResourcePoolState)
async def get_resource_pool(
    refresh: bool = False,
    q: str | None = Query(default=None, max_length=120),
    category: PoolCategory | None = None,
    status: PoolStatus | None = None,
) -> ResourcePoolState:
    return await _resource_pool_state(
        refresh=refresh,
        search=q,
        category=category,
        status=status,
    )


@app.post("/state/resource-pool/plan", response_model=ResourcePoolPlan)
async def preview_resource_pool_plan(
    request: ResourcePoolPlanRequest,
) -> ResourcePoolPlan:
    state = await _resource_pool_state()
    return build_resource_pool_plan(request, state)


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
