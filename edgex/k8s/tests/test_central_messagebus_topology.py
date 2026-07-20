from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1]
ARGO_APPLICATIONS = K8S_DIR.parents[1] / "edge-orch-argocd" / "argocd-apps.yaml"
CENTRAL_NODE = "etri-ser0002-cgnmsb"
EDGE_PLACEMENT = {
    "edgex-device-mqtt": "etri-dev0001-jetorn",
    "edgex-device-mqtt-sensehat": "etri-dev0003-raspi5",
}
CENTRAL_WORKLOADS = {
    "edgex-core-keeper",
    "edgex-core-common-config-bootstrapper",
    "edgex-core-data",
    "edgex-core-metadata",
    "edgex-core-command",
    "edgex-messagebus",
    "edgex-postgres",
}


def render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(K8S_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def pod_spec(resource: dict[str, Any]) -> dict[str, Any]:
    return resource["spec"]["template"]["spec"]


def workloads() -> dict[str, dict[str, Any]]:
    return {
        resource["metadata"]["name"]: resource
        for resource in render()
        if resource["kind"] in {"Deployment", "StatefulSet", "Job"}
    }


def test_central_workloads_run_only_on_server2() -> None:
    rendered = workloads()
    assert CENTRAL_WORKLOADS <= rendered.keys()
    for name in CENTRAL_WORKLOADS:
        assert pod_spec(rendered[name])["nodeSelector"] == {
            "kubernetes.io/hostname": CENTRAL_NODE
        }


def test_device_services_remain_on_the_sensor_edges() -> None:
    rendered = workloads()
    for name, node in EDGE_PLACEMENT.items():
        assert pod_spec(rendered[name])["nodeSelector"] == {
            "kubernetes.io/hostname": node
        }


def test_core_images_are_amd64_and_device_images_are_arm64() -> None:
    rendered = workloads()
    for name in CENTRAL_WORKLOADS:
        containers = [
            *pod_spec(rendered[name]).get("initContainers", []),
            *pod_spec(rendered[name]).get("containers", []),
        ]
        for container in containers:
            image = container["image"]
            if "edgexfoundry/" in image:
                assert ":4.0.2" in image
                assert "-arm64" not in image
    for name in EDGE_PLACEMENT:
        assert pod_spec(rendered[name])["containers"][0]["image"] == (
            "edgexfoundry/device-mqtt-arm64:4.0.2"
        )


def test_edge_has_no_local_core_messagebus_or_database() -> None:
    rendered = workloads()
    edge_nodes = set(EDGE_PLACEMENT.values())
    for name, resource in rendered.items():
        node = pod_spec(resource).get("nodeSelector", {}).get(
            "kubernetes.io/hostname"
        )
        if node in edge_nodes:
            assert name in EDGE_PLACEMENT


def test_internal_messagebus_is_cluster_only() -> None:
    service = next(
        item
        for item in render()
        if item["kind"] == "Service"
        and item["metadata"]["name"] == "edgex-messagebus"
    )
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [
        {"name": "mqtt", "port": 1883, "targetPort": "mqtt"}
    ]


def test_device_services_use_the_central_configuration_and_registry() -> None:
    rendered = workloads()
    for name in EDGE_PLACEMENT:
        args = pod_spec(rendered[name])["containers"][0]["args"]
        assert "-cp=keeper.http://edgex-core-keeper:59890" in args
        assert "--registry" in args


def test_argocd_owns_edgex_but_not_the_legacy_mapper() -> None:
    applications = {
        resource["metadata"]["name"]: resource
        for resource in yaml.safe_load_all(ARGO_APPLICATIONS.read_text())
        if resource and resource.get("kind") == "Application"
    }

    assert "edge-orch-mqttvirtual-mapper" not in applications
    edgex = applications["edgex-telemetry"]
    assert edgex["spec"]["source"]["path"] == "edgex/k8s"
    assert edgex["spec"]["destination"]["namespace"] == "telemetry"
