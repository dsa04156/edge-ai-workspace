from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from .augmentation_crds import AugmentationResourceCrdState, DeviceAugmentationCrdState
from .virtual_resources import JsonMap


SCENARIO_ID = "jetson-inspection-x86-gpu-cache-v1"
DEVICE_AUGMENTATION_ID = "jetson-gpu-storage-augmentation"
TARGET_DEVICE = "etri-dev0001-jetorn"
INFERENCE_RESOURCE = "vd-x86-gpu-inference"
STORAGE_RESOURCE = "vd-storage-cache"
DEFAULT_INPUT_SOURCE = "jetson-inspection-camera"

ExecutionStatus = Literal["not_run", "blocked", "succeeded", "failed"]


class AugmentationExecutionRequest(BaseModel):
    input_source: str = DEFAULT_INPUT_SOURCE
    payload: dict[str, Any] = Field(default_factory=dict)


class AugmentationValidationCheck(BaseModel):
    name: str
    status: Literal["pass", "fail"]
    detail: str


class AugmentationExecutionRecord(BaseModel):
    execution_id: str
    scenario_id: str = SCENARIO_ID
    status: ExecutionStatus
    triggered_at: datetime
    completed_at: datetime | None = None
    target_device: str = TARGET_DEVICE
    input_source: str = DEFAULT_INPUT_SOURCE
    target_endpoint: str | None = None
    target_resources: dict[str, str] = Field(default_factory=dict)
    latency_ms: int | None = None
    output_artifact: str | None = None
    error: str | None = None
    validation: list[AugmentationValidationCheck] = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)


class AugmentationExecutionState(BaseModel):
    generated_at: datetime
    mode: str = "manual_trigger"
    scope: str = "resource_augmentation_execution_v1"
    scenario_id: str = SCENARIO_ID
    last_execution: AugmentationExecutionRecord | None = None


class AugmentationExecutionRunner(Protocol):
    async def execute(self, payload: JsonMap) -> JsonMap: ...


class HttpAugmentationExecutionRunner:
    def __init__(self, endpoint_url: str, timeout_seconds: float) -> None:
        self.endpoint_url = endpoint_url
        self.timeout_seconds = timeout_seconds

    async def execute(self, payload: JsonMap) -> JsonMap:
        if not self.endpoint_url:
            raise RuntimeError("resource augmentation inference endpoint is not configured")
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.endpoint_url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"result": data}


class ResourceAugmentationExecutor:
    def __init__(
        self,
        runner: AugmentationExecutionRunner,
        target_endpoint: str | None = None,
    ) -> None:
        self.runner = runner
        self.target_endpoint = target_endpoint
        self.last_execution: AugmentationExecutionRecord | None = None

    def state(self) -> AugmentationExecutionState:
        return AugmentationExecutionState(
            generated_at=datetime.now(timezone.utc),
            last_execution=self.last_execution,
        )

    async def trigger(
        self,
        request: AugmentationExecutionRequest,
        resources: AugmentationResourceCrdState,
        device_augmentations: DeviceAugmentationCrdState,
    ) -> AugmentationExecutionState:
        validation = validate_execution_preconditions(resources, device_augmentations)
        target_resources = {"inference": INFERENCE_RESOURCE, "storage": STORAGE_RESOURCE}
        record = AugmentationExecutionRecord(
            execution_id=str(uuid.uuid4()),
            status="blocked",
            triggered_at=datetime.now(timezone.utc),
            input_source=request.input_source,
            target_endpoint=self.target_endpoint,
            target_resources=target_resources,
            validation=validation,
        )
        failures = [check.detail for check in validation if check.status == "fail"]
        if failures:
            record.completed_at = datetime.now(timezone.utc)
            record.error = "; ".join(failures)
            self.last_execution = record
            return self.state()

        payload: JsonMap = {
            "scenario_id": SCENARIO_ID,
            "device_augmentation": DEVICE_AUGMENTATION_ID,
            "target_device": TARGET_DEVICE,
            "input_source": request.input_source,
            "resources": target_resources,
            "payload": request.payload,
        }
        started = time.monotonic()
        try:
            response = await self.runner.execute(payload)
        except (httpx.HTTPError, RuntimeError) as exc:
            record.status = "failed"
            record.completed_at = datetime.now(timezone.utc)
            record.latency_ms = elapsed_ms(started)
            record.error = f"{exc.__class__.__name__}: {exc}"
            self.last_execution = record
            return self.state()

        record.status = "succeeded"
        record.completed_at = datetime.now(timezone.utc)
        record.latency_ms = response_latency_ms(response, elapsed_ms(started))
        record.output_artifact = output_artifact(response)
        record.response = response
        self.last_execution = record
        return self.state()


def validate_execution_preconditions(
    resources: AugmentationResourceCrdState,
    device_augmentations: DeviceAugmentationCrdState,
) -> list[AugmentationValidationCheck]:
    resource_map = {resource.name: resource for resource in resources.resources}
    binding_map = {binding.name: binding for binding in device_augmentations.device_augmentations}
    checks: list[AugmentationValidationCheck] = []

    for resource_id in (INFERENCE_RESOURCE, STORAGE_RESOURCE):
        resource = resource_map.get(resource_id)
        if resource is None:
            checks.append(fail(f"{resource_id} available", f"{resource_id} is missing"))
            continue
        if resource.phase != "Available":
            checks.append(fail(f"{resource_id} available", f"{resource_id} phase={resource.phase!r}"))
            continue
        if not resource.endpoint_ready:
            checks.append(fail(f"{resource_id} endpoint ready", f"{resource_id} endpoint is not ready"))
            continue
        checks.append(pass_check(f"{resource_id} available", "phase=Available and endpointReady=true"))

    binding = binding_map.get(DEVICE_AUGMENTATION_ID)
    if binding is None:
        checks.append(fail("device augmentation ready", f"{DEVICE_AUGMENTATION_ID} is missing"))
        return checks
    if binding.target_device_name != TARGET_DEVICE:
        checks.append(
            fail(
                "target device matches",
                f"{DEVICE_AUGMENTATION_ID} target_device_name={binding.target_device_name!r}",
            )
        )
    else:
        checks.append(pass_check("target device matches", TARGET_DEVICE))
    if binding.phase != "Ready":
        checks.append(fail("device augmentation ready", f"{DEVICE_AUGMENTATION_ID} phase={binding.phase!r}"))
    elif not ready_condition_is_true(binding.conditions):
        checks.append(fail("device augmentation ready", f"{DEVICE_AUGMENTATION_ID} Ready condition is not True"))
    else:
        checks.append(pass_check("device augmentation ready", "phase=Ready and Ready condition=True"))
    return checks


def pass_check(name: str, detail: str) -> AugmentationValidationCheck:
    return AugmentationValidationCheck(name=name, status="pass", detail=detail)


def fail(name: str, detail: str) -> AugmentationValidationCheck:
    return AugmentationValidationCheck(name=name, status="fail", detail=detail)


def ready_condition_is_true(conditions: list[object]) -> bool:
    return any(
        getattr(condition, "type", None) == "Ready" and getattr(condition, "status", None) == "True"
        for condition in conditions
    )


def elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def response_latency_ms(response: JsonMap, fallback: int) -> int:
    latency = response.get("latency_ms")
    return latency if isinstance(latency, int) and not isinstance(latency, bool) else fallback


def output_artifact(response: JsonMap) -> str | None:
    for key in ("output_artifact", "artifact", "artifact_uri", "result_uri"):
        value = response.get(key)
        if isinstance(value, str) and value:
            return value
    return None
