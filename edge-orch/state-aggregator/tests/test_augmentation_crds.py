from __future__ import annotations

from fastapi.testclient import TestClient

from app.augmentation_crds import AugmentationCrdReader
from app.main import app
from app.virtual_resources import JsonMap


class FakeCustomObjectsApi:
    def list_cluster_custom_object(self, *, group: str, version: str, plural: str) -> JsonMap:
        assert group == "augmentation.edge-ai.io"
        assert version == "v1alpha1"
        assert plural == "augmentationresources"
        return {
            "items": [
                {
                    "metadata": {"name": "vd-x86-gpu-inference"},
                    "spec": {
                        "displayName": "x86 GPU Inference",
                        "resourceType": "gpu",
                        "nodeSelector": {"kubernetes.io/hostname": "etri-ser0002-cgnmsb"},
                        "capabilities": ["gpu_inference"],
                        "stageTypes": ["ai_inference"],
                    },
                    "status": {
                        "phase": "Available",
                        "observedInstances": 8,
                        "freeInstances": 8,
                        "bindingState": "available",
                        "endpointReady": True,
                        "conditions": [
                            {"type": "Available", "status": "True", "reason": "ResourceAvailable"},
                        ],
                    },
                }
            ]
        }

    def list_namespaced_custom_object(self, *, group: str, version: str, namespace: str, plural: str) -> JsonMap:
        assert group == "augmentation.edge-ai.io"
        assert version == "v1alpha1"
        assert namespace == "default"
        assert plural == "deviceaugmentations"
        return {
            "items": [
                {
                    "metadata": {"name": "jetson-gpu-storage-augmentation", "namespace": "default"},
                    "spec": {
                        "targetDevice": {"kind": "EdgeNode", "name": "etri-dev0001-jetorn"},
                        "bindings": {
                            "inferenceResource": "vd-x86-gpu-inference",
                            "storageResource": "vd-storage-cache",
                        },
                        "requiredCapabilities": ["gpu_inference", "result_cache"],
                        "workloadPolicy": {"mode": "read_only"},
                    },
                    "status": {
                        "phase": "Ready",
                        "boundResources": ["vd-x86-gpu-inference", "vd-storage-cache"],
                        "selectedResources": [
                            {"role": "inference", "name": "vd-x86-gpu-inference", "node": "etri-ser0002-cgnmsb"},
                        ],
                        "conditions": [
                            {"type": "Ready", "status": "True", "reason": "DeviceAugmentationReady"},
                        ],
                    },
                }
            ]
        }


def test_augmentation_crd_routes_return_kubernetes_status(monkeypatch) -> None:
    # Given
    reader = AugmentationCrdReader(custom_api=FakeCustomObjectsApi())
    monkeypatch.setattr("app.main.augmentation_crds", reader)

    # When
    with TestClient(app) as client:
        resource_response = client.get("/state/augmentation-resources")
        binding_response = client.get("/state/device-augmentations")

    # Then
    assert resource_response.status_code == 200
    resources = resource_response.json()
    assert resources["scope"] == "resource_augmentation_crds"
    assert resources["resources"][0]["name"] == "vd-x86-gpu-inference"
    assert resources["resources"][0]["phase"] == "Available"
    assert resources["resources"][0]["endpoint_ready"] is True
    assert resources["resources"][0]["conditions"][0]["type"] == "Available"

    assert binding_response.status_code == 200
    bindings = binding_response.json()
    assert bindings["device_augmentations"][0]["name"] == "jetson-gpu-storage-augmentation"
    assert bindings["device_augmentations"][0]["phase"] == "Ready"
    assert bindings["device_augmentations"][0]["selected_resources"][0]["role"] == "inference"
    assert bindings["device_augmentations"][0]["conditions"][0]["reason"] == "DeviceAugmentationReady"
