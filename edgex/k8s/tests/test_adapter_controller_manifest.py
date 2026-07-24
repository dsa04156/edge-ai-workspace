from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1]


def render_path(path: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        document
        for document in yaml.safe_load_all(result.stdout)
        if document
    ]


def render() -> list[dict[str, Any]]:
    return render_path(K8S_DIR)


def indexed() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (item["kind"], item["metadata"]["name"]): item
        for item in render()
    }


def test_adapter_runtime_crd_is_namespaced_structural_and_has_status():
    resources = indexed()
    crd = resources[
        ("CustomResourceDefinition", "adapterruntimes.edgeai.etri.re.kr")
    ]

    assert crd["spec"]["group"] == "edgeai.etri.re.kr"
    assert crd["spec"]["scope"] == "Namespaced"
    assert crd["spec"]["names"]["kind"] == "AdapterRuntime"
    version = crd["spec"]["versions"][0]
    assert version["name"] == "v1alpha1"
    assert version["served"] is True
    assert version["storage"] is True
    assert version["subresources"] == {"status": {}}
    schema = version["schema"]["openAPIV3Schema"]
    spec = schema["properties"]["spec"]
    assert set(spec["required"]) == {
        "templateId",
        "adapterId",
        "targetNode",
        "hardwareBindingId",
        "edgeX",
        "desiredState",
        "requestRef",
    }
    spec_text = str(spec)
    for forbidden in ("image", "hostPath", "clusterIP", "podIP", "command"):
        assert forbidden not in spec_text
    assert spec["properties"]["desiredState"]["enum"] == ["Running", "Retired"]

    def assert_no_forbidden_additional_properties(value: Any) -> None:
        if isinstance(value, dict):
            assert value.get("additionalProperties") is not False
            for child in value.values():
                assert_no_forbidden_additional_properties(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_forbidden_additional_properties(child)

    assert_no_forbidden_additional_properties(schema)


def test_controller_deployment_is_feature_gated_and_secret_authenticated():
    resources = indexed()
    deployment = resources[("Deployment", "edgex-adapter-controller")]
    service = resources[("Service", "edgex-adapter-controller")]
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert deployment["metadata"]["namespace"] == "edgex-edge"
    assert pod["serviceAccountName"] == "edgex-adapter-controller"
    assert pod["nodeSelector"] == {
        "kubernetes.io/hostname": "etri-ser0002-cgnmsb"
    }
    assert pod.get("hostNetwork", False) is False
    assert pod["securityContext"] == {
        "fsGroup": 2001,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert re.fullmatch(
        r"192\.168\.0\.56:5000/edge-adapter-controller@sha256:[0-9a-f]{64}",
        container["image"],
    )
    assert env["ADAPTER_RUNTIME_MUTATION_ENABLED"]["value"] == "true"
    assert env["DISCOVERY_DATABASE_PATH"]["value"] == (
        "/var/lib/adapter-controller/discovery.db"
    )
    assert env["ADAPTER_AUTH_MODE"]["value"] == "development-mock"
    assert env["EDGEX_CORE_DATA_URL"]["value"].endswith(":59880")
    assert "value" not in env["ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY"]
    assert env["ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY"]["valueFrom"][
        "secretKeyRef"
    ] == {
        "name": "edgex-adapter-management-auth",
        "key": "internal-hmac-key",
    }
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
        "runAsUser": 2001,
        "runAsGroup": 2001,
    }
    assert {"startupProbe", "readinessProbe", "livenessProbe"} <= container.keys()
    assert container["resources"]["requests"]
    assert container["resources"]["limits"]
    assert {
        item["name"]: item["mountPath"] for item in container["volumeMounts"]
    }["discovery-state"] == "/var/lib/adapter-controller"
    assert next(
        item for item in pod["volumes"] if item["name"] == "discovery-state"
    )["persistentVolumeClaim"]["claimName"] == (
        "edgex-adapter-controller-state"
    )
    pvc = resources[
        ("PersistentVolumeClaim", "edgex-adapter-controller-state")
    ]
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert pvc["spec"]["resources"]["requests"]["storage"] == "1Gi"
    assert service["metadata"]["namespace"] == "edgex-edge"
    assert "clusterIP" not in service["spec"]
    assert "podIP" not in str(deployment) + str(service)


def test_controller_base_fails_closed_without_external_approval_configuration():
    resources = {
        (item["kind"], item["metadata"]["name"]): item
        for item in render_path(K8S_DIR / "base/adapter-controller")
    }
    deployment = resources[("Deployment", "edgex-adapter-controller")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert env["ADAPTER_AUTH_MODE"] == {
        "name": "ADAPTER_AUTH_MODE",
        "value": "external",
    }
    for name, key in (
        ("ADAPTER_AUTH_ENDPOINT", "endpoint"),
        ("ADAPTER_AUTH_TOKEN", "token"),
    ):
        assert env[name]["valueFrom"]["secretKeyRef"] == {
            "name": "edgex-device-approval-auth",
            "key": key,
            "optional": True,
        }
        assert "value" not in env[name]


def test_controller_rbac_is_namespaced_except_node_read():
    resources = indexed()
    role = resources[("Role", "edgex-adapter-controller")]
    cluster_role = resources[("ClusterRole", "edgex-adapter-controller-node-reader")]

    assert role["metadata"]["namespace"] == "edgex-edge"
    rules = role["rules"]
    custom = next(
        item
        for item in rules
        if item["apiGroups"] == ["edgeai.etri.re.kr"]
    )
    assert set(custom["resources"]) == {
        "adapterruntimes",
        "adapterruntimes/status",
    }
    assert set(custom["verbs"]) == {
        "get",
        "list",
        "watch",
        "create",
        "update",
        "patch",
    }
    namespaced_resources = {
        resource
        for rule in rules
        for resource in rule["resources"]
    }
    assert {
        "deployments",
        "services",
        "configmaps",
        "networkpolicies",
        "pods",
        "events",
    } <= namespaced_resources
    assert "secrets" not in namespaced_resources
    assert cluster_role["rules"] == [
        {
            "apiGroups": [""],
            "resources": ["nodes"],
            "verbs": ["get", "list"],
        }
    ]
    rbac_text = str(role) + str(cluster_role)
    assert "devices" not in rbac_text
    assert "devicemodels" not in rbac_text
    assert "edgemesh" not in rbac_text.lower()


def test_controller_network_policy_only_exposes_internal_api_to_aggregator_and_discovery():
    policy = indexed()[("NetworkPolicy", "edgex-adapter-controller")]

    assert policy["metadata"]["namespace"] == "edgex-edge"
    assert policy["spec"]["policyTypes"] == ["Ingress", "Egress"]
    ingress = policy["spec"]["ingress"]
    assert ingress == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": "default",
                        }
                    },
                    "podSelector": {
                        "matchLabels": {"app": "state-aggregator"}
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8080}],
        },
        {
            "from": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "edge-device-discovery"
                        }
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8080}],
        },
    ]
    assert policy["spec"]["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": "kube-system"
                        }
                    }
                }
            ],
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        },
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": "edgex-system"
                        }
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "edgex-core-metadata"
                        }
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 59881}],
        },
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": "edgex-system"
                        }
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "edgex-core-data"
                        }
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 59880}],
        },
        {"ports": [{"protocol": "TCP", "port": 443}]},
    ]


def test_operational_render_adds_no_kubeedge_device_or_edgemesh_resource():
    resources = render()
    text = "\n".join(
        f"{item.get('apiVersion')} {item.get('kind')} "
        f"{(item.get('metadata') or {}).get('name')}"
        for item in resources
    ).lower()

    assert "devices.devices.kubeedge.io" not in text
    assert "devicemodel" not in text
    assert "edgemesh" not in text
