from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.augmentation_crds import AugmentationCrdReader
from app.augmentation_execution import (
    AugmentationExecutionRunner,
    KubernetesJobAugmentationExecutionRunner,
    ResourceAugmentationExecutor,
)
from app.main import app
from app.virtual_resources import JsonMap


class FakeReadyCustomObjectsApi:
    def list_cluster_custom_object(self, *, group: str, version: str, plural: str) -> JsonMap:
        return {
            "items": [
                {
                    "metadata": {"name": "vd-x86-gpu-inference"},
                    "spec": {
                        "displayName": "x86 GPU Inference",
                        "resourceType": "gpu",
                        "nodeSelector": {"kubernetes.io/hostname": "etri-ser0002-cgnmsb"},
                    },
                    "status": {"phase": "Available", "endpointReady": True, "freeInstances": 2},
                },
                {
                    "metadata": {"name": "vd-storage-cache"},
                    "spec": {
                        "displayName": "Storage Cache",
                        "resourceType": "storage/cache",
                        "nodeSelector": {"kubernetes.io/hostname": "etri-ser0002-cgnmsb"},
                    },
                    "status": {"phase": "Available", "endpointReady": True, "freeInstances": 1},
                },
            ]
        }

    def list_namespaced_custom_object(self, *, group: str, version: str, namespace: str, plural: str) -> JsonMap:
        return {
            "items": [
                {
                    "metadata": {"name": "jetson-gpu-storage-augmentation", "namespace": namespace},
                    "spec": {
                        "targetDevice": {"kind": "EdgeNode", "name": "etri-dev0001-jetorn"},
                        "requiredCapabilities": ["gpu_inference", "result_cache"],
                    },
                    "status": {
                        "phase": "Ready",
                        "selectedResources": [
                            {"role": "inference", "name": "vd-x86-gpu-inference"},
                            {"role": "storage", "name": "vd-storage-cache"},
                        ],
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
            ]
        }


class FakeBlockedCustomObjectsApi(FakeReadyCustomObjectsApi):
    def list_cluster_custom_object(self, *, group: str, version: str, plural: str) -> JsonMap:
        payload = super().list_cluster_custom_object(group=group, version=version, plural=plural)
        payload["items"][0]["status"] = {"phase": "Pending", "endpointReady": False, "freeInstances": 0}
        return payload


class RecordingRunner(AugmentationExecutionRunner):
    def __init__(self) -> None:
        self.calls: list[JsonMap] = []

    async def execute(self, payload: JsonMap) -> JsonMap:
        self.calls.append(payload)
        return {
            "status": "ok",
            "latency_ms": 87,
            "output_artifact": "s3://edge-ai-results/inspection-0001.json",
        }


class RecordingJobRunner(AugmentationExecutionRunner):
    def __init__(self) -> None:
        self.calls: list[JsonMap] = []

    async def execute(self, payload: JsonMap) -> JsonMap:
        self.calls.append(payload)
        return {
            "status": "running",
            "job_name": "resource-augmentation-abc123",
            "job_namespace": "default",
            "phase": "Running",
            "progress_percent": 55,
            "progress_steps": [
                {"id": "validate", "label": "사전 검증", "status": "succeeded"},
                {"id": "create_job", "label": "Kubernetes Job 생성", "status": "succeeded"},
                {"id": "run_analyzer", "label": "x86 analyzer 실행", "status": "running"},
                {"id": "collect_result", "label": "결과 수집", "status": "pending"},
            ],
        }

    async def refresh(self, record):
        return {
            "status": "succeeded",
            "phase": "Succeeded",
            "progress_percent": 100,
            "latency_ms": 1234,
            "output_artifact": "job://default/resource-augmentation-abc123",
            "progress_steps": [
                {"id": "validate", "label": "사전 검증", "status": "succeeded"},
                {"id": "create_job", "label": "Kubernetes Job 생성", "status": "succeeded"},
                {"id": "run_analyzer", "label": "x86 analyzer 실행", "status": "succeeded"},
                {"id": "collect_result", "label": "결과 수집", "status": "succeeded"},
            ],
        }


def test_resource_augmentation_execution_triggers_fixed_endpoint_and_records_last_execution(monkeypatch) -> None:
    reader = AugmentationCrdReader(custom_api=FakeReadyCustomObjectsApi())
    runner = RecordingRunner()
    executor = ResourceAugmentationExecutor(runner=runner)
    monkeypatch.setattr("app.main.augmentation_crds", reader)
    monkeypatch.setattr("app.main.augmentation_executor", executor)

    with TestClient(app) as client:
        response = client.post(
            "/state/resource-augmentation/execution",
            json={"input_source": "jetson-inspection-camera", "payload": {"image_id": "inspection-0001"}},
        )
        state_response = client.get("/state/resource-augmentation/execution")

    assert response.status_code == 200
    payload = response.json()
    assert payload["last_execution"]["status"] == "succeeded"
    assert payload["last_execution"]["target_device"] == "etri-dev0001-jetorn"
    assert payload["last_execution"]["target_resources"]["inference"] == "vd-x86-gpu-inference"
    assert payload["last_execution"]["target_resources"]["storage"] == "vd-storage-cache"
    assert payload["last_execution"]["latency_ms"] == 87
    assert payload["last_execution"]["output_artifact"] == "s3://edge-ai-results/inspection-0001.json"
    assert payload["last_execution"]["validation"][0]["status"] == "pass"
    assert state_response.json()["last_execution"]["execution_id"] == payload["last_execution"]["execution_id"]

    assert len(runner.calls) == 1
    assert runner.calls[0]["scenario_id"] == "jetson-inspection-x86-gpu-cache-v1"
    assert runner.calls[0]["input_source"] == "jetson-inspection-camera"
    assert runner.calls[0]["resources"]["inference"] == "vd-x86-gpu-inference"
    assert runner.calls[0]["payload"] == {"image_id": "inspection-0001"}


def test_resource_augmentation_execution_blocks_when_required_resource_is_not_available(monkeypatch) -> None:
    reader = AugmentationCrdReader(custom_api=FakeBlockedCustomObjectsApi())
    runner = RecordingRunner()
    executor = ResourceAugmentationExecutor(runner=runner)
    monkeypatch.setattr("app.main.augmentation_crds", reader)
    monkeypatch.setattr("app.main.augmentation_executor", executor)

    with TestClient(app) as client:
        response = client.post("/state/resource-augmentation/execution", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["last_execution"]["status"] == "blocked"
    assert "vd-x86-gpu-inference" in payload["last_execution"]["error"]
    assert payload["last_execution"]["output_artifact"] is None
    assert runner.calls == []


def test_resource_augmentation_execution_creates_job_and_get_refreshes_progress(monkeypatch) -> None:
    reader = AugmentationCrdReader(custom_api=FakeReadyCustomObjectsApi())
    runner = RecordingJobRunner()
    executor = ResourceAugmentationExecutor(runner=runner)
    monkeypatch.setattr("app.main.augmentation_crds", reader)
    monkeypatch.setattr("app.main.augmentation_executor", executor)

    with TestClient(app) as client:
        post_response = client.post("/state/resource-augmentation/execution", json={})
        get_response = client.get("/state/resource-augmentation/execution")

    assert post_response.status_code == 200
    posted = post_response.json()["last_execution"]
    assert posted["status"] == "running"
    assert posted["phase"] == "Running"
    assert posted["job_name"] == "resource-augmentation-abc123"
    assert posted["job_namespace"] == "default"
    assert posted["progress_percent"] == 55
    assert posted["progress_steps"][2]["status"] == "running"

    refreshed = get_response.json()["last_execution"]
    assert refreshed["status"] == "succeeded"
    assert refreshed["phase"] == "Succeeded"
    assert refreshed["progress_percent"] == 100
    assert refreshed["latency_ms"] == 1234
    assert refreshed["output_artifact"] == "job://default/resource-augmentation-abc123"
    assert refreshed["progress_steps"][3]["status"] == "succeeded"


class FakeBatchApi:
    def __init__(self) -> None:
        self.created: list[tuple[str, JsonMap]] = []
        self.job_status = type("JobStatus", (), {"succeeded": None, "failed": None, "active": 1})()
        self.job = type("Job", (), {"status": self.job_status})()

    def create_namespaced_job(self, *, namespace: str, body: JsonMap):
        self.created.append((namespace, body))
        return self.job

    def read_namespaced_job(self, *, namespace: str, name: str):
        return self.job


class FakeCoreApi:
    def list_namespaced_pod(self, *, namespace: str, label_selector: str):
        pod = type("Pod", (), {})()
        pod.metadata = type("Metadata", (), {"name": "resource-augmentation-exec123-pod"})()
        return type("PodList", (), {"items": [pod]})()

    def read_namespaced_pod_log(self, *, namespace: str, name: str, tail_lines: int):
        return '{"output_artifact":"job://default/resource-augmentation-exec123"}'


def test_kubernetes_job_runner_creates_analyzer_job_and_refreshes_status() -> None:
    batch = FakeBatchApi()
    core = FakeCoreApi()
    runner = KubernetesJobAugmentationExecutionRunner(
        batch_api=batch,
        core_api=core,
        namespace="default",
        image="192.168.0.56:5000/state-aggregator:latest",
        endpoint_url="http://j-server-analyzer-svc.offload-test.svc.cluster.local:8000/analyze",
        ttl_seconds_after_finished=600,
    )

    response = asyncio.run(
        runner.execute(
            {
                "execution_id": "exec123456789",
                "target_device": "etri-dev0001-jetorn",
                "payload": {"device_id": "etri-dev0001-jetorn", "vibration": [0.1, 0.2, 0.3]},
            }
        )
    )

    assert response["status"] == "running"
    assert response["job_name"] == "resource-augmentation-exec12345678"
    namespace, body = batch.created[0]
    assert namespace == "default"
    assert body["metadata"]["name"] == "resource-augmentation-exec12345678"
    container = body["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "192.168.0.56:5000/state-aggregator:latest"
    env = {item["name"]: item["value"] for item in container["env"]}
    assert env["AUGMENTATION_ANALYZE_URL"] == "http://j-server-analyzer-svc.offload-test.svc.cluster.local:8000/analyze"
    assert "vibration" in env["AUGMENTATION_ANALYZE_PAYLOAD"]

    refreshed = asyncio.run(
        runner.refresh(
            type(
                "Record",
                (),
                {"job_name": "resource-augmentation-exec12345678", "job_namespace": "default"},
            )()
        )
    )
    assert refreshed["status"] == "running"
    assert refreshed["progress_percent"] == 70

    batch.job_status.active = None
    batch.job_status.succeeded = 1
    refreshed = asyncio.run(
        runner.refresh(
            type(
                "Record",
                (),
                {"job_name": "resource-augmentation-exec12345678", "job_namespace": "default"},
            )()
        )
    )
    assert refreshed["status"] == "succeeded"
    assert refreshed["progress_percent"] == 100
    assert refreshed["output_artifact"] == "job://default/resource-augmentation-exec123"
