from __future__ import annotations

from fastapi.testclient import TestClient

from app.augmentation_crds import AugmentationCrdReader
from app.augmentation_execution import (
    AugmentationExecutionRunner,
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
