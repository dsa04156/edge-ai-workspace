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
    assert env["RUNTIME_RECOMMENDATION_ENABLED"]["value"] == "true"
    assert env["RUNTIME_RECOMMENDATION_POLL_INTERVAL_SECONDS"]["value"] == "15"
    assert env["RUNTIME_RECOMMENDATION_DATABASE_PATH"]["value"] == (
        "/app/data/runtime-recommendations.sqlite3"
    )
    assert env["EXECUTION_CONTROLLER_ENABLED"]["value"] == "true"
    assert env["RUNTIME_EXECUTION_DATABASE_PATH"]["value"] == (
        "/app/data/runtime-executions.sqlite3"
    )
    assert env["CANDIDATE_TEMPLATE_CATALOG_PATH"]["value"] == (
        "/app/app/config/candidate_workload_templates.json"
    )
    assert env["CANDIDATE_VALIDATION_CONTRACT_PATH"]["value"] == (
        "/app/app/config/candidate_validation_contracts.json"
    )
    assert env["TRAFFIC_ROUTING_CONTRACT_PATH"]["value"] == (
        "/app/app/config/traffic_routing_contracts.json"
    )
    assert env["EXECUTION_OWNERSHIP_CONTRACT_PATH"]["value"] == (
        "/app/app/config/execution_ownership_contracts.json"
    )
    assert env["EXECUTION_MANAGEMENT_TOKEN"]["valueFrom"]["secretKeyRef"] == {
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
    assert {
        "apiGroups": ["apps"],
        "resources": ["deployments", "statefulsets"],
        "verbs": ["get", "list", "watch"],
    } in reader["rules"]
    assert {
        "apiGroups": [""],
        "resources": ["services", "persistentvolumeclaims"],
        "verbs": ["get", "list", "watch"],
    } in reader["rules"]
    assert {
        "apiGroups": ["storage.k8s.io"],
        "resources": ["storageclasses"],
        "verbs": ["get", "list", "watch"],
    } in reader["rules"]
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


def test_runtime_recommendation_state_uses_single_writer_persistent_storage() -> None:
    resources = render()
    deployment = resources[("Deployment", "state-aggregator")]
    claim = resources[("PersistentVolumeClaim", "state-aggregator-state")]

    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert claim["spec"]["resources"]["requests"]["storage"] == "1Gi"
    volume = deployment["spec"]["template"]["spec"]["volumes"][0]
    assert volume == {
        "name": "state-data",
        "persistentVolumeClaim": {"claimName": "state-aggregator-state"},
    }


def test_runtime_controller_can_update_only_the_approved_execution_lease() -> None:
    resources = render()
    role = resources[("Role", "state-aggregator-runtime-routing")]
    lease_rules = [
        item
        for item in role["rules"]
        if item.get("apiGroups") == ["coordination.k8s.io"]
    ]

    assert lease_rules == [
        {
            "apiGroups": ["coordination.k8s.io"],
            "resources": ["leases"],
            "resourceNames": ["sensor-anomaly-demo-execution"],
            "verbs": ["get", "update"],
        }
    ]
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
