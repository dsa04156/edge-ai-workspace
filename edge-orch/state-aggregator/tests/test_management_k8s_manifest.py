from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1] / "k8s"


def render() -> dict[tuple[str, str], dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(K8S_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        (item["kind"], item["metadata"]["name"]): item
        for item in yaml.safe_load_all(result.stdout)
        if item
    }


def test_dashboard_management_uses_internal_controller_and_secret_refs() -> None:
    deployment = render()[("Deployment", "state-aggregator")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert env["DEVICE_MANAGEMENT_ENABLED"]["value"] == "true"
    assert env["ADAPTER_RUNTIME_MANAGEMENT_ENABLED"]["value"] == "true"
    assert env["ADAPTER_RUNTIME_MUTATION_ENABLED"]["value"] == "true"
    assert env["ADAPTER_CONTROLLER_URL"]["value"] == (
        "http://edgex-adapter-controller.edgex-edge.svc.cluster.local:8080"
    )
    assert "DEVICE_MANAGEMENT_ADMIN_TOKEN" not in env
    assert "DEVICE_DISCOVERY_TOKENLESS_APPROVAL_ENABLED" not in env
    assert env["DEVICE_MANAGEMENT_HMAC_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "edgex-adapter-management-auth",
        "key": "management-hmac-key",
    }
    assert env["ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY"]["valueFrom"][
        "secretKeyRef"
    ] == {
        "name": "edgex-adapter-management-auth",
        "key": "internal-hmac-key",
    }
    assert "192.168." not in env["ADAPTER_CONTROLLER_URL"]["value"]
    assert env["DEPLOYMENT_CONTROLLER_ENABLED"]["value"] == "true"
    assert env["DEPLOYMENT_TARGET_NAMESPACE"]["value"] == "edge-ai-workloads"
    assert env["DEPLOYMENT_MANAGEMENT_TOKEN"]["valueFrom"]["secretKeyRef"] == {
        "name": "edgex-adapter-management-auth",
        "key": "management-hmac-key",
    }


def test_deployment_controller_has_create_only_access_in_its_bounded_namespace() -> None:
    resources = render()
    namespace = resources[("Namespace", "edge-ai-workloads")]
    reader = resources[("ClusterRole", "state-aggregator-node-reader")]
    creator = resources[("Role", "state-aggregator-deployment-creator")]
    binding = resources[("RoleBinding", "state-aggregator-deployment-creator")]

    assert namespace["metadata"]["name"] == "edge-ai-workloads"
    assert all(
        not (
            set(rule.get("verbs", []))
            & {"create", "update", "patch", "delete", "deletecollection"}
        )
        for rule in reader["rules"]
    )
    assert creator["metadata"]["namespace"] == "edge-ai-workloads"
    assert creator["rules"] == [
        {
            "apiGroups": ["apps"],
            "resources": ["deployments"],
            "verbs": ["create", "get", "list", "watch"],
        }
    ]
    assert binding["metadata"]["namespace"] == "edge-ai-workloads"
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": "state-aggregator",
            "namespace": "default",
        }
    ]
    assert binding["roleRef"] == {
        "kind": "Role",
        "name": "state-aggregator-deployment-creator",
        "apiGroup": "rbac.authorization.k8s.io",
    }


def test_dashboard_is_exposed_through_the_gitops_managed_traefik_route() -> None:
    ingress_route = render()[("IngressRoute", "state-aggregator")]

    assert ingress_route["metadata"]["namespace"] == "default"
    assert ingress_route["spec"]["entryPoints"] == ["web"]

    route = ingress_route["spec"]["routes"][0]
    assert route["kind"] == "Rule"
    assert route["match"] == (
        "Host(`aggregator.192.168.0.56.sslip.io`) || "
        "Host(`aggregator.10.254.192.217.sslip.io`)"
    )
    assert route["services"] == [{"name": "state-aggregator", "port": 8000}]
