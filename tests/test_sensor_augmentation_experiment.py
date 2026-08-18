import importlib.util
import json
import sys
from pathlib import Path

import httpx
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "sensor_augmentation_experiment.py"
ANALYZER = ROOT / "tools" / "analyze_sensor_augmentation_experiment.py"
MANIFEST = ROOT / "tools" / "k8s" / "sensor-augmentation-experiment.yaml"


def load_module():
    spec = importlib.util.spec_from_file_location("sensor_augmentation_experiment", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_analyzer():
    spec = importlib.util.spec_from_file_location("sensor_augmentation_analysis", ANALYZER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_schedule_is_seeded_blocked_and_balanced() -> None:
    module = load_module()
    first = module.build_schedule(
        [0.0, 0.5, 1.0], [0, 64], repetitions=3, seed=42
    )
    second = module.build_schedule(
        [0.0, 0.5, 1.0], [0, 64], repetitions=3, seed=42
    )

    assert first == second
    assert len(first) == 36
    for ratio in (0.0, 0.5, 1.0):
        for memory_load_mib in (0, 64):
            methods = [
                method
                for observed_ratio, observed_memory, method in first
                if observed_ratio == ratio and observed_memory == memory_load_mib
            ]
            assert methods.count("local") == 3
            assert methods.count("server1") == 3


def test_percentile_uses_nearest_rank() -> None:
    module = load_module()
    assert module.percentile([], 0.95) == 0
    assert module.percentile([1, 2, 3, 4, 5], 0.50) == 3
    assert module.percentile([1, 2, 3, 4, 5], 0.95) == 5


def test_server1_measurement_separates_server_time_and_payload_size() -> None:
    module = load_module()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "requestId": payload["requestId"],
                "modelVersion": "cuda-baseline-1.0.0",
                "serverProcessingMs": 1.25,
            },
        )

    inferer = module.Server1Inferer(
        "http://server1",
        run_index=7,
        expected_model_version="cuda-baseline-1.0.0",
    )
    inferer.client.close()
    inferer.client = httpx.Client(transport=httpx.MockTransport(handler))
    measurement = inferer(10_000)
    inferer.close()

    assert measurement["server_processing_ms"] == 1.25
    assert measurement["request_bytes"] > 0
    assert measurement["response_bytes"] > 0


def test_script_never_mutates_the_active_route_or_deployment() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "kubectl patch" not in text
    assert "kubectl apply" not in text
    assert "REMOTE_INFERENCE_MODE" not in text
    assert "sensor-anomaly-inference-server1" in text
    assert 'payload.get("modelVersion")' in text


def test_experiment_job_is_isolated_pinned_and_not_part_of_gitops_root() -> None:
    documents = list(yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")))
    job, policy = documents
    pod = job["spec"]["template"]
    container = pod["spec"]["containers"][0]

    assert job["kind"] == "Job"
    assert job["spec"]["backoffLimit"] == 0
    assert pod["spec"]["restartPolicy"] == "Never"
    assert pod["spec"]["automountServiceAccountToken"] is False
    assert pod["spec"]["nodeSelector"] == {
        "kubernetes.io/hostname": "etri-dev0001-jetorn"
    }
    assert "@sha256:" in container["image"]
    assert container["resources"]["limits"] == {"cpu": "250m", "memory": "128Mi"}
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"] == {
        "edge-ai.io/augmentation-experiment": "true"
    }
    root_kustomization = (ROOT / "edgex" / "k8s" / "kustomization.yaml").read_text(
        encoding="utf-8"
    )
    assert "sensor-augmentation-experiment" not in root_kustomization


def test_analysis_pairs_methods_within_repetition_and_pressure_block() -> None:
    analyzer = load_analyzer()
    document = {
        "design": {"repetitions": 1, "target_rps": 1},
        "runs": [
            {
                "run_index": 1,
                "method": "local",
                "background_cpu_ratio": 0.5,
                "memory_load_mib": 0,
                "latency_ms": {"p95": 2.0},
                "edge_decision_e2e_latency_ms": {"p95": 3.0},
                "throughput_per_second": 1.0,
                "schedule_lag_ms": {"p95": 0.1},
                "resource": {
                    "cpu_saturation_ratio": 0.8,
                    "throttled_seconds": 0.1,
                    "memory_peak_mib": 40,
                    "oom_events": 0,
                },
                "error_count": 0,
            },
            {
                "run_index": 2,
                "method": "server1",
                "background_cpu_ratio": 0.5,
                "memory_load_mib": 0,
                "latency_ms": {"p95": 10.0},
                "edge_decision_e2e_latency_ms": {"p95": 6.0},
                "server_processing_ms": {"sample_count": 10, "p95": 1.5},
                "edge_server_roundtrip_overhead_ms": {
                    "sample_count": 10,
                    "p95": 4.5,
                },
                "throughput_per_second": 0.9,
                "schedule_lag_ms": {"p95": 1.0},
                "resource": {
                    "cpu_saturation_ratio": 0.9,
                    "throttled_seconds": 0.2,
                    "memory_peak_mib": 42,
                    "oom_events": 0,
                },
                "error_count": 0,
            },
        ],
    }

    summary = analyzer.summarize_document(document, "fixture.json")

    assert summary["pair_count"] == 1
    assert summary["server_latency_wins"] == 0
    assert summary["paired_comparisons"][0]["server_minus_local_p95_ms"] == 3.0
    server_group = next(
        group for group in summary["groups"] if group["method"] == "server1"
    )
    assert server_group["server_processing_p95_ms_median"] == 1.5
    assert server_group["edge_server_roundtrip_overhead_p95_ms_median"] == 4.5
    assert summary["latency_sign_test_two_sided_p"] == 1.0
    assert summary["condition_comparisons"][0]["qualification_passed"] is False


def test_analysis_skips_generated_summary_and_reports_promotion_rule(
    tmp_path: Path,
) -> None:
    experiment = {
        "design": {"repetitions": 1, "target_rps": 1},
        "runs": [
            {
                "run_index": index,
                "method": method,
                "background_cpu_ratio": 0,
                "memory_load_mib": 0,
                "latency_ms": {"p95": latency},
                "throughput_per_second": throughput,
                "schedule_lag_ms": {"p95": 0.1},
                "resource": {
                    "cpu_saturation_ratio": 0.5,
                    "throttled_seconds": 0,
                    "memory_peak_mib": 40,
                    "oom_events": 0,
                },
                "error_count": 0,
            }
            for index, method, latency, throughput in (
                (1, "local", 10.0, 100.0),
                (2, "server1", 8.0, 96.0),
            )
        ],
    }
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps(experiment), encoding="utf-8")
    generated_path = tmp_path / "summary.json"
    generated_path.write_text(
        '{"schema_version":"sensor-augmentation-analysis/v1"}',
        encoding="utf-8",
    )

    result = load_analyzer().summarize([raw_path, generated_path])

    assert result["schema_version"] == "sensor-augmentation-analysis/v3"
    assert result["skipped_generated_files"] == ["summary.json"]
    assert result["qualified_condition_count"] == 1
    assert result["validated_condition_count"] == 1
    assert result["candidate_qualified"] is True
    assert result["qualification_rule"] == {
        "latency_metric": "edge_decision_e2e_latency_p95",
        "latency_p95_improvement_percent": 10,
        "throughput_noninferiority_percent": 5,
        "requires_zero_errors_and_oom": True,
        "application": "future_candidate_promotion_gate",
    }
    assert result["measurement_contract"]["comparison_origin"] == (
        "frame_ready_at_edge"
    )
