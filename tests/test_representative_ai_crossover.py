from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "representative_ai_crossover_experiment.py"
MANIFEST = ROOT / "tools" / "k8s" / "representative-ai-crossover.yaml"


def load_module():
    spec = importlib.util.spec_from_file_location("representative_crossover", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_model_input_replays_real_frame_values_into_fixed_contract() -> None:
    module = load_module()
    frames = [
        {"x": 256.0, "y": 128.0, "z": 64.0, "temperature": 32.0},
        {"x": 512.0, "y": 256.0, "z": 128.0, "temperature": 64.0},
    ]
    values = module.model_input(frames, 0)

    assert len(values) == module.INPUT_WIDTH == 256
    assert values[:8] == [0.5, 0.25, 0.125, 0.0625, 1.0, 0.5, 0.25, 0.125]
    assert module.MODEL_VERSION == "representative-temporal-convolution-v1"


def test_manifest_is_temporary_isolated_and_uses_existing_gpu_candidate() -> None:
    documents = list(yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")))
    by_kind = {document["kind"]: document for document in documents}

    assert set(by_kind) == {"Service", "Job", "NetworkPolicy"}
    service = by_kind["Service"]
    assert service["spec"]["selector"]["app.kubernetes.io/name"] == (
        "sensor-anomaly-inference-server1"
    )
    assert service["spec"]["ports"][0]["targetPort"] == 8081

    job = by_kind["Job"]
    pod = job["spec"]["template"]["spec"]
    assert pod["nodeSelector"]["kubernetes.io/hostname"] == "etri-dev0001-jetorn"
    assert pod["automountServiceAccountToken"] is False
    assert pod["restartPolicy"] == "Never"
    container = pod["containers"][0]
    assert "@sha256:" in container["image"]
    assert container["resources"]["limits"] == {"cpu": "250m", "memory": "512Mi"}
    assert container["securityContext"]["readOnlyRootFilesystem"] is True


def test_script_marks_proxy_as_untrained_and_has_no_route_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"production_model": False' in text
    assert "weights are deterministic and untrained" in text
    assert "kubectl patch" not in text
    assert "REMOTE_INFERENCE_MODE" not in text
