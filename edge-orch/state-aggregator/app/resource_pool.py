from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import DeviceState, NodeState
from .virtual_resources import VirtualResourceState


PoolCategory = Literal["data", "compute", "service"]
PoolStatus = Literal["ready", "degraded", "unavailable", "configured"]


class ResourcePoolServiceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str
    lifecycle: Literal["deployed", "design_template"]
    input_capability_options: list[list[str]] = Field(default_factory=list)
    compute_capabilities: list[str] = Field(default_factory=list)
    workload_ref: dict[str, str] | None = None


SERVICE_CATALOG: tuple[ResourcePoolServiceDefinition, ...] = (
    ResourcePoolServiceDefinition(
        id="sensor-anomaly-demo",
        name="센서 이상 탐지",
        description="실측 센서 입력을 이용해 변화 기반 이상 점수를 제공하는 현재 서비스 데모",
        lifecycle="deployed",
        input_capability_options=[["vibration"], ["angular-velocity"]],
        workload_ref={
            "namespace": "edgex-edge",
            "kind": "Deployment",
            "name": "sensor-anomaly-demo",
        },
    ),
)


class ResourcePoolItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: PoolCategory
    kind: str
    name: str
    description: str
    status: PoolStatus
    authority: Literal["edgex", "kubernetes", "service_catalog"]
    source_endpoint: str
    node: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    selectable: bool = False
    current_bindings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourcePoolBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    service_id: str
    service_name: str
    data_resource_id: str
    data_resource_name: str
    status: Literal["ready", "degraded", "unresolved"]
    input_contract: str
    binding_mode: Literal["declarative_read_only"]
    workload_ref: dict[str, str] | None = None


class ResourcePoolSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_resources: int = 0
    visible_resources: int = 0
    ready_resources: int = 0
    data_resources: int = 0
    compute_resources: int = 0
    service_resources: int = 0
    active_bindings: int = 0


class ResourcePoolQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    search: str | None = None
    category: PoolCategory | None = None
    status: PoolStatus | None = None


class ResourcePoolState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    reservation_mode: Literal["dry_run"] = "dry_run"
    authority_policy: str = "edgex_physical_kubernetes_compute"
    query: ResourcePoolQuery = Field(default_factory=ResourcePoolQuery)
    summary: ResourcePoolSummary
    resources: list[ResourcePoolItem] = Field(default_factory=list)
    bindings: list[ResourcePoolBinding] = Field(default_factory=list)
    observation_errors: list[str] = Field(default_factory=list)


class ResourcePoolPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_id: str = Field(min_length=1, max_length=120)
    data_resource_id: str | None = Field(default=None, max_length=180)
    compute_resource_id: str | None = Field(default=None, max_length=180)


class ResourcePoolPlanCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    label: str
    status: Literal["pass", "fail", "not_required"]
    detail: str


class ResourcePoolPlanSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str
    service_name: str
    data_resource_id: str | None = None
    data_resource_name: str | None = None
    compute_resource_id: str | None = None
    compute_resource_name: str | None = None


class ResourcePoolLeasePreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    state: Literal["preview"] = "preview"
    persisted: Literal[False] = False
    expires_at: datetime


class ResourcePoolPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    mode: Literal["dry_run"] = "dry_run"
    compatible: bool
    selection: ResourcePoolPlanSelection
    checks: list[ResourcePoolPlanCheck]
    lease_preview: ResourcePoolLeasePreview | None = None
    execution_steps: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)


def build_resource_pool_state(
    *,
    devices: list[DeviceState],
    virtual_resources: VirtualResourceState,
    nodes: list[NodeState],
    services: tuple[ResourcePoolServiceDefinition, ...] = SERVICE_CATALOG,
    service_observations: dict[str, PoolStatus] | None = None,
    service_bindings: dict[str, list[str]] | None = None,
    observation_errors: list[str] | None = None,
    search: str | None = None,
    category: PoolCategory | None = None,
    status: PoolStatus | None = None,
) -> ResourcePoolState:
    device_by_name = {item.name: item for item in devices}
    bindings = [
        _binding_from_device(
            device_by_name.get(device_name),
            device_name=device_name,
            service=service,
        )
        for service in services
        for device_name in (service_bindings or {}).get(service.id, [])
    ]
    binding_service_by_device = {
        binding.data_resource_name: binding.service_id for binding in bindings
    }
    resources: list[ResourcePoolItem] = []
    resources.extend(
        _data_resource(item, binding_service_by_device.get(item.name)) for item in devices
    )
    resources.extend(_node_resource(node) for node in nodes)
    resources.extend(_compute_resource(item) for item in virtual_resources.resources)
    resources.extend(
        _service_resource(item, bindings, (service_observations or {}).get(item.id))
        for item in services
    )
    resources.sort(key=lambda item: (item.category, item.name.casefold(), item.id))

    query = ResourcePoolQuery(
        search=search.strip() if search and search.strip() else None,
        category=category,
        status=status,
    )
    visible = [item for item in resources if _matches_query(item, query)]
    summary = ResourcePoolSummary(
        total_resources=len(resources),
        visible_resources=len(visible),
        ready_resources=sum(item.status == "ready" for item in resources),
        data_resources=sum(item.category == "data" for item in resources),
        compute_resources=sum(item.category == "compute" for item in resources),
        service_resources=sum(item.category == "service" for item in resources),
        active_bindings=sum(item.status == "ready" for item in bindings),
    )
    errors = list(observation_errors or [])
    if virtual_resources.observation_error:
        errors.append(virtual_resources.observation_error)
    return ResourcePoolState(
        generated_at=datetime.now(timezone.utc),
        query=query,
        summary=summary,
        resources=visible,
        bindings=bindings,
        observation_errors=list(dict.fromkeys(errors)),
    )


def build_resource_pool_plan(
    request: ResourcePoolPlanRequest,
    state: ResourcePoolState,
    *,
    services: tuple[ResourcePoolServiceDefinition, ...] = SERVICE_CATALOG,
    now: datetime | None = None,
) -> ResourcePoolPlan:
    generated_at = now or datetime.now(timezone.utc)
    service_id = request.service_id.removeprefix("service:")
    definition = next((item for item in services if item.id == service_id), None)
    service_item = _find_item(state.resources, f"service:{service_id}")
    data_candidates = [item for item in state.resources if item.category == "data"]
    compute_candidates = [item for item in state.resources if item.category == "compute"]
    data_item = _select_item(request.data_resource_id, data_candidates)
    if request.data_resource_id is None and definition is not None:
        data_item = next(
            (
                item
                for item in data_candidates
                if item.status == "ready" and _input_compatible(item, definition)
            ),
            None,
        )
    compute_item = _select_item(request.compute_resource_id, compute_candidates)
    if request.compute_resource_id is None and definition and definition.compute_capabilities:
        compute_item = next(
            (
                item
                for item in compute_candidates
                if item.status == "ready"
                and set(definition.compute_capabilities).issubset(item.capabilities)
            ),
            None,
        )

    checks: list[ResourcePoolPlanCheck] = []
    checks.append(
        ResourcePoolPlanCheck(
            code="service_known",
            label="서비스 계약",
            status="pass" if definition and service_item else "fail",
            detail=(
                "서비스 카탈로그의 배포 계약을 확인했습니다."
                if definition and service_item
                else "요청한 서비스를 자원 풀에서 찾을 수 없습니다."
            ),
        )
    )
    service_ready = bool(service_item and service_item.status == "ready")
    checks.append(
        ResourcePoolPlanCheck(
            code="service_available",
            label="서비스 실행 상태",
            status="pass" if service_ready else "fail",
            detail=(
                "AI 서비스와 입력 상태가 현재 사용 가능합니다."
                if service_ready
                else "AI 서비스의 live 상태와 입력 준비를 먼저 확인해야 합니다."
            ),
        )
    )
    data_ok = bool(
        definition
        and data_item
        and data_item.status == "ready"
        and _input_compatible(data_item, definition)
    )
    checks.append(
        ResourcePoolPlanCheck(
            code="data_compatible",
            label="센서 입력 호환성",
            status="pass" if data_ok else "fail",
            detail=(
                f"{data_item.name}의 입력 capability와 최신 상태가 요구사항을 만족합니다."
                if data_ok and data_item
                else "ready 상태이며 입력 capability가 맞는 센서 데이터가 필요합니다."
            ),
        )
    )
    compute_required = bool(definition and definition.compute_capabilities)
    compute_ok = bool(
        not compute_required
        or (
            definition
            and compute_item
            and compute_item.status == "ready"
            and set(definition.compute_capabilities).issubset(compute_item.capabilities)
        )
    )
    checks.append(
        ResourcePoolPlanCheck(
            code="compute_compatible",
            label="컴퓨팅 자원",
            status=("pass" if compute_ok else "fail") if compute_required else "not_required",
            detail=(
                f"{compute_item.name}이 실행 요구사항을 만족합니다."
                if compute_required and compute_ok and compute_item
                else "현재 서비스는 고정 Deployment를 사용하므로 새 컴퓨팅 예약이 필요하지 않습니다."
                if not compute_required
                else "요구 capability를 제공하는 ready 컴퓨팅 자원이 없습니다."
            ),
        )
    )
    checks.append(
        ResourcePoolPlanCheck(
            code="mutation_guard",
            label="변경 안전 경계",
            status="pass",
            detail="이 계획은 EdgeX·Kubernetes를 변경하거나 자원을 점유하지 않습니다.",
        )
    )

    compatible = all(check.status != "fail" for check in checks)
    blocked_reasons = [check.detail for check in checks if check.status == "fail"]
    selection = ResourcePoolPlanSelection(
        service_id=service_id,
        service_name=definition.name if definition else service_id,
        data_resource_id=data_item.id if data_item else None,
        data_resource_name=data_item.name if data_item else None,
        compute_resource_id=compute_item.id if compute_item else None,
        compute_resource_name=compute_item.name if compute_item else None,
    )
    lease_preview = None
    if compatible:
        seed = "|".join(
            [service_id, selection.data_resource_id or "", selection.compute_resource_id or ""]
        )
        lease_preview = ResourcePoolLeasePreview(
            id=f"dryrun-{sha256(seed.encode('utf-8')).hexdigest()[:12]}",
            expires_at=generated_at + timedelta(minutes=15),
        )
    return ResourcePoolPlan(
        generated_at=generated_at,
        compatible=compatible,
        selection=selection,
        checks=checks,
        lease_preview=lease_preview,
        execution_steps=(
            [
                "EdgeX Core Metadata의 Device/Profile 계약을 다시 확인합니다.",
                "Core Data 최신 Reading의 타입·단위·freshness를 검증합니다.",
                "기존 고정 AI 서비스 입력 계약에 읽기 전용으로 연결합니다.",
                "운영자가 계획을 검토하며 실제 배포나 명령은 실행하지 않습니다.",
            ]
            if compatible
            else []
        ),
        blocked_reasons=blocked_reasons,
        guardrails=[
            "물리 디바이스 inventory·schema·telemetry 권위는 EdgeX입니다.",
            "노드·워크로드 상태 권위는 Kubernetes/KubeEdge입니다.",
            "예약 ID는 미리보기이며 서버에 저장되지 않습니다.",
            "Kubernetes apply/delete, EdgeX mutation, command, offloading은 수행하지 않습니다.",
        ],
    )


def _binding_from_device(
    item: DeviceState | None,
    *,
    device_name: str,
    service: ResourcePoolServiceDefinition,
) -> ResourcePoolBinding:
    status: Literal["ready", "degraded", "unresolved"] = "unresolved"
    if item is not None:
        status = "ready" if item.overall_status in {"available", "healthy"} else "degraded"
    return ResourcePoolBinding(
        id=f"binding:{service.id}:{device_name}",
        service_id=service.id,
        service_name=service.name,
        data_resource_id=f"data:{device_name}",
        data_resource_name=device_name,
        status=status,
        input_contract="okdong.pump-motor.telemetry/v1",
        binding_mode="declarative_read_only",
        workload_ref=service.workload_ref,
    )


def _device_capabilities(item: DeviceState) -> list[str]:
    terms = {
        item.name.casefold(),
        item.profile_name.casefold(),
        *(reading.resource_name.casefold() for reading in item.latest_readings),
        *(reading.source_name.casefold() for reading in item.latest_readings),
    }
    haystack = " ".join(sorted(terms))
    capabilities: set[str] = set()
    if any(token in haystack for token in ("acceleration", "vibration", "accelerometer")):
        capabilities.add("vibration")
    if any(token in haystack for token in ("angular", "gyroscope", "gyro")):
        capabilities.add("angular-velocity")
    if "temperature" in haystack or "temp" in haystack:
        capabilities.add("temperature")
    if "humidity" in haystack:
        capabilities.add("humidity")
    if "pressure" in haystack:
        capabilities.add("pressure")
    return sorted(capabilities)


def _data_resource(item: DeviceState, bound_service_id: str | None) -> ResourcePoolItem:
    capabilities = _device_capabilities(item)
    status: PoolStatus = {
        "available": "ready",
        "healthy": "ready",
        "degraded": "degraded",
        "unavailable": "unavailable",
    }[item.overall_status]
    return ResourcePoolItem(
        id=f"data:{item.name}",
        category="data",
        kind="edgex_device",
        name=item.name,
        description=(
            f"{item.profile_name} · Core Data {item.telemetry_freshness} · "
            f"{len(item.latest_readings)}개 최신 reading"
        ),
        status=status,
        authority="edgex",
        source_endpoint="/state/devices",
        node=item.node_name,
        capabilities=capabilities,
        selectable=status == "ready",
        current_bindings=[bound_service_id] if bound_service_id else [],
        metadata={
            "profile_name": item.profile_name,
            "device_service_name": item.device_service_name,
            "admin_state": item.admin_state,
            "operating_state": item.operating_state,
            "telemetry_freshness": item.telemetry_freshness,
            "latest_event_timestamp": (
                item.latest_event_timestamp.isoformat()
                if item.latest_event_timestamp is not None
                else None
            ),
            "reason": item.reason,
        },
    )


def _node_resource(node: NodeState) -> ResourcePoolItem:
    capabilities = ["cpu", "memory"]
    if any("gpu" in key.casefold() for key in node.raw_metrics):
        capabilities.append("gpu")
    status: PoolStatus = {
        "healthy": "ready",
        "available": "ready",
        "degraded": "degraded",
        "unavailable": "unavailable",
    }[node.node_health]
    return ResourcePoolItem(
        id=f"compute:node:{node.hostname}",
        category="compute",
        kind="edge_node",
        name=node.hostname,
        description=f"{node.node_type or 'edge node'} · CPU {node.compute_pressure} / memory {node.memory_pressure}",
        status=status,
        authority="kubernetes",
        source_endpoint="/state/nodes",
        node=node.hostname,
        capabilities=capabilities,
        selectable=status == "ready",
        metadata={
            "node_type": node.node_type,
            "compute_pressure": node.compute_pressure,
            "memory_pressure": node.memory_pressure,
            "network_pressure": node.network_pressure,
            "collected_at": node.collected_at.isoformat(),
        },
    )


def _compute_resource(item: Any) -> ResourcePoolItem:
    status: PoolStatus = {
        "idle": "ready",
        "partially_available": "ready",
        "allocated": "degraded",
        "degraded": "degraded",
        "unavailable": "unavailable",
        "unknown": "degraded",
        "configured_not_running": "configured",
    }[item.status]
    return ResourcePoolItem(
        id=f"compute:{item.id}",
        category="compute",
        kind=item.resource_type,
        name=item.display_name,
        description=f"{item.observed_instances}/{item.desired_instances} 인스턴스 관측 · {item.free_instances}개 사용 가능",
        status=status,
        authority="kubernetes",
        source_endpoint="/state/virtual-resources",
        node=item.node,
        capabilities=item.capabilities,
        selectable=status == "ready" and item.free_instances > 0,
        metadata={
            "desired_instances": item.desired_instances,
            "observed_instances": item.observed_instances,
            "free_instances": item.free_instances,
            "allocated_instances": item.allocated_instances,
            "supported_stage_types": item.supported_stage_types,
            "status_reason": item.twin.status_reason,
        },
    )


def _service_resource(
    item: ResourcePoolServiceDefinition,
    bindings: list[ResourcePoolBinding],
    observed_status: PoolStatus | None,
) -> ResourcePoolItem:
    service_bindings = [binding for binding in bindings if binding.service_id == item.id]
    inferred_status: PoolStatus = (
        "ready"
        if any(binding.status == "ready" for binding in service_bindings)
        else "degraded"
        if service_bindings
        else "configured"
    )
    status = observed_status or inferred_status
    return ResourcePoolItem(
        id=f"service:{item.id}",
        category="service",
        kind=item.lifecycle,
        name=item.name,
        description=item.description,
        status=status,
        authority="service_catalog",
        source_endpoint="/state/resource-pool",
        capabilities=sorted(
            {capability for option in item.input_capability_options for capability in option}
        ),
        selectable=True,
        current_bindings=[binding.id for binding in service_bindings],
        metadata={
            "service_id": item.id,
            "lifecycle": item.lifecycle,
            "input_capability_options": item.input_capability_options,
            "compute_capabilities": item.compute_capabilities,
            "workload_ref": item.workload_ref,
        },
    )


def _matches_query(item: ResourcePoolItem, query: ResourcePoolQuery) -> bool:
    if query.category and item.category != query.category:
        return False
    if query.status and item.status != query.status:
        return False
    if not query.search:
        return True
    needle = query.search.casefold()
    haystack = " ".join(
        [item.id, item.name, item.description, item.kind, item.node or "", *item.capabilities]
    ).casefold()
    return needle in haystack


def _find_item(resources: list[ResourcePoolItem], resource_id: str) -> ResourcePoolItem | None:
    return next((item for item in resources if item.id == resource_id), None)


def _select_item(
    resource_id: str | None,
    candidates: list[ResourcePoolItem],
) -> ResourcePoolItem | None:
    if not resource_id:
        return None
    normalized = resource_id if ":" in resource_id else f"data:{resource_id}"
    return _find_item(candidates, normalized)


def _input_compatible(
    resource: ResourcePoolItem,
    service: ResourcePoolServiceDefinition,
) -> bool:
    available = set(resource.capabilities)
    return any(set(option).issubset(available) for option in service.input_capability_options)


def _service_name(service_id: str) -> str:
    service = next((item for item in SERVICE_CATALOG if item.id == service_id), None)
    return service.name if service else service_id
