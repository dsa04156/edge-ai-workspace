import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_crd_matches_runtime_schema():
    spec = importlib.util.spec_from_file_location("crd_generator", ROOT / "scripts/generate-crd.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert yaml.safe_load((ROOT / "k8s/crd.yaml").read_text()) == module.generate()


def test_mutations_are_namespace_scoped_and_no_secret_or_node_write():
    resources = list(yaml.safe_load_all((ROOT / "k8s/rbac.yaml").read_text()))
    role = next(r for r in resources if r["kind"] == "Role")
    cluster = next(r for r in resources if r["kind"] == "ClusterRole")
    assert role["metadata"]["namespace"] == "platform-runtime"
    assert all(set(rule["verbs"]) <= {"get", "list"} for rule in cluster["rules"])
    assert not any("secrets" in rule["resources"] or "pods/exec" in rule["resources"] for rule in role["rules"])


def test_one_writer_with_persistent_journal_and_no_public_ingress():
    resources = list(yaml.safe_load_all((ROOT / "k8s/operator.yaml").read_text()))
    deployment = next(r for r in resources if r["kind"] == "Deployment")
    assert deployment["spec"]["replicas"] == 1 and deployment["spec"]["strategy"]["type"] == "Recreate"
    pod = deployment["spec"]["template"]["spec"]
    assert pod["volumes"][0]["persistentVolumeClaim"]["claimName"] == "runtime-journal"
    assert "@sha256:" in pod["containers"][0]["image"]
    assert not any(r["kind"] == "Ingress" for r in resources)


def test_examples_have_no_fixed_node_or_order_and_distinct_service_contracts():
    resources = list(yaml.safe_load_all((ROOT / "demo/services.yaml").read_text()))
    assert len({r["spec"]["ioContract"] for r in resources}) == 2
    text = (ROOT / "demo/services.yaml").read_text()
    assert "etri-" not in text and "execution_order" not in text and "hostname" not in text
