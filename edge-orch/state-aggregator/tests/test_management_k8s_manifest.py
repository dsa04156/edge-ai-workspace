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
    assert env["DEVICE_DISCOVERY_TOKENLESS_APPROVAL_ENABLED"]["value"] == "true"
    assert env["ADAPTER_CONTROLLER_URL"]["value"] == (
        "http://edgex-adapter-controller.edgex-edge.svc.cluster.local:8080"
    )
    assert env["DEVICE_MANAGEMENT_ADMIN_TOKEN"]["valueFrom"]["secretKeyRef"] == {
        "name": "edgex-adapter-management-auth",
        "key": "admin-token",
    }
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


def test_dashboard_service_account_remains_read_only_for_kubernetes_workloads() -> None:
    resources = render()
    roles = [
        item
        for (kind, _), item in resources.items()
        if kind in {"Role", "ClusterRole"}
    ]
    rules = [rule for item in roles for rule in item.get("rules", [])]

    for rule in rules:
        resources_in_rule = set(rule.get("resources", []))
        if resources_in_rule & {
            "deployments",
            "services",
            "configmaps",
            "networkpolicies",
            "adapterruntimes",
        }:
            assert not (
                set(rule.get("verbs", []))
                & {"create", "update", "patch", "delete", "deletecollection"}
            )
