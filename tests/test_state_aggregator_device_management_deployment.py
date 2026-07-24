from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATH = ROOT / "edge-orch/state-aggregator/k8s/deployment.yaml"
BUILD_WORKFLOW_PATH = ROOT / ".github/workflows/docker-build-push.yml"


def _resources() -> dict[tuple[str, str], dict]:
    documents = yaml.safe_load_all(DEPLOYMENT_PATH.read_text(encoding="utf-8"))
    return {
        (document["kind"], document["metadata"]["name"]): document
        for document in documents
        if document
    }


def test_device_management_is_enabled_only_with_required_secret_refs() -> None:
    deployment = _resources()[("Deployment", "state-aggregator")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    environment = {item["name"]: item for item in container["env"]}

    assert environment["DEVICE_MANAGEMENT_ENABLED"] == {
        "name": "DEVICE_MANAGEMENT_ENABLED",
        "value": "true",
    }
    assert environment["ADAPTER_RUNTIME_MANAGEMENT_ENABLED"]["value"] == "true"
    assert environment["ADAPTER_RUNTIME_MUTATION_ENABLED"]["value"] == "true"
    assert environment["ADAPTER_CATALOG_PATH"] == {
        "name": "ADAPTER_CATALOG_PATH",
        "value": "/app/app/config/adapter_catalog.json",
    }
    expected_secret_refs = {
        "DEVICE_MANAGEMENT_HMAC_KEY": "management-hmac-key",
        "ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY": "internal-hmac-key",
    }
    for name, key in expected_secret_refs.items():
        assert environment[name]["valueFrom"]["secretKeyRef"] == {
            "name": "edgex-adapter-management-auth",
            "key": key,
        }
        assert "value" not in environment[name]
    assert "DEVICE_MANAGEMENT_ADMIN_TOKEN" not in environment
    assert "DEVICE_DISCOVERY_TOKENLESS_APPROVAL_ENABLED" not in environment


def test_management_deployment_does_not_add_fixed_network_or_edgemesh_paths() -> None:
    resources = _resources()
    service = resources[("Service", "state-aggregator")]
    manifest = DEPLOYMENT_PATH.read_text(encoding="utf-8").lower()

    assert "clusterIP" not in service["spec"]
    assert "edgemesh" not in manifest
    assert "podip" not in manifest


def test_ci_deploys_state_aggregator_through_argocd_digest_override() -> None:
    workflow = BUILD_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "STATE_AGGREGATOR_IMAGE=" in workflow
    assert "state-aggregator-build-metadata.json" in workflow
    assert "kubectl patch application edge-orch-state-aggregator" in workflow
    assert 'targetRevision\\\":\\\"${TARGET_REVISION}' in workflow
    assert "argocd.argoproj.io/refresh=hard" in workflow
    assert "kubectl set image deployment/state-aggregator" not in workflow


def test_ci_deploys_adapter_controller_before_enabling_dashboard_management() -> None:
    workflow = yaml.safe_load(BUILD_WORKFLOW_PATH.read_text(encoding="utf-8"))
    step_names = [
        step.get("name")
        for step in workflow["jobs"]["build-and-push"]["steps"]
    ]

    assert step_names.index(
        "Deploy EdgeX adapter management images through Argo CD"
    ) < step_names.index("Deploy state-aggregator image through Argo CD")


def test_ci_skips_legacy_mqtt_mapper_deploy_when_daemonset_is_absent() -> None:
    workflow = yaml.safe_load(BUILD_WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build-and-push"]["steps"]
    deploy_step = next(
        step
        for step in steps
        if step.get("name") == "Deploy mqttvirtual mapper latest image"
    )
    script = deploy_step["run"]

    guard = "if ! kubectl get daemonset mqttvirtual-mapper -n default"
    assert guard in script
    assert script.index(guard) < script.index("CURRENT_IMAGE=")
    assert "Legacy mqttvirtual mapper is not deployed; skipping rollout." in script
