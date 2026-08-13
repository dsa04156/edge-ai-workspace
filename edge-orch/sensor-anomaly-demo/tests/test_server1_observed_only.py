from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "k8s" / "server1-observed-only"


def _resources() -> list[dict]:
    return [
        item
        for item in yaml.safe_load_all(
            (OVERLAY / "resources.yaml").read_text(encoding="utf-8")
        )
        if item
    ]


def test_server1_shadow_endpoint_is_prepared_but_not_in_active_kustomization() -> None:
    active = yaml.safe_load((ROOT / "k8s" / "kustomization.yaml").read_text())
    resources = _resources()

    assert "server1-observed-only" not in active["resources"]
    assert {item["kind"] for item in resources} == {
        "Service",
        "Deployment",
        "NetworkPolicy",
        "AugmentationResource",
    }


def test_server1_endpoint_uses_model_readiness_and_never_enables_offloading() -> None:
    resources = _resources()
    deployment = next(item for item in resources if item["kind"] == "Deployment")
    service = next(item for item in resources if item["kind"] == "Service")
    candidate = next(item for item in resources if item["kind"] == "AugmentationResource")
    pod = deployment["spec"]["template"]
    container = pod["spec"]["containers"][0]

    assert pod["spec"]["nodeSelector"]["kubernetes.io/hostname"] == "etri-ser0001-cg0msb"
    assert container["readinessProbe"]["httpGet"]["path"] == "/api/v1/augmentation-readyz"
    assert container["image"] == (
        "192.168.0.56:5000/sensor-anomaly-demo@"
        "sha256:2abc03055426ea979a38e18fa3e58df1c6b49b4057a6c84fc4cc62342a9e641b"
    )
    assert {item["name"]: item.get("value") for item in container["env"]}.items() >= {
        "SERVICE_ROLE": "inference-server",
        "INFERENCE_WARMUP_SOURCE_ENABLED": "true",
    }.items()
    assert service["spec"]["selector"] == {
        "app.kubernetes.io/name": "sensor-anomaly-inference-server1"
    }
    assert candidate["spec"]["runtimeRef"]["serviceSelector"] == service["spec"]["selector"]
    assert candidate["spec"]["nodeSelector"]["kubernetes.io/hostname"] == "etri-ser0001-cg0msb"
    assert "automaticOffloading" not in yaml.safe_dump(resources)
