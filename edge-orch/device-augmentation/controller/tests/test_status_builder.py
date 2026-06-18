from __future__ import annotations

from datetime import datetime, timezone

from app.models import VirtualResourceProfile, VirtualResourceTwin
from app.status_builder import augmentation_resource_status, device_augmentation_status


def _resource(resource_id: str, capabilities: tuple[str, ...], status: str = "idle") -> VirtualResourceProfile:
    return VirtualResourceProfile(
        id=resource_id,
        display_name=resource_id,
        node="etri-ser0002-cgnmsb",
        resource_type="gpu",
        capabilities=capabilities,
        desired_instances=1,
        observed_instances=2,
        free_instances=2,
        allocated_instances=0,
        status=status,
        twin=VirtualResourceTwin(
            availability=status,
            node_ready=True,
            pod_ready=True,
            endpoint_ready=True,
            current_load="normal",
            binding_state="available",
            status_reason="runtime instance is observed and not bound",
        ),
    )


def test_augmentation_resource_status_when_idle_resource_is_available() -> None:
    # Given
    observed_at = datetime(2026, 6, 18, tzinfo=timezone.utc)
    resource = _resource("vd-x86-gpu-inference", ("gpu_inference",))

    # When
    patch = augmentation_resource_status(resource, observed_at)

    # Then
    assert patch["status"]["phase"] == "Available"
    assert patch["status"]["observedInstances"] == 2
    assert patch["status"]["bindingState"] == "available"
    assert patch["status"]["conditions"] == [
        {
            "type": "RuntimeObserved",
            "status": "True",
            "reason": "InstancesObserved",
            "message": "2 runtime instance(s) observed",
            "lastTransitionTime": "2026-06-18T00:00:00+00:00",
        },
        {
            "type": "EndpointReady",
            "status": "True",
            "reason": "EndpointReady",
            "message": "runtime endpoint is ready",
            "lastTransitionTime": "2026-06-18T00:00:00+00:00",
        },
        {
            "type": "Available",
            "status": "True",
            "reason": "ResourceAvailable",
            "message": "runtime instance is observed and not bound",
            "lastTransitionTime": "2026-06-18T00:00:00+00:00",
        },
    ]


def test_device_augmentation_status_when_bound_resources_cover_required_capabilities() -> None:
    # Given
    observed_at = datetime(2026, 6, 18, tzinfo=timezone.utc)
    resources = {
        "vd-x86-gpu-inference": _resource("vd-x86-gpu-inference", ("gpu_inference",)),
        "vd-storage-cache": _resource("vd-storage-cache", ("result_cache",)),
    }
    device_augmentation = {
        "spec": {
            "requiredCapabilities": ["gpu_inference", "result_cache"],
            "bindings": {
                "inferenceResource": "vd-x86-gpu-inference",
                "storageResource": "vd-storage-cache",
            },
        }
    }

    # When
    patch = device_augmentation_status(device_augmentation, resources, observed_at=observed_at)

    # Then
    assert patch["status"]["phase"] == "Ready"
    assert patch["status"]["boundResources"] == ["vd-x86-gpu-inference", "vd-storage-cache"]
    assert patch["status"]["missingCapabilities"] == []
    assert patch["status"]["selectedResources"] == [
        {
            "role": "inference",
            "name": "vd-x86-gpu-inference",
            "phase": "Available",
            "node": "etri-ser0002-cgnmsb",
            "observedInstances": 2,
            "bindingState": "available",
            "endpointReady": True,
        },
        {
            "role": "storage",
            "name": "vd-storage-cache",
            "phase": "Available",
            "node": "etri-ser0002-cgnmsb",
            "observedInstances": 2,
            "bindingState": "available",
            "endpointReady": True,
        },
    ]
    assert patch["status"]["conditions"][-1] == {
        "type": "Ready",
        "status": "True",
        "reason": "DeviceAugmentationReady",
        "message": "bound augmentation resources are available",
        "lastTransitionTime": "2026-06-18T00:00:00+00:00",
    }


def test_device_augmentation_status_uses_declared_resource_capabilities() -> None:
    # Given
    observed_at = datetime(2026, 6, 18, tzinfo=timezone.utc)
    resources = {
        "vd-aihat-inference": _resource("vd-aihat-inference", ("lightweight_inference",)),
        "vd-storage-cache": _resource("vd-storage-cache", ("result_cache",)),
    }
    declared = {"vd-storage-cache": ("model_cache", "window_storage")}
    device_augmentation = {
        "spec": {
            "requiredCapabilities": ["lightweight_inference", "model_cache"],
            "bindings": {
                "inferenceResource": "vd-aihat-inference",
                "storageResource": "vd-storage-cache",
            },
        }
    }

    # When
    patch = device_augmentation_status(
        device_augmentation,
        resources,
        declared_capabilities=declared,
        observed_at=observed_at,
    )

    # Then
    assert patch["status"]["phase"] == "Ready"
    assert patch["status"]["missingCapabilities"] == []
