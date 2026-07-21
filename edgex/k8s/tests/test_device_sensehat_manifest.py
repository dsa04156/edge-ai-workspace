from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


K8S_DIR = Path(__file__).resolve().parents[1]
DEVICE_SERVICE_DIR = K8S_DIR.parents[0] / "device-sensehat"
BASE_DIR = K8S_DIR / "base" / "device-sensehat-raspi"
PROFILE_FILES = (
    "etri-sensehat-temperature.yaml",
    "etri-sensehat-humidity.yaml",
    "etri-sensehat-pressure.yaml",
    "etri-sensehat-compass.yaml",
    "etri-sensehat-orientation.yaml",
    "etri-sensehat-gyroscope.yaml",
)


def render(path: Path = BASE_DIR) -> list[dict[str, Any]]:
    result = subprocess.run(
        [os.environ.get("KUBECTL", "kubectl"), "kustomize", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def named(resources: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(item["kind"], item["metadata"]["name"]): item for item in resources}


def pod_spec(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]


def test_sensehat_configmap_matches_canonical_sdk_resources() -> None:
    resources = render()
    configmaps = [
        item
        for item in resources
        if item["kind"] == "ConfigMap"
        and item["metadata"]["name"].startswith("device-sensehat-raspi-config-")
    ]
    assert len(configmaps) == 1
    expected = {
        "configuration.yaml": (DEVICE_SERVICE_DIR / "res" / "configuration.yaml").read_text(),
        **{
            filename: (DEVICE_SERVICE_DIR / "res" / "profiles" / filename).read_text()
            for filename in PROFILE_FILES
        },
        "sensehat-virtual-devices.yaml": (
            DEVICE_SERVICE_DIR / "res" / "devices" / "sensehat-virtual-devices.yaml"
        ).read_text(),
    }
    assert configmaps[0]["data"] == expected


def test_sensehat_deployment_owns_only_exact_i2c_device_on_raspberry_pi() -> None:
    resources = named(render())
    deployment = resources[("Deployment", "device-sensehat-raspi")]
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}
    pod = pod_spec(deployment)
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "etri-dev0003-raspi5"}
    assert pod["automountServiceAccountToken"] is False
    assert pod.get("hostNetwork", False) is False
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert len(pod["containers"]) == 1
    container = pod["containers"][0]
    assert container["name"] == "device-sensehat-raspi"
    assert re.fullmatch(
        r"192\.168\.0\.56:5000/edgex-device-sensehat@sha256:[0-9a-f]{64}",
        container["image"],
    )
    assert container["securityContext"] == {
        "privileged": True,
        "allowPrivilegeEscalation": True,
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": False,
        "runAsUser": 0,
        "runAsGroup": 0,
    }
    i2c_volume = next(volume for volume in pod["volumes"] if volume["name"] == "sensehat-i2c")
    assert i2c_volume["hostPath"] == {"path": "/dev/i2c-1", "type": "CharDevice"}
    i2c_mount = next(mount for mount in container["volumeMounts"] if mount["name"] == "sensehat-i2c")
    assert i2c_mount == {"name": "sensehat-i2c", "mountPath": "/dev/i2c-1"}
    assert any(volume["name"] == "tmp" and volume["emptyDir"] == {} for volume in pod["volumes"])
    assert not any("mqtt" in str(value).lower() for value in container.get("env", []))


def test_sensehat_service_uses_fqdns_without_fixed_ips() -> None:
    resources = named(render())
    deployment = resources[("Deployment", "device-sensehat-raspi")]
    container = pod_spec(deployment)["containers"][0]
    assert container["args"] == [
        "-cp=keeper.http://edgex-core-keeper.edgex-system.svc.cluster.local:59890",
        "-cd=/res",
    ]
    environment = {item["name"]: item["value"] for item in container["env"]}
    assert environment == {
        "EDGEX_SECURITY_SECRET_STORE": "false",
        "SERVICE_HOST": "device-sensehat-raspi.edgex-edge.svc.cluster.local",
        "SERVICE_SERVERBINDADDR": "0.0.0.0",
        "CLIENTS_CORE_METADATA_HOST": "edgex-core-metadata.edgex-system.svc.cluster.local",
        "MESSAGEBUS_HOST": "edgex-messagebus.edgex-system.svc.cluster.local",
    }
    routed_values = [
        *container["args"],
        *(value for name, value in environment.items() if name != "SERVICE_SERVERBINDADDR"),
    ]
    assert not any(
        re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", value) for value in routed_values
    )
    service = resources[("Service", "device-sensehat-raspi")]
    assert service["spec"]["type"] == "ClusterIP"
    assert "clusterIP" not in service["spec"]
    assert service["spec"]["ports"] == [{"name": "http", "port": 59911, "targetPort": "http"}]


def test_sensehat_network_policy_declares_current_boundaries() -> None:
    resources = named(render())
    egress = resources[("NetworkPolicy", "device-sensehat-raspi-egress")]["spec"]
    assert egress["policyTypes"] == ["Egress"]
    assert {port["port"] for rule in egress["egress"] for port in rule["ports"]} == {53, 1883, 59881, 59890}
    ingress = resources[("NetworkPolicy", "device-sensehat-raspi-ingress")]["spec"]
    assert ingress["policyTypes"] == ["Ingress"]
    assert all(port == {"protocol": "TCP", "port": 59911} for rule in ingress["ingress"] for port in rule["ports"])
    workflow_rule = next(
        rule
        for rule in ingress["ingress"]
        if any("podSelector" in source for source in rule["from"])
    )
    assert workflow_rule["from"] == [
        {
            "namespaceSelector": {},
            "podSelector": {"matchLabels": {"edge-ai.io/local-data-client": "true"}},
        }
    ]


def test_sensehat_runtime_base_is_pinned_and_has_no_mqtt_client() -> None:
    dockerfile = (DEVICE_SERVICE_DIR / "Dockerfile.base").read_text()
    assert "python3-rtimulib_7.2.1-7_arm64.deb" in dockerfile
    assert "librtimulib7_7.2.1-7_arm64.deb" in dockerfile
    assert "67b25a603ae136c4b4d7877a3639e5bf7f0d333dbf7d6d5b47428a76addae357" in dockerfile
    assert "f40afd613a6f8ed589948cd713b50ae0bb20e74c13e663ac756deb640a7b69a2" in dockerfile
    assert "sha256sum --check --strict" in dockerfile
    assert "read_sensehat.py" in dockerfile
    assert "mosquitto" not in dockerfile.lower()
    ko_config = yaml.safe_load((DEVICE_SERVICE_DIR / ".ko.yaml").read_text())
    assert re.fullmatch(
        r"192\.168\.0\.56:5000/edgex-device-sensehat-base@sha256:[0-9a-f]{64}",
        ko_config["defaultBaseImage"],
    )
    assert ko_config["defaultPlatforms"] == ["linux/arm64"]
