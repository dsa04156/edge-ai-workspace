from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "representative_ai_crossover_experiment.py"
MANIFEST = ROOT / "tools" / "k8s" / "representative-ai-crossover.yaml"
RASPI_MANIFEST = ROOT / "tools" / "k8s" / "representative-ai-crossover-raspi.yaml"
ANALYZER = ROOT / "tools" / "analyze_representative_ai_platforms.py"


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
    by_kind = {}
    for document in documents:
        by_kind.setdefault(document["kind"], []).append(document)

    assert set(by_kind) == {"Service", "Job", "NetworkPolicy"}
    assert len(by_kind["NetworkPolicy"]) == 2
    service = by_kind["Service"][0]
    assert service["spec"]["selector"]["app.kubernetes.io/name"] == (
        "sensor-anomaly-inference-server1"
    )
    assert service["spec"]["ports"][0]["targetPort"] == 8081

    job = by_kind["Job"][0]
    pod = job["spec"]["template"]["spec"]
    assert pod["nodeSelector"]["kubernetes.io/hostname"] == "etri-dev0001-jetorn"
    assert pod["automountServiceAccountToken"] is False
    assert pod["restartPolicy"] == "Never"
    container = pod["containers"][0]
    assert "@sha256:" in container["image"]
    assert container["resources"]["limits"] == {"cpu": "250m", "memory": "512Mi"}
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["env"][2]["value"] == "jetson-device1"


def test_raspi_manifest_replays_jetson_capture_under_equal_limits() -> None:
    job = yaml.safe_load(RASPI_MANIFEST.read_text(encoding="utf-8"))
    pod = job["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert pod["nodeSelector"]["kubernetes.io/hostname"] == "etri-dev0003-raspi5"
    assert container["resources"]["limits"] == {"cpu": "250m", "memory": "512Mi"}
    assert container["args"][:2] == ["--replay-input", "/dataset/jetson.json"]
    assert any(volume["configMap"]["name"] == "representative-ai-crossover-dataset" for volume in pod["volumes"] if "configMap" in volume)


def test_replay_dataset_rejects_hash_mismatch(tmp_path: Path) -> None:
    module = load_module()
    frames = [
        {
            "frame_origin": index,
            "x": 1.0,
            "y": 2.0,
            "z": 3.0,
            "temperature_origin": index,
            "temperature": 4.0,
        }
        for index in range(64)
    ]
    path = tmp_path / "capture.json"
    path.write_text(
        json.dumps({"input_provenance": {"frames": frames, "dataset_sha256": "wrong"}}),
        encoding="utf-8",
    )

    try:
        module.load_replay_dataset(str(path))
    except ValueError as error:
        assert "hash mismatch" in str(error)
    else:
        raise AssertionError("tampered replay dataset was accepted")


def test_platform_analyzer_requires_one_dataset_and_reports_paired_gate() -> None:
    spec = importlib.util.spec_from_file_location("platform_analyzer", ANALYZER)
    analyzer = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(analyzer)
    runs = []
    for repetition in range(1, 4):
        for method, p95, throughput in (("local", 100.0, 10.0), ("server1", 50.0, 20.0)):
            runs.append(
                {
                    "repetition": repetition,
                    "method": method,
                    "width": 65536,
                    "background_cpu_ratio": 0.0,
                    "latency_ms": {"p95": p95},
                    "throughput_per_second": throughput,
                    "resource": {"cpu_saturation_ratio": 1.0, "throttled_seconds": 1.0},
                }
            )
    result = analyzer.summarize(
        [
            {
                "execution": {"site": "raspi", "node_name": "node-r"},
                "input_provenance": {"dataset_sha256": "same"},
                "model": {"depth": 20},
                "runs": runs,
            }
        ]
    )

    assert result["conditions"][0]["condition_qualified"] is True
    assert result["platforms"]["raspi"]["server1_latency_wins"] == 3
    assert result["profiles"]["raspi:65536"]["qualified_pairs"] == 3


def test_script_marks_proxy_as_untrained_and_has_no_route_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"production_model": False' in text
    assert "weights are deterministic and untrained" in text
    assert "kubectl patch" not in text
    assert "REMOTE_INFERENCE_MODE" not in text
