import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_runtime_resource_augmentation_demo.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_runtime_resource_augmentation_demo", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runtime_resource_augmentation_checker_accepts_15_item_demo_payload() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "summary": {"total": 15, "selected": 5, "blocked": 2, "candidate": 4, "none": 4},
        "recommendations": [
            {
                "virtual_device": f"vd-inspection-{index:03d}",
                "recommendation": (
                    "selected"
                    if index <= 5
                    else "candidate"
                    if index <= 9
                    else "blocked"
                    if index <= 11
                    else "none"
                ),
                "target_device": "etri-dev0001-jetorn",
                "pressure_reason": [] if index >= 12 else ["gpu_inference_pressure"],
                "selected_resources": [
                    {"role": "inference", "name": "vd-x86-gpu-inference"},
                    {"role": "storage", "name": "vd-storage-cache"},
                ] if index <= 5 else [],
                "apply_state": "blocked" if 10 <= index <= 11 else "observed-only",
            }
            for index in range(1, 16)
        ],
    }

    errors = module.validate_runtime_augmentation(payload)

    assert errors == []


def test_runtime_resource_augmentation_checker_rejects_wrong_count() -> None:
    module = load_checker()
    payload = {
        "scope": "runtime_resource_augmentation_demo_v1",
        "summary": {"total": 14, "selected": 0, "blocked": 0, "candidate": 0, "none": 14},
        "recommendations": [],
    }

    errors = module.validate_runtime_augmentation(payload)

    assert "summary.total=14, expected 15" in errors
    assert "recommendations count=0, expected 15" in errors
