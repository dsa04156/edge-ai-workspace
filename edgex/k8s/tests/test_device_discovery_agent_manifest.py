from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1]
BASE = K8S_DIR / "base/device-discovery-agent"


def render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(BASE)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def render_overlay(name: str) -> list[dict[str, Any]]:
    path = K8S_DIR / "overlays/examples" / name
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def test_discovery_daemon_is_read_only_scoped_and_secret_authenticated():
    resources = {
        (item["kind"], item["metadata"]["name"]): item
        for item in render()
    }
    daemon = resources[("DaemonSet", "edge-device-discovery")]
    account = resources[("ServiceAccount", "edge-device-discovery")]
    policy = resources[("NetworkPolicy", "edge-device-discovery-egress")]
    pod = daemon["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert account["automountServiceAccountToken"] is False
    assert pod["automountServiceAccountToken"] is False
    assert pod.get("hostNetwork", False) is False
    assert pod["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"][0]["matchExpressions"][0] == {
        "key": "kubernetes.io/hostname",
        "operator": "In",
        "values": [
            "etri-dev0001-jetorn",
            "etri-dev0002-raspi5",
            "etri-dev0003-raspi5",
        ],
    }
    assert {
        item["hostPath"]["path"]
        for item in pod["volumes"]
        if "hostPath" in item
    } == {"/dev", "/sys"}
    assert all(
        item.get("readOnly") is True
        for item in container["volumeMounts"]
        if item["name"] in {"host-dev", "host-sys"}
    )
    security = container["securityContext"]
    assert security["allowPrivilegeEscalation"] is False
    assert security["readOnlyRootFilesystem"] is True
    assert security["runAsNonRoot"] is True
    assert security["capabilities"] == {"drop": ["ALL"]}
    assert "@sha256:" in container["image"]
    assert container["ports"] == [
        {
            "name": "health",
            "containerPort": 8081,
            "protocol": "TCP",
        }
    ]
    assert container["startupProbe"]["httpGet"] == {
        "path": "/healthz",
        "port": "health",
    }
    assert container["readinessProbe"]["httpGet"] == {
        "path": "/readyz",
        "port": "health",
    }
    assert container["livenessProbe"]["httpGet"] == {
        "path": "/healthz",
        "port": "health",
    }
    assert "exec" not in container["startupProbe"]
    environment = {item["name"]: item for item in container["env"]}
    assert environment["ADAPTER_CONTROLLER_URL"]["value"] == (
        "http://edgex-adapter-controller.edgex-edge.svc.cluster.local:8080"
    )
    assert environment["ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY"]["valueFrom"][
        "secretKeyRef"
    ] == {
        "name": "edgex-adapter-management-auth",
        "key": "internal-hmac-key",
    }
    assert policy["spec"]["policyTypes"] == ["Egress"]
    assert policy["spec"]["egress"][1] == {
        "to": [
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "edgex-adapter-controller"
                    }
                }
            }
        ],
        "ports": [{"protocol": "TCP", "port": 8080}],
    }
    rendered = yaml.safe_dump_all(render()).lower()
    assert "hostnetwork: true" not in rendered
    assert "devices.devices.kubeedge.io" not in rendered
    assert "edgemesh" not in rendered


def test_node_specific_discovery_examples_target_only_the_intended_node():
    expected = {
        "discovery-agent-jetson": "etri-dev0001-jetorn",
        "discovery-agent-raspi": "etri-dev0003-raspi5",
    }
    for overlay, node_name in expected.items():
        daemon = next(
            item
            for item in render_overlay(overlay)
            if item["kind"] == "DaemonSet"
        )
        expression = daemon["spec"]["template"]["spec"]["affinity"][
            "nodeAffinity"
        ]["requiredDuringSchedulingIgnoredDuringExecution"][
            "nodeSelectorTerms"
        ][0][
            "matchExpressions"
        ][0]
        assert expression["key"] == "kubernetes.io/hostname"
        assert expression["values"] == [node_name]
