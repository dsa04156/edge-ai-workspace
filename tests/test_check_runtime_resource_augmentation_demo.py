import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_runtime_resource_augmentation_demo.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_runtime_resource_augmentation_demo", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runtime_resource_augmentation_checker_accepts_candidate_pool_and_augmented_device() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "ai_service": "factory-vision-inspection-ai",
        "summary": {"candidate_resource_total": 15, "available": 12, "bound": 0, "blocked": 3},
        "candidate_resources": [
            {"name": "vd-x86-gpu-inference", "kind": "gpu-inference", "phase": "Available"},
            {"name": "vd-storage-cache", "kind": "storage-cache", "phase": "Available"},
        ] + [
            {"name": f"aug-gpu-x86-{index:03d}", "kind": "gpu-inference", "phase": "Available"}
            for index in range(1, 9)
        ] + [
            {"name": "aug-storage-cache-001", "kind": "storage-cache", "phase": "Available"},
            {"name": "aug-model-cache-001", "kind": "model-cache", "phase": "Available"},
            {"name": "aug-jetson-gpu-001", "kind": "gpu-inference", "phase": "Blocked"},
            {"name": "aug-jetson-gpu-002", "kind": "gpu-inference", "phase": "Blocked"},
            {"name": "aug-storage-cache-002", "kind": "storage-cache", "phase": "Blocked"},
        ],
        "decision": {
            "state": "selected",
            "trigger": "service_resource_request",
            "ai_service": "factory-vision-inspection-ai",
            "target_device": "etri-dev0001-jetorn",
            "pressure_reason": ["gpu_inference_pressure"],
            "candidate_resource_names": ["vd-x86-gpu-inference", "vd-storage-cache"],
            "selected_resources": [
                {"role": "inference", "name": "vd-x86-gpu-inference"},
                {"role": "storage", "name": "vd-storage-cache"},
            ],
            "resulting_augmented_device": {
                "name": "ad-jetorn-inspection-001",
                "target_device": "etri-dev0001-jetorn",
                "phase": "Planned",
            },
            "apply_state": "observed-only",
        },
        "workflow_demo": {
            "name": "inspection-resource-augmentation-demo",
            "status": "offload_planned",
            "steps": [
                {"id": "service-request", "state": "completed"},
                {"id": "pressure-detected", "state": "completed"},
                {"id": "candidate-scan", "state": "completed"},
                {"id": "offload-plan", "state": "active"},
                {"id": "augmented-device-bind", "state": "planned"},
            ],
            "offload_path": {
                "source": "etri-dev0001-jetorn",
                "inference": "vd-x86-gpu-inference",
                "cache": "vd-storage-cache",
                "result": "ad-jetorn-inspection-001",
            },
        },
    }

    errors = module.validate_runtime_augmentation(payload)

    assert errors == []


def test_runtime_resource_augmentation_checker_rejects_wrong_count() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "ai_service": "wrong-service",
        "summary": {"candidate_resource_total": 14, "available": 14, "bound": 0, "blocked": 0},
        "candidate_resources": [],
        "decision": {},
    }

    errors = module.validate_runtime_augmentation(payload)

    assert "ai_service='wrong-service', expected 'factory-vision-inspection-ai'" in errors
    assert "summary.candidate_resource_total=14, expected 15" in errors
    assert "candidate_resources count=0, expected 15" in errors


def test_runtime_resource_augmentation_checker_rejects_waiting_virtual_device_pool() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "ai_service": "factory-vision-inspection-ai",
        "summary": {"candidate_resource_total": 15, "available": 15, "bound": 0, "blocked": 0},
        "virtual_devices": [{"name": f"vd-inspection-{index:03d}", "state": "waiting"} for index in range(1, 16)],
        "candidate_resources": [{"name": f"aug-gpu-x86-{index:03d}", "kind": "gpu-inference", "phase": "Available"} for index in range(1, 16)],
        "decision": {
            "state": "selected",
            "trigger": "service_resource_request",
            "ai_service": "factory-vision-inspection-ai",
            "selected_resources": [],
        },
    }

    errors = module.validate_runtime_augmentation(payload)

    assert "legacy virtual_devices waiting pool must not be present" in errors
