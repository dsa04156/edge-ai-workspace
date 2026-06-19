from __future__ import annotations

import time
import uuid
import json
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

import httpx
from kubernetes import client
from pydantic import BaseModel, Field

from .augmentation_crds import AugmentationResourceCrdState, DeviceAugmentationCrdState
from .virtual_resources import JsonMap


SCENARIO_ID = "jetson-inspection-x86-gpu-cache-v1"
DEVICE_AUGMENTATION_ID = "jetson-gpu-storage-augmentation"
TARGET_DEVICE = "etri-dev0001-jetorn"
INFERENCE_RESOURCE = "vd-x86-gpu-inference"
STORAGE_RESOURCE = "vd-storage-cache"
DEFAULT_INPUT_SOURCE = "jetson-inspection-camera"

ExecutionStatus = Literal["not_run", "blocked", "pending", "running", "succeeded", "failed"]
ProgressStepStatus = Literal["pending", "running", "succeeded", "failed"]


class AugmentationExecutionRequest(BaseModel):
    input_source: str = DEFAULT_INPUT_SOURCE
    payload: dict[str, Any] = Field(default_factory=dict)


class AugmentationValidationCheck(BaseModel):
    name: str
    status: Literal["pass", "fail"]
    detail: str


class AugmentationProgressStep(BaseModel):
    id: str
    label: str
    status: ProgressStepStatus = "pending"


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
    phase: str = "NotRun"
    job_name: str | None = None
    job_namespace: str | None = None
    progress_percent: int = 0
    progress_steps: list[AugmentationProgressStep] = Field(default_factory=list)
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


class KubernetesJobAugmentationExecutionRunner:
    def __init__(
        self,
        *,
        namespace: str,
        image: str,
        endpoint_url: str,
        ttl_seconds_after_finished: int,
        batch_api: Any | None = None,
        core_api: Any | None = None,
    ) -> None:
        self.namespace = namespace
        self.image = image
        self.endpoint_url = endpoint_url
        self.ttl_seconds_after_finished = ttl_seconds_after_finished
        self.batch = batch_api or client.BatchV1Api()
        self.core = core_api or client.CoreV1Api()

    async def execute(self, payload: JsonMap) -> JsonMap:
        if not self.endpoint_url:
            raise RuntimeError("resource augmentation inference endpoint is not configured")
        execution_id = text(payload.get("execution_id"), str(uuid.uuid4()))
        job_name = job_name_for_execution(execution_id)
        body = self._job_body(job_name=job_name, payload=payload)
        self.batch.create_namespaced_job(namespace=self.namespace, body=body)
        return {
            "status": "running",
            "phase": "Running",
            "job_name": job_name,
            "job_namespace": self.namespace,
            "progress_percent": 55,
            "progress_steps": progress_payload("running"),
        }

    async def refresh(self, record: AugmentationExecutionRecord) -> JsonMap:
        if not record.job_name:
            return {"status": "failed", "phase": "MissingJob", "error": "execution record has no job_name"}
        namespace = record.job_namespace or self.namespace
        job = self.batch.read_namespaced_job(namespace=namespace, name=record.job_name)
        status = getattr(job, "status", None)
        succeeded = int(getattr(status, "succeeded", None) or 0)
        failed = int(getattr(status, "failed", None) or 0)
        active = int(getattr(status, "active", None) or 0)
        if succeeded > 0:
            logs = self._job_logs(namespace=namespace, job_name=record.job_name)
            return {
                "status": "succeeded",
                "phase": "Succeeded",
                "job_name": record.job_name,
                "job_namespace": namespace,
                "progress_percent": 100,
                "output_artifact": output_artifact_from_logs(logs) or f"job://{namespace}/{record.job_name}",
                "response": {"logs": logs},
                "progress_steps": progress_payload("succeeded"),
            }
        if failed > 0:
            logs = self._job_logs(namespace=namespace, job_name=record.job_name)
            return {
                "status": "failed",
                "phase": "Failed",
                "job_name": record.job_name,
                "job_namespace": namespace,
                "progress_percent": 100,
                "error": logs or f"{record.job_name} failed",
                "progress_steps": progress_payload("failed"),
            }
        return {
            "status": "running" if active > 0 else "pending",
            "phase": "Running" if active > 0 else "Pending",
            "job_name": record.job_name,
            "job_namespace": namespace,
            "progress_percent": 70 if active > 0 else 45,
            "progress_steps": progress_payload("running" if active > 0 else "pending"),
        }

    def _job_body(self, *, job_name: str, payload: JsonMap) -> JsonMap:
        analyzer_payload = analyzer_request_payload(payload)
        command = (
            "import json, os, urllib.request\n"
            "url = os.environ['AUGMENTATION_ANALYZE_URL']\n"
            "payload = os.environ['AUGMENTATION_ANALYZE_PAYLOAD'].encode('utf-8')\n"
            "timeout = int(os.environ.get('AUGMENTATION_ANALYZE_TIMEOUT_SECONDS', '30'))\n"
            "req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})\n"
            "body = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8')\n"
            "print(body)\n"
        )
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": self.namespace,
                "labels": {
                    "app": "resource-augmentation-execution",
                    "edge-ai.io/scenario": SCENARIO_ID,
                },
            },
            "spec": {
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": self.ttl_seconds_after_finished,
                "template": {
                    "metadata": {
                        "labels": {
                            "app": "resource-augmentation-execution",
                            "job-name": job_name,
                        }
                    },
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "analyzer-call",
                                "image": self.image,
                                "imagePullPolicy": "Always",
                                "command": ["python", "-c", command],
                                "env": [
                                    {"name": "AUGMENTATION_ANALYZE_URL", "value": self.endpoint_url},
                                    {
                                        "name": "AUGMENTATION_ANALYZE_PAYLOAD",
                                        "value": json.dumps(analyzer_payload, ensure_ascii=False),
                                    },
                                    {"name": "AUGMENTATION_ANALYZE_TIMEOUT_SECONDS", "value": "30"},
                                ],
                                "resources": {
                                    "requests": {"cpu": "50m", "memory": "64Mi"},
                                    "limits": {"cpu": "250m", "memory": "256Mi"},
                                },
                            }
                        ],
                    },
                },
            },
        }

    def _job_logs(self, *, namespace: str, job_name: str) -> str:
        try:
            pods = self.core.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
            if not pods.items:
                return ""
            pod_name = pods.items[0].metadata.name
            return self.core.read_namespaced_pod_log(namespace=namespace, name=pod_name, tail_lines=80)
        except Exception:
            return ""


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

    async def refresh_state(self) -> AugmentationExecutionState:
        if self.last_execution is None or self.last_execution.status not in {"pending", "running"}:
            return self.state()
        refresh = getattr(self.runner, "refresh", None)
        if refresh is None:
            return self.state()
        response = await refresh(self.last_execution)
        self._apply_runner_response(self.last_execution, response)
        return self.state()

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
            phase="Validating",
            triggered_at=datetime.now(timezone.utc),
            input_source=request.input_source,
            target_endpoint=self.target_endpoint,
            target_resources=target_resources,
            validation=validation,
            progress_percent=10,
            progress_steps=base_progress_steps(),
        )
        failures = [check.detail for check in validation if check.status == "fail"]
        if failures:
            record.completed_at = datetime.now(timezone.utc)
            record.error = "; ".join(failures)
            record.phase = "Blocked"
            record.progress_percent = 100
            record.progress_steps = mark_step(record.progress_steps, "validate", "failed")
            self.last_execution = record
            return self.state()

        payload: JsonMap = {
            "execution_id": record.execution_id,
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
            record.phase = "Failed"
            record.progress_percent = 100
            record.progress_steps = mark_step(record.progress_steps, "create_job", "failed")
            self.last_execution = record
            return self.state()

        self._apply_runner_response(record, response, fallback_latency_ms=elapsed_ms(started))
        self.last_execution = record
        return self.state()

    def _apply_runner_response(
        self,
        record: AugmentationExecutionRecord,
        response: JsonMap,
        fallback_latency_ms: int | None = None,
    ) -> None:
        status = execution_status(response.get("status"))
        record.status = status
        record.phase = text(response.get("phase"), status.title())
        record.job_name = optional_text(response.get("job_name")) or record.job_name
        record.job_namespace = optional_text(response.get("job_namespace")) or record.job_namespace
        record.progress_percent = bounded_percent(response.get("progress_percent"), default_progress_percent(status))
        record.progress_steps = progress_steps(response.get("progress_steps")) or default_steps_for_status(status)
        if fallback_latency_ms is not None or response.get("latency_ms") is not None:
            record.latency_ms = response_latency_ms(response, fallback_latency_ms or 0)
        record.output_artifact = output_artifact(response) or record.output_artifact
        record.error = optional_text(response.get("error")) or record.error
        record.response = response
        if status in {"succeeded", "failed", "blocked"}:
            record.completed_at = datetime.now(timezone.utc)


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


def execution_status(value: object) -> ExecutionStatus:
    return value if value in {"blocked", "pending", "running", "succeeded", "failed"} else "succeeded"


def optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def text(value: object, fallback: str = "") -> str:
    return value if isinstance(value, str) and value else fallback


def bounded_percent(value: object, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return fallback
    return max(0, min(100, int(value)))


def default_progress_percent(status: ExecutionStatus) -> int:
    return {
        "not_run": 0,
        "blocked": 100,
        "pending": 40,
        "running": 70,
        "succeeded": 100,
        "failed": 100,
    }[status]


def base_progress_steps() -> list[AugmentationProgressStep]:
    return [
        AugmentationProgressStep(id="validate", label="사전 검증", status="running"),
        AugmentationProgressStep(id="create_job", label="Kubernetes Job 생성"),
        AugmentationProgressStep(id="run_analyzer", label="x86 analyzer 실행"),
        AugmentationProgressStep(id="collect_result", label="결과 수집"),
    ]


def default_steps_for_status(status: ExecutionStatus) -> list[AugmentationProgressStep]:
    steps = base_progress_steps()
    if status == "pending":
        steps = mark_step(steps, "validate", "succeeded")
        steps = mark_step(steps, "create_job", "running")
    elif status == "running":
        steps = mark_step(steps, "validate", "succeeded")
        steps = mark_step(steps, "create_job", "succeeded")
        steps = mark_step(steps, "run_analyzer", "running")
    elif status == "succeeded":
        steps = [
            AugmentationProgressStep(id=step.id, label=step.label, status="succeeded")
            for step in steps
        ]
    elif status in {"failed", "blocked"}:
        steps = mark_step(steps, "validate", "failed" if status == "blocked" else "succeeded")
        steps = mark_step(steps, "create_job", "failed" if status == "failed" else "pending")
    return steps


def progress_steps(value: object) -> list[AugmentationProgressStep]:
    if not isinstance(value, list):
        return []
    steps: list[AugmentationProgressStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        step_id = item.get("id")
        label = item.get("label")
        status = item.get("status")
        if not isinstance(step_id, str) or not isinstance(label, str):
            continue
        if status not in {"pending", "running", "succeeded", "failed"}:
            status = "pending"
        steps.append(AugmentationProgressStep(id=step_id, label=label, status=status))
    return steps


def mark_step(
    steps: list[AugmentationProgressStep],
    step_id: str,
    status: ProgressStepStatus,
) -> list[AugmentationProgressStep]:
    return [
        AugmentationProgressStep(id=step.id, label=step.label, status=status if step.id == step_id else step.status)
        for step in steps
    ]


def job_name_for_execution(execution_id: str) -> str:
    safe = "".join(char.lower() for char in execution_id if char.isalnum())
    return f"resource-augmentation-{safe[:12] or uuid.uuid4().hex[:12]}"


def analyzer_request_payload(payload: JsonMap) -> dict[str, Any]:
    requested = payload.get("payload")
    if isinstance(requested, dict) and isinstance(requested.get("device_id"), str) and isinstance(requested.get("vibration"), list):
        return {"device_id": requested["device_id"], "vibration": requested["vibration"]}
    target_device = text(payload.get("target_device"), TARGET_DEVICE)
    return {
        "device_id": target_device,
        "vibration": [0.12, 0.18, 0.31, 0.26, 0.21, 0.17],
    }


def progress_payload(status: ExecutionStatus) -> list[dict[str, str]]:
    return [
        {"id": step.id, "label": step.label, "status": step.status}
        for step in default_steps_for_status(status)
    ]


def output_artifact_from_logs(logs: str) -> str | None:
    for line in reversed(logs.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            artifact = output_artifact(payload)
            if artifact:
                return artifact
    return None
