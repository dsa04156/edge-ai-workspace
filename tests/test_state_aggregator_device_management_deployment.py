from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATH = ROOT / "edge-orch/state-aggregator/k8s/deployment.yaml"


def _resources() -> dict[tuple[str, str], dict]:
    documents = yaml.safe_load_all(DEPLOYMENT_PATH.read_text(encoding="utf-8"))
    return {
        (document["kind"], document["metadata"]["name"]): document
        for document in documents
        if document
    }


def test_device_management_is_explicitly_disabled_without_committed_secrets() -> None:
    deployment = _resources()[("Deployment", "state-aggregator")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    environment = {item["name"]: item for item in container["env"]}

    assert environment["DEVICE_MANAGEMENT_ENABLED"] == {
        "name": "DEVICE_MANAGEMENT_ENABLED",
        "value": "false",
    }
    assert environment["ADAPTER_CATALOG_PATH"] == {
        "name": "ADAPTER_CATALOG_PATH",
        "value": "/app/app/config/adapter_catalog.json",
    }
    assert "DEVICE_MANAGEMENT_ADMIN_TOKEN" not in environment
    assert "DEVICE_MANAGEMENT_HMAC_KEY" not in environment


def test_management_deployment_does_not_add_fixed_network_or_edgemesh_paths() -> None:
    resources = _resources()
    service = resources[("Service", "state-aggregator")]
    manifest = DEPLOYMENT_PATH.read_text(encoding="utf-8").lower()

    assert "clusterIP" not in service["spec"]
    assert "edgemesh" not in manifest
    assert "podip" not in manifest
