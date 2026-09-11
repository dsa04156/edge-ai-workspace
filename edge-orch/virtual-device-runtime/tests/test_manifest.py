import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT = Path(__file__).parents[1]


def test_render_separates_test_namespace_identity_config_and_resources(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts/render.py"), "--image", "test/model@sha256:" + "a"*64,
                    "--node-selector", "kubernetes.io/hostname=approved-server",
                    "--cpu-request", "200m", "--cpu-limit", "2",
                    "--memory-request", "128Mi", "--memory-limit", "512Mi",
                    "--output", str(tmp_path)], check=True, capture_output=True)
    objects = json.loads((tmp_path / "manifest.json").read_text())["items"]
    deploy = next(o for o in objects if o["kind"] == "Deployment")
    assert deploy["metadata"]["namespace"] == "virtual-device-test"
    assert deploy["spec"]["replicas"] == 0
    spec = deploy["spec"]["template"]["spec"]
    assert spec["nodeSelector"] == {"kubernetes.io/hostname":"approved-server"}
    assert spec["automountServiceAccountToken"] is False
    container = spec["containers"][0]
    assert container["resources"]["limits"] == {"cpu":"2","memory":"512Mi"}
    assert not any("gpu" in key for section in container["resources"].values() for key in section)
    assert container["env"][0]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.uid"
    registry = json.loads((tmp_path / "virtual_devices.json").read_text())
    resource = registry["resources"][0]
    assert resource["metadata"]["name"] == "vd-demo-001"
    assert resource["spec"]["nodeSelector"] == spec["nodeSelector"]
    saved = next(o for o in objects if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "virtual-device-registry")
    assert json.loads(saved["data"]["virtual_devices.json"]) == registry
    assert not any(o["kind"] in ("ClusterRole", "RoleBinding", "CustomResourceDefinition") for o in objects)


def test_observer_has_read_only_test_namespace_permissions():
    objects = list(yaml.safe_load_all((ROOT / "k8s/observer-rbac.yaml").read_text()))
    role = objects[0]
    assert role["metadata"]["namespace"] == "virtual-device-test"
    assert all(set(rule["verbs"]) <= {"get","list"} for rule in role["rules"])
    assert "observer-rbac.yaml" not in (ROOT / "k8s/kustomization.yaml").read_text()
