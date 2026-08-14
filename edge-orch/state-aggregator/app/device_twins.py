from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import DeviceState
from .service_demo_models import DeployedServiceItem


TwinHealth = Literal["ready", "degraded", "unavailable"]
BindingHealth = Literal["active", "degraded", "unavailable"]


class DeviceTwinBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_id: str
    service_name: str
    input_contract: str
    status: BindingHealth


class ObservedDeviceTwin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    physical_device_id: str
    node: str | None = None
    profile_name: str
    device_service_name: str
    observed_resources: list[str] = Field(default_factory=list)
    telemetry_freshness: Literal["fresh", "stale", "no_events"]
    health: TwinHealth
    reason: str
    latest_event_timestamp: datetime | None = None
    service_bindings: list[DeviceTwinBinding] = Field(default_factory=list)
    authority: Literal["edgex"] = "edgex"
    scope: Literal["observed_state"] = "observed_state"


class DeviceTwinSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    physical_devices: int = 0
    device_twins: int = 0
    service_bound_twins: int = 0
    service_connections: int = 0
    unbound_twins: int = 0
    attention_twins: int = 0


class DeviceTwinState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: datetime
    mode: Literal["read_only"] = "read_only"
    authority: Literal["edgex_metadata_and_core_data"] = "edgex_metadata_and_core_data"
    twin_scope: Literal["observed_state_not_control"] = "observed_state_not_control"
    summary: DeviceTwinSummary
    twins: list[ObservedDeviceTwin] = Field(default_factory=list)
    observation_errors: list[str] = Field(default_factory=list)


def build_device_twin_state(
    *,
    devices: list[DeviceState],
    deployed_services: list[DeployedServiceItem] | None = None,
    observation_errors: list[str] | None = None,
) -> DeviceTwinState:
    services_by_device: dict[str, list[DeployedServiceItem]] = {}
    for deployed_service in deployed_services or []:
        for device_name in set(deployed_service.input_devices):
            services_by_device.setdefault(device_name, []).append(deployed_service)
    twins = [
        _device_twin(
            device,
            deployed_services=services_by_device.get(device.name, []),
        )
        for device in devices
        if device.physical_device_id
    ]
    twins.sort(
        key=lambda twin: (
            not bool(twin.service_bindings),
            twin.physical_device_id.casefold(),
            twin.name.casefold(),
        )
    )
    return DeviceTwinState(
        generated_at=datetime.now(timezone.utc),
        summary=DeviceTwinSummary(
            physical_devices=len({twin.physical_device_id for twin in twins}),
            device_twins=len(twins),
            service_bound_twins=sum(bool(twin.service_bindings) for twin in twins),
            service_connections=sum(len(twin.service_bindings) for twin in twins),
            unbound_twins=sum(not twin.service_bindings for twin in twins),
            attention_twins=sum(twin.health != "ready" for twin in twins),
        ),
        twins=twins,
        observation_errors=list(dict.fromkeys(observation_errors or [])),
    )


def _device_twin(
    device: DeviceState,
    *,
    deployed_services: list[DeployedServiceItem],
) -> ObservedDeviceTwin:
    health: TwinHealth = {
        "available": "ready",
        "healthy": "ready",
        "degraded": "degraded",
        "unavailable": "unavailable",
    }[device.overall_status]
    resource_names = sorted(
        {reading.resource_name for reading in device.latest_readings if reading.resource_name}
    )
    bindings = [
        _service_binding(service, twin_health=health)
        for service in sorted(deployed_services, key=lambda item: item.service_id)
    ]
    return ObservedDeviceTwin(
        id=f"twin:{device.name}",
        name=device.name,
        physical_device_id=device.physical_device_id or "",
        node=device.node_name,
        profile_name=device.profile_name,
        device_service_name=device.device_service_name,
        observed_resources=resource_names,
        telemetry_freshness=device.telemetry_freshness,
        health=health,
        reason=device.reason,
        latest_event_timestamp=device.latest_event_timestamp,
        service_bindings=bindings,
    )


def _service_binding(
    service: DeployedServiceItem,
    *,
    twin_health: TwinHealth,
) -> DeviceTwinBinding:
    status: BindingHealth = (
        "active"
        if twin_health == "ready"
        and service.mode == "live"
        and service.status == "normal"
        and service.input_state == "fresh"
        and service.model_state == "ready"
        else "unavailable"
        if twin_health == "unavailable" or service.mode == "unavailable"
        else "degraded"
    )
    return DeviceTwinBinding(
        service_id=service.service_id,
        service_name=service.display_name,
        input_contract=_input_contract(service),
        status=status,
    )


def _input_contract(service: DeployedServiceItem) -> str:
    descriptor = service.descriptor if isinstance(service.descriptor, dict) else {}
    input_contract = descriptor.get("input_contract")
    if isinstance(input_contract, dict):
        schema = input_contract.get("schema")
        if isinstance(schema, str) and schema.strip():
            return schema.strip()
    if service.design_contract is not None:
        return service.design_contract.contract_id
    return "미지정"
