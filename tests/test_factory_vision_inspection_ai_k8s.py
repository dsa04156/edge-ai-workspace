from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
K8S_DIR = ROOT / "edge-orch" / "vision_stage_runner" / "k8s"
ARGOCD_APPS = ROOT / "edge-orch-argocd" / "argocd-apps.yaml"


def _load_yaml(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [doc for doc in yaml.safe_load_all(handle) if doc]


def _resources() -> dict[tuple[str, str], dict]:
    resources: dict[tuple[str, str], dict] = {}
    for path in sorted(K8S_DIR.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        for doc in _load_yaml(path):
            resources[(doc["kind"], doc["metadata"]["name"])] = doc
    return resources


def _service_selector_is_valid(resources: dict[tuple[str, str], dict]) -> bool:
    deployment = resources[("Deployment", "factory-vision-inspection-ai")]
    service = resources[("Service", "factory-vision-inspection-ai")]
    labels = deployment["spec"]["template"]["metadata"]["labels"]
    selector = service["spec"]["selector"]
    return all(labels.get(key) == value for key, value in selector.items())


def _argocd_app_path_is_valid(path: str) -> bool:
    return path == "edge-orch/vision_stage_runner/k8s"


def test_factory_vision_ai_manifest_contract():
    resources = _resources()

    deployment = resources[("Deployment", "factory-vision-inspection-ai")]
    service = resources[("Service", "factory-vision-inspection-ai")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]

    assert deployment["metadata"]["namespace"] == "default"
    assert deployment["spec"]["selector"]["matchLabels"] == {
        "app": "factory-vision-inspection-ai"
    }
    assert deployment["spec"]["template"]["metadata"]["labels"]["app"] == (
        "factory-vision-inspection-ai"
    )
    assert deployment["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/hostname": "etri-dev0001-jetorn"
    }
    assert container["image"] == "192.168.0.56:5000/vision-stage-runner:latest"
    assert container["imagePullPolicy"] == "Always"
    assert container["ports"] == [{"containerPort": 8080, "name": "http"}]
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["resources"]["requests"]["cpu"]
    assert container["resources"]["requests"]["memory"]
    assert container["resources"]["limits"]["cpu"]
    assert container["resources"]["limits"]["memory"]
    assert {
        item["name"]: item["value"] for item in container["env"]
    } == {
        "SERVICE_NAME": "factory-vision-inspection-ai",
        "SCENARIO_ID": "jetson-vision-inspection",
        "TARGET_DEVICE": "etri-dev0001-jetorn",
        "WORKFLOW_ID": "factory-vision-live",
    }

    assert service["metadata"]["namespace"] == "default"
    assert service["spec"]["ports"] == [
        {"name": "http", "port": 8080, "targetPort": "http"}
    ]
    assert _service_selector_is_valid(resources)


def test_factory_vision_ai_kustomization_lists_deployment():
    kustomization = yaml.safe_load((K8S_DIR / "kustomization.yaml").read_text())

    assert kustomization["resources"] == ["deployment.yaml"]


def test_factory_vision_ai_argocd_application_contract():
    apps = {
        doc["metadata"]["name"]: doc
        for doc in _load_yaml(ARGOCD_APPS)
        if doc.get("kind") == "Application"
    }

    app = apps["edge-orch-factory-vision-inspection-ai"]
    assert _argocd_app_path_is_valid(app["spec"]["source"]["path"])
    assert app["spec"]["source"]["targetRevision"] == "main"
    assert app["spec"]["destination"]["namespace"] == "default"
    assert app["spec"]["syncPolicy"]["automated"] == {
        "prune": True,
        "selfHeal": True,
    }


def test_rejects_missing_factory_service_selector():
    resources = {
        ("Deployment", "factory-vision-inspection-ai"): {
            "spec": {"template": {"metadata": {"labels": {"app": "factory-vision-inspection-ai"}}}}
        },
        ("Service", "factory-vision-inspection-ai"): {
            "spec": {"selector": {"app": "wrong-service"}}
        },
    }

    assert not _service_selector_is_valid(resources)


def test_rejects_wrong_argocd_path():
    assert not _argocd_app_path_is_valid("llm")
