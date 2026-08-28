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


def test_server1_shadow_endpoint_is_managed_by_active_kustomization() -> None:
    active = yaml.safe_load((ROOT / "k8s" / "kustomization.yaml").read_text())
    resources = _resources()

    assert "server1-observed-only" in active["resources"]
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

    assert pod["spec"]["nodeSelector"]["kubernetes.io/hostname"] == "etri-ser0002-cgnmsb"
    assert "schedulerName" not in pod["spec"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/api/v1/augmentation-readyz"
    assert container["image"] == (
        "192.168.0.56:5000/sensor-anomaly-demo-server1@"
        "sha256:b31d45e138c431cc3f6a04be5757b0244942338cd2387b01ef7825359f464c1c"
    )
    assert {item["name"]: item.get("value") for item in container["env"]}.items() >= {
        "SERVICE_ROLE": "inference-server",
        "INFERENCE_WARMUP_SOURCE_ENABLED": "true",
        "CUPY_CACHE_DIR": "/tmp/cupy-cache",
        "MODEL_BACKEND": "cuda-online-baseline",
        "MODEL_VERSION": "cuda-baseline-1.0.0",
    }.items()
    assert container["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert service["spec"]["selector"] == {
        "app.kubernetes.io/name": "sensor-anomaly-inference-server1"
    }
    assert candidate["spec"]["runtimeRef"]["serviceSelector"] == service["spec"]["selector"]
    assert candidate["spec"]["nodeSelector"]["kubernetes.io/hostname"] == "etri-ser0002-cgnmsb"
    assert candidate["spec"]["resourceType"] == "gpu"
    assert {"cuda_inference", "hami_vgpu"}.issubset(candidate["spec"]["capabilities"])
    assert "automaticOffloading" not in yaml.safe_dump(resources)
