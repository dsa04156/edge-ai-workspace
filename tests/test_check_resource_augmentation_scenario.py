import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_resource_augmentation_scenario.py"


def load_check_resource_augmentation_scenario():
    spec = importlib.util.spec_from_file_location("check_resource_augmentation_scenario", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ready_jetson_vision_inspection_payload_passes() -> None:
    # Given
    module = load_check_resource_augmentation_scenario()
    virtual_resources = {
        "mode": "read_only",
        "scope": "resource_augmentation_virtual_devices",
        "resources": [
            {
                "id": "vd-x86-gpu-inference",
                "observed_instances": 8,
                "twin": {"endpoint_ready": True, "binding_state": "available"},
            },
            {
                "id": "vd-storage-cache",
                "observed_instances": 8,
                "twin": {"endpoint_ready": True, "binding_state": "available"},
            },
        ],
    }
    augmentation_resources = {
        "resources": [
            {"name": "vd-x86-gpu-inference", "phase": "Available", "endpoint_ready": True},
            {"name": "vd-storage-cache", "phase": "Available", "endpoint_ready": True},
        ],
    }
    device_augmentations = {
        "device_augmentations": [
            {
                "name": "jetson-gpu-storage-augmentation",
                "target_device_name": "etri-dev0001-jetorn",
                "phase": "Ready",
                "selected_resources": [
                    {"role": "inference", "name": "vd-x86-gpu-inference"},
                    {"role": "storage", "name": "vd-storage-cache"},
                ],
                "conditions": [{"type": "Ready", "status": "True"}],
            }
        ],
    }

    # When
    errors, warnings = module.check_scenario_payloads(
        virtual_resources=virtual_resources,
        augmentation_resources=augmentation_resources,
        device_augmentations=device_augmentations,
    )

    # Then
    assert errors == []
    assert warnings == []


def test_missing_ready_condition_fails() -> None:
    # Given
    module = load_check_resource_augmentation_scenario()
    virtual_resources = {
        "resources": [
            {
                "id": "vd-x86-gpu-inference",
                "observed_instances": 1,
                "twin": {"endpoint_ready": True, "binding_state": "available"},
            },
            {
                "id": "vd-storage-cache",
                "observed_instances": 1,
                "twin": {"endpoint_ready": True, "binding_state": "available"},
            },
        ],
    }
    augmentation_resources = {
        "resources": [
            {"name": "vd-x86-gpu-inference", "phase": "Available", "endpoint_ready": True},
            {"name": "vd-storage-cache", "phase": "Available", "endpoint_ready": True},
        ],
    }
    device_augmentations = {
        "device_augmentations": [
            {
                "name": "jetson-gpu-storage-augmentation",
                "target_device_name": "etri-dev0001-jetorn",
                "phase": "Pending",
                "selected_resources": [],
                "conditions": [{"type": "Ready", "status": "False"}],
            }
        ],
    }

    # When
    errors, _ = module.check_scenario_payloads(
        virtual_resources=virtual_resources,
        augmentation_resources=augmentation_resources,
        device_augmentations=device_augmentations,
    )

    # Then
    assert "jetson-gpu-storage-augmentation: expected phase=Ready, got 'Pending'" in errors
    assert "jetson-gpu-storage-augmentation: expected Ready condition=True, got 'False'" in errors
