from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1]
DEVICE_SERVICE_DIR = K8S_DIR.parents[0] / "device-serial"
STABLE_ARDUINO_PATH = (
    "/dev/serial/by-id/"
    "usb-Arduino__www.arduino.cc__0043_75035303230351E0D171-if00"
)
IMAGE = (
    "192.168.0.56:5000/edgex-device-serial@"
    "sha256:4c933c3d8827dec325055634ed196380690c4748362fecb3f9676b412e724b71"
)
CENTRAL_FQDNS = {
    "edgex-core-keeper.edgex-system.svc.cluster.local",
    "edgex-core-metadata.edgex-system.svc.cluster.local",
    "edgex-messagebus.edgex-system.svc.cluster.local",
}


def render(path: Path = K8S_DIR) -> list[dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def named(resources: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (resource["kind"], resource["metadata"]["name"]): resource
        for resource in resources
    }


def find_generated_configmap(resources: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        resource
        for resource in resources
        if resource["kind"] == "ConfigMap"
        and resource["metadata"]["name"].startswith("device-serial-jetson-config-")
    ]
    assert len(matches) == 1
    return matches[0]


def pod_spec(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]


def test_root_entrypoint_adds_only_the_current_serial_and_i2c_edge_workloads() -> None:
    root = yaml.safe_load((K8S_DIR / "kustomization.yaml").read_text())
    assert root["resources"] == [
        "overlays/testbed/server2",
        "base/edge-namespace",
        "base/device-serial-jetson",
        "base/device-sensehat-raspi",
    ]

    resources = render()
    edge_workloads = [
        resource
        for resource in resources
        if resource["kind"] in {"Deployment", "StatefulSet", "Job"}
        and pod_spec(resource).get("nodeSelector", {}).get("kubernetes.io/hostname")
        in {"etri-dev0001-jetorn", "etri-dev0002-raspi5", "etri-dev0003-raspi5"}
    ]
    assert sorted(resource["metadata"]["name"] for resource in edge_workloads) == [
        "device-sensehat-raspi",
        "device-serial-jetson",
    ]
    assert not [resource for resource in resources if resource["kind"] == "PersistentVolumeClaim"]


def test_serial_configmap_is_identical_to_canonical_sdk_resources() -> None:
    resources = render(K8S_DIR / "base/device-serial-jetson")
    configmap = find_generated_configmap(resources)
    expected = {
        "configuration.yaml": DEVICE_SERVICE_DIR.joinpath("res/configuration.yaml").read_text(),
        **{
            filename: DEVICE_SERVICE_DIR.joinpath("res/profiles", filename).read_text()
            for filename in (
                "etri-arduino-temperature.yaml",
                "etri-arduino-light.yaml",
                "etri-arduino-magnetic.yaml",
                "etri-arduino-acceleration-x.yaml",
                "etri-arduino-acceleration-y.yaml",
                "etri-arduino-acceleration-z.yaml",
            )
        },
        "arduino-virtual-devices.yaml": DEVICE_SERVICE_DIR.joinpath(
            "res/devices/arduino-virtual-devices.yaml"
        ).read_text(),
    }
    assert configmap["data"] == expected


def test_serial_deployment_mounts_only_virtual_device_resources() -> None:
    resources = named(render(K8S_DIR / "base/device-serial-jetson"))
    deployment = resources[("Deployment", "device-serial-jetson")]
    service_config = next(
        volume
        for volume in pod_spec(deployment)["volumes"]
        if volume["name"] == "service-config"
    )
    assert service_config["configMap"]["items"] == [
        {"key": "configuration.yaml", "path": "configuration.yaml"},
        {"key": "etri-arduino-temperature.yaml", "path": "profiles/etri-arduino-temperature.yaml"},
        {"key": "etri-arduino-light.yaml", "path": "profiles/etri-arduino-light.yaml"},
        {"key": "etri-arduino-magnetic.yaml", "path": "profiles/etri-arduino-magnetic.yaml"},
        {"key": "etri-arduino-acceleration-x.yaml", "path": "profiles/etri-arduino-acceleration-x.yaml"},
        {"key": "etri-arduino-acceleration-y.yaml", "path": "profiles/etri-arduino-acceleration-y.yaml"},
        {"key": "etri-arduino-acceleration-z.yaml", "path": "profiles/etri-arduino-acceleration-z.yaml"},
        {"key": "arduino-virtual-devices.yaml", "path": "devices/arduino-virtual-devices.yaml"},
    ]


def test_serial_deployment_has_one_narrow_privileged_device_exception() -> None:
    resources = named(render(K8S_DIR / "base/device-serial-jetson"))
    deployment = resources[("Deployment", "device-serial-jetson")]
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    pod = pod_spec(deployment)
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "etri-dev0001-jetorn"}
    assert pod["automountServiceAccountToken"] is False
    assert pod.get("hostNetwork", False) is False
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert len(pod["containers"]) == 1
    container = pod["containers"][0]
    assert container["name"] == "device-serial-jetson"
    assert container["image"] == IMAGE
    assert container["securityContext"] == {
        "privileged": True,
        "allowPrivilegeEscalation": True,
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": False,
        "runAsUser": 0,
        "runAsGroup": 0,
    }
    serial_volume = next(
        volume for volume in pod["volumes"] if volume["name"] == "arduino-serial"
    )
    assert serial_volume["hostPath"] == {
        "path": STABLE_ARDUINO_PATH,
        "type": "CharDevice",
    }
    serial_mount = next(
        mount for mount in container["volumeMounts"] if mount["name"] == "arduino-serial"
    )
    assert serial_mount == {
        "name": "arduino-serial",
        "mountPath": "/dev/arduino-001",
    }


def test_serial_service_uses_edgemesh_fqdns_without_registry_short_names() -> None:
    resources = named(render(K8S_DIR / "base/device-serial-jetson"))
    deployment = resources[("Deployment", "device-serial-jetson")]
    container = pod_spec(deployment)["containers"][0]
    assert container["args"] == [
        "-cp=keeper.http://edgex-core-keeper.edgex-system.svc.cluster.local:59890",
        "-cd=/res",
    ]
    assert "--registry" not in container["args"]
    environment = {item["name"]: item["value"] for item in container["env"]}
    assert environment == {
        "EDGEX_SECURITY_SECRET_STORE": "false",
        "SERVICE_HOST": "device-serial-jetson.edgex-edge.svc.cluster.local",
        "SERVICE_SERVERBINDADDR": "0.0.0.0",
        "CLIENTS_CORE_METADATA_HOST": (
            "edgex-core-metadata.edgex-system.svc.cluster.local"
        ),
        "MESSAGEBUS_HOST": "edgex-messagebus.edgex-system.svc.cluster.local",
    }
    configured_hosts = {
        match.group(0)
        for value in [*container["args"], *environment.values()]
        for match in re.finditer(r"[a-z0-9-]+\.edgex-system\.svc\.cluster\.local", value)
    }
    assert configured_hosts == CENTRAL_FQDNS
    assert not any(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", value) for value in container["args"])

    service = resources[("Service", "device-serial-jetson")]
    assert service["spec"]["type"] == "ClusterIP"
    assert "clusterIP" not in service["spec"]
    assert service["spec"]["ports"] == [
        {"name": "http", "port": 59910, "targetPort": "http"}
    ]


def test_serial_network_policies_limit_both_namespace_boundaries() -> None:
    edge = named(render(K8S_DIR / "base/device-serial-jetson"))
    egress = edge[("NetworkPolicy", "device-serial-jetson-egress")]["spec"]
    assert egress["podSelector"] == {
        "matchLabels": {"app.kubernetes.io/name": "device-serial-jetson"}
    }
    assert egress["policyTypes"] == ["Egress"]
    assert egress["egress"][0] == {
        "to": [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                }
            }
        ],
        "ports": [
            {"protocol": "UDP", "port": 53},
            {"protocol": "TCP", "port": 53},
        ],
    }
    central_rule = egress["egress"][1]
    assert central_rule["to"] == [
        {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "edgex-system"}
            },
            "podSelector": {
                "matchExpressions": [
                    {
                        "key": "app.kubernetes.io/name",
                        "operator": "In",
                        "values": [
                            "edgex-core-keeper",
                            "edgex-core-metadata",
                            "edgex-messagebus",
                        ],
                    }
                ]
            },
        }
    ]
    assert central_rule["ports"] == [
        {"protocol": "TCP", "port": 59890},
        {"protocol": "TCP", "port": 59881},
        {"protocol": "TCP", "port": 1883},
    ]

    ingress = edge[("NetworkPolicy", "device-serial-jetson-ingress")]["spec"]
    assert ingress["policyTypes"] == ["Ingress"]
    assert ingress["ingress"] == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": "edgex-system"
                        }
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 59910}],
        },
        {
            "from": [
                {
                    "namespaceSelector": {},
                    "podSelector": {
                        "matchLabels": {
                            "edge-ai.io/local-data-client": "true"
                        }
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 59910}],
        },
    ]

    server = named(render(K8S_DIR / "base/server"))
    central = server[("NetworkPolicy", "edgex-device-service-ingress")]["spec"]
    assert central["podSelector"]["matchExpressions"][0]["values"] == [
        "edgex-core-keeper",
        "edgex-core-metadata",
        "edgex-messagebus",
    ]
    assert central["ingress"] == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "edgex-edge"}
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "device-serial-jetson"
                        }
                    },
                }
            ],
            "ports": [
                {"protocol": "TCP", "port": 59890},
                {"protocol": "TCP", "port": 59881},
                {"protocol": "TCP", "port": 1883},
            ],
        }
    ]
