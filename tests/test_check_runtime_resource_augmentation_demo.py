import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_runtime_resource_augmentation_demo.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_runtime_resource_augmentation_demo", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runtime_resource_augmentation_checker_accepts_waiting_pool_and_single_decision() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "ai_service": "factory-vision-inspection-ai",
        "summary": {"virtual_device_total": 15, "waiting": 15, "running": 0, "reserved": 0},
        "virtual_devices": [
            {
                "name": f"vd-inspection-{index:03d}",
                "state": "waiting",
                "capability": "vision-inference-slot",
                "node": "virtual-pool",
            }
            for index in range(1, 16)
        ],
        "decision": {
            "state": "selected",
            "trigger": "service_resource_request",
            "ai_service": "factory-vision-inspection-ai",
            "target_device": "etri-dev0001-jetorn",
            "pressure_reason": ["gpu_inference_pressure"],
            "selected_resources": [
                {"role": "inference", "name": "vd-x86-gpu-inference"},
                {"role": "storage", "name": "vd-storage-cache"},
            ],
            "virtual_device_candidates": ["vd-inspection-001", "vd-inspection-002", "vd-inspection-003"],
            "apply_state": "observed-only",
        },
    }

    errors = module.validate_runtime_augmentation(payload)

    assert errors == []


def test_runtime_resource_augmentation_checker_rejects_wrong_count() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "ai_service": "wrong-service",
        "summary": {"virtual_device_total": 14, "waiting": 14, "running": 0, "reserved": 0},
        "virtual_devices": [],
        "decision": {},
    }

    errors = module.validate_runtime_augmentation(payload)

    assert "ai_service='wrong-service', expected 'factory-vision-inspection-ai'" in errors
    assert "summary.virtual_device_total=14, expected 15" in errors
    assert "virtual_devices count=0, expected 15" in errors


def test_runtime_resource_augmentation_checker_rejects_legacy_recommendations_list() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "ai_service": "factory-vision-inspection-ai",
        "summary": {"virtual_device_total": 15, "waiting": 15, "running": 0, "reserved": 0},
        "recommendations": [],
        "virtual_devices": [{"name": f"vd-inspection-{index:03d}", "state": "waiting"} for index in range(1, 16)],
        "decision": {"state": "selected", "selected_resources": []},
    }

    errors = module.validate_runtime_augmentation(payload)

    assert "legacy recommendations list must not be present" in errors
