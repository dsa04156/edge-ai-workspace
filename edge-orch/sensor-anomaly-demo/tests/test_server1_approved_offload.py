from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "k8s-overlays" / "server1-approved-offload"


def _render() -> tuple[str, list[dict]]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return rendered, [item for item in yaml.safe_load_all(rendered) if item]


def _resource(resources: list[dict], kind: str, name: str) -> dict:
    return next(
        item
        for item in resources
        if item.get("kind") == kind and item.get("metadata", {}).get("name") == name
    )


def test_approved_overlay_is_inactive_and_requires_external_approval_secret() -> None:
    active = yaml.safe_load((ROOT / "k8s" / "kustomization.yaml").read_text())
    rendered, resources = _render()
    deployment = _resource(resources, "Deployment", "sensor-anomaly-demo")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert "server1-approved-offload" not in active["resources"]
    assert not any(item["kind"] == "Secret" for item in resources)
    assert env["REMOTE_INFERENCE_MODE"]["value"] == "approved"
    assert env["REMOTE_INFERENCE_INITIAL_TARGET"]["value"] == "local"
    assert env["REMOTE_INFERENCE_URL"]["value"] == (
        "http://sensor-anomaly-inference-server1.edgex-edge.svc.cluster.local:8080"
    )
    assert env["REMOTE_INFERENCE_APPROVAL_ID"]["valueFrom"]["secretKeyRef"] == {
        "name": "sensor-anomaly-augmentation-approval",
        "key": "approval-id",
    }
    assert env["REMOTE_INFERENCE_CONTROL_TOKEN"]["valueFrom"]["secretKeyRef"] == {
        "name": "sensor-anomaly-augmentation-approval",
        "key": "control-token",
    }
    assert env["REMOTE_INFERENCE_NODE"]["value"] == "etri-ser0002-cgnmsb"
    assert env["REMOTE_INFERENCE_MODEL_VERSION"]["value"] == "cuda-baseline-1.0.0"
    assert env["REMOTE_INFERENCE_LATENCY_THRESHOLD_MS"]["value"] == "250"
    assert env["REMOTE_INFERENCE_LATENCY_FAILURE_THRESHOLD"]["value"] == "3"
    assert "approval-id:" not in rendered


def test_approved_overlay_adds_only_the_server1_inference_egress() -> None:
    _, resources = _render()
    policy = _resource(resources, "NetworkPolicy", "sensor-anomaly-demo-network")
    egress = policy["spec"]["egress"]

    assert any(
        rule.get("to")
        == [
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": (
                            "sensor-anomaly-inference-server1"
                        )
                    }
                }
            }
        ]
        and rule.get("ports") == [{"port": 8080, "protocol": "TCP"}]
        for rule in egress
    )
    # Base policy includes DNS, EdgeX input and the Lease API. This overlay
    # contributes only the server1 inference destination.
    assert len(egress) == 4
