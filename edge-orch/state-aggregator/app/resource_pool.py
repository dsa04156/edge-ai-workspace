from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import NodeState, VirtualDeviceCollection, VirtualDeviceView
from .virtual_resources import JsonMap, VirtualResourceProfile, VirtualResourceState


ResourceClass = Literal["data_source", "node_diagnostic", "runtime_candidate", "service"]
PoolStatus = Literal["verified", "partial", "declared", "unavailable"]
EvidenceState = Literal["verified", "partial", "missing", "not_applicable"]


class ResourceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["definition", "runtime", "endpoint", "binding"]
    state: EvidenceState
    detail: str


class ResourcePoolItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    resource_class: ResourceClass
    kind: str
    status: PoolStatus
    selectable: bool = False
    authority: str
    location: str | None = None
    role: str
    capabilities: list[str] = Field(default_factory=list)
    evidence: list[ResourceEvidence] = Field(default_factory=list)
    status_reason: str


class ResourcePoolSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_sources: int
    ready_data_sources: int
    node_diagnostics: int
    runtime_candidates: int
    verified_candidates: int
    attention_candidates: int
    declared_candidates: int
    services: int


class ResourcePoolState(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    scope: str = "resource_pool_evidence_v1"
    summary: ResourcePoolSummary
    resources: list[ResourcePoolItem] = Field(default_factory=list)
    observation_errors: list[str] = Field(default_factory=list)


def build_resource_pool_state(
    *,
    virtual_devices: VirtualDeviceCollection,
    nodes: list[NodeState],
    virtual_resources: VirtualResourceState,
    service_resource_profiles: list[JsonMap],
) -> ResourcePoolState:
    resources = [
        *(_data_source_resource(item) for item in virtual_devices.items),
        *(_node_diagnostic(node) for node in nodes),
        *(_runtime_candidate(item) for item in virtual_resources.resources),
        *_service_resources(service_resource_profiles, virtual_devices),
    ]
    data_sources = [item for item in resources if item.resource_class == "data_source"]
    candidates = [item for item in resources if item.resource_class == "runtime_candidate"]
    services = [item for item in resources if item.resource_class == "service"]
    errors: list[str] = []
    if virtual_devices.observation_error is not None:
        errors.append(f"EdgeX projection: {virtual_devices.observation_error.code}")
    if virtual_resources.observation_error:
        errors.append(virtual_resources.observation_error)
    return ResourcePoolState(
        generated_at=datetime.now(timezone.utc),
        resources=resources,
        observation_errors=errors,
        summary=ResourcePoolSummary(
            data_sources=len(data_sources),
            ready_data_sources=sum(item.status == "verified" for item in data_sources),
            node_diagnostics=sum(item.resource_class == "node_diagnostic" for item in resources),
            runtime_candidates=len(candidates),
            verified_candidates=sum(item.status == "verified" and item.selectable for item in candidates),
            attention_candidates=sum(item.status in {"partial", "unavailable"} for item in candidates),
            declared_candidates=sum(item.status == "declared" for item in candidates),
            services=len(services),
        ),
    )


def _data_source_resource(item: VirtualDeviceView) -> ResourcePoolItem:
    required_inputs = [
        input_
        for capability in item.capabilities
        for input_ in capability.inputs
        if input_.required
    ]
    inputs_ready = bool(required_inputs) and all(input_.ready for input_ in required_inputs)
    profile_ready = item.physical_device_ref.profile_resolved
    binding_ready = item.binding_status == "ready"
    status: PoolStatus = {
        "ready": "verified",
        "degraded": "partial",
        "unresolved": "declared",
    }[item.binding_status]
    return ResourcePoolItem(
        id=item.id,
        name=item.id,
        resource_class="data_source",
        kind="EdgeX virtual-device projection",
        status=status,
        selectable=binding_ready,
        authority="EdgeX Core Metadata · Core Data",
        location=item.physical_device_ref.node_name,
        role="서비스 입력 데이터",
        capabilities=[capability.id for capability in item.capabilities],
        evidence=[
            ResourceEvidence(stage="definition", state="verified", detail=f"바인딩 설정 {item.config_revision[:12] or '로드됨'}"),
            ResourceEvidence(
                stage="runtime",
                state="verified" if profile_ready else "missing",
                detail="EdgeX Device/Profile 확인" if profile_ready else "EdgeX Device/Profile 미확인",
            ),
            ResourceEvidence(
                stage="endpoint",
                state="verified" if inputs_ready else "partial",
                detail="필수 Core Data Reading 최신" if inputs_ready else "필수 Reading 누락 또는 stale",
            ),
            ResourceEvidence(
                stage="binding",
                state="verified" if binding_ready else "partial",
                detail=f"읽기 전용 바인딩: {item.binding_status}",
            ),
        ],
        status_reason="입력·최신 이벤트·서비스 바인딩이 확인됨" if binding_ready else "EdgeX 입력 증거 일부를 확인해야 함",
    )


def _node_diagnostic(node: NodeState) -> ResourcePoolItem:
    ready = node.node_health in {"available", "healthy"}
    return ResourcePoolItem(
        id=f"node:{node.hostname}",
        name=node.hostname,
        resource_class="node_diagnostic",
        kind=node.node_type or "Kubernetes node",
        status="verified" if ready else "unavailable",
        selectable=False,
        authority="Kubernetes 노드 진단",
        location=node.hostname,
        role="배치·용량 진단 (바인딩 자원 아님)",
        capabilities=[],
        evidence=[
            ResourceEvidence(stage="definition", state="verified", detail="Kubernetes Node 확인"),
            ResourceEvidence(stage="runtime", state="verified" if ready else "missing", detail=f"노드 상태: {node.node_health}"),
            ResourceEvidence(stage="endpoint", state="not_applicable", detail="노드 상태는 서비스 endpoint 증거가 아님"),
            ResourceEvidence(stage="binding", state="not_applicable", detail="물리 디바이스 availability gate로 사용하지 않음"),
        ],
        status_reason="노드 상태 관측 정상" if ready else "Kubernetes 노드 상태 확인 필요",
    )


def _runtime_candidate(item: VirtualResourceProfile) -> ResourcePoolItem:
    runtime_state: EvidenceState = "missing"
    if item.observed_instances:
        runtime_state = "verified" if item.twin.pod_ready else "partial"
    endpoint_state: EvidenceState = "verified" if item.twin.endpoint_ready else "missing"
    binding_state: EvidenceState = (
        "verified"
        if item.twin.binding_state in {"available", "allocated", "partial"}
        else "missing"
    )
    if item.status == "configured_not_running":
        status: PoolStatus = "declared"
    elif item.status == "idle":
        status = "verified"
    elif item.status == "unavailable":
        status = "unavailable"
    else:
        status = "partial"
    return ResourcePoolItem(
        id=item.id,
        name=item.display_name,
        resource_class="runtime_candidate",
        kind=item.resource_type,
        status=status,
        selectable=item.status == "idle",
        authority="state-aggregator 자원 registry · Kubernetes 실행 증거",
        location=item.node,
        role="검증된 경우에만 실행 후보",
        capabilities=item.capabilities,
        evidence=[
            ResourceEvidence(stage="definition", state="verified", detail=f"자원 정의 확인: {item.id}"),
            ResourceEvidence(stage="runtime", state=runtime_state, detail=f"ID 일치 Ready Pod: {sum(instance.runtime_ready for instance in item.instances)}/{item.desired_instances}"),
            ResourceEvidence(stage="endpoint", state=endpoint_state, detail="Ready Service endpoint 확인" if item.twin.endpoint_ready else "Ready Service endpoint 미확인"),
            ResourceEvidence(stage="binding", state=binding_state, detail=f"바인딩 상태: {item.twin.binding_state}"),
        ],
        status_reason={
            "configured_not_running": "정의는 있으나 일치하는 런타임이 없음",
            "idle": "실행·엔드포인트·free 바인딩 증거 확인",
            "allocated": "확인된 인스턴스가 이미 바인딩됨",
            "partially_available": "free와 allocated 인스턴스가 함께 있음",
            "degraded": "런타임 또는 엔드포인트 증거가 불완전함",
            "unavailable": "실행 노드가 Ready 상태가 아님",
            "unknown": "바인딩 상태 증거가 없음",
        }[item.status],
    )


def _service_resources(
    profiles: list[JsonMap],
    virtual_devices: VirtualDeviceCollection,
) -> list[ResourcePoolItem]:
    bound_service_ids = {
        item.ai_service_ref.service_id
        for item in virtual_devices.items
        if item.binding_status == "ready"
    }
    resources: list[ResourcePoolItem] = []
    for profile in profiles:
        namespace = str(profile.get("namespace") or "default")
        name = str(profile.get("service") or "unknown")
        containers = profile.get("containers") or []
        endpoint_ready = bool(containers) and all(
            isinstance(container, dict) and container.get("endpoint_ready") is True
            for container in containers
        )
        pod_ready = bool(containers) and all(
            isinstance(container, dict) and container.get("pod_ready") is True
            for container in containers
        )
        bound = name in bound_service_ids
        status: PoolStatus = "verified" if pod_ready and endpoint_ready else "partial"
        resources.append(
            ResourcePoolItem(
                id=f"service:{namespace}:{name}",
                name=name,
                resource_class="service",
                kind="Kubernetes workload",
                status=status,
                selectable=False,
                authority="Kubernetes 워크로드 관측",
                location=", ".join(str(node) for node in profile.get("nodes") or []) or None,
                role="실행 서비스 (자원 후보 아님)",
                capabilities=[],
                evidence=[
                    ResourceEvidence(stage="definition", state="verified", detail=f"{namespace}/{name}"),
                    ResourceEvidence(stage="runtime", state="verified" if pod_ready else "partial", detail=f"실행 Pod: {profile.get('pod_count') or 0}"),
                    ResourceEvidence(stage="endpoint", state="verified" if endpoint_ready else "missing", detail="Service endpoint 확인" if endpoint_ready else "Service endpoint 미확인"),
                    ResourceEvidence(stage="binding", state="verified" if bound else "partial", detail="ready virtual-device 바인딩 확인" if bound else "ready virtual-device 바인딩 미확인"),
                ],
                status_reason="실행 Pod와 endpoint 확인" if status == "verified" else "서비스 실행 증거 일부를 확인해야 함",
            )
        )
    return resources
