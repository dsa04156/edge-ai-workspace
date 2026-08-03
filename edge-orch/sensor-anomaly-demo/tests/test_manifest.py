from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]


def render_resources() -> tuple[str, list[dict]]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(SERVICE_ROOT / "k8s")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return rendered, [item for item in yaml.safe_load_all(rendered) if item]


def resource(resources: list[dict], kind: str, name: str) -> dict:
    matches = [
        item
        for item in resources
        if item.get("kind") == kind and item.get("metadata", {}).get("name") == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_demo_workload_is_edge_local_read_only_and_bounded() -> None:
    rendered, resources = render_resources()
    deployment = resource(resources, "Deployment", "sensor-anomaly-demo")
    service = resource(resources, "Service", "sensor-anomaly-demo")
    claim = resource(resources, "PersistentVolumeClaim", "sensor-anomaly-demo-state")
    pod = deployment["spec"]["template"]
    container = pod["spec"]["containers"][0]
    env = {
        item["name"]: (
            item["value"] if "value" in item else {"valueFrom": item["valueFrom"]}
        )
        for item in container["env"]
    }

    assert deployment["metadata"]["namespace"] == "edgex-edge"
    assert pod["spec"]["nodeSelector"]["kubernetes.io/hostname"] == (
        "etri-dev0001-jetorn"
    )
    assert pod["metadata"]["labels"]["edge-ai.io/local-data-client"] == "true"
    assert re.fullmatch(
        r"192\.168\.0\.56:5000/sensor-anomaly-demo@sha256:[0-9a-f]{64}",
        container["image"],
    )
    assert env["LOCAL_DATA_BASE_URL"] == (
        "http://device-serial-jetson.edgex-edge.svc.cluster.local:59910"
    )
    assert env["POLL_INTERVAL_SECONDS"] == "0.5"
    assert env["INPUT_STALE_SECONDS"] == "10"
    assert env["CONTEXT_MAX_SKEW_SECONDS"] == "2"
    assert env["VIBRATION_WINDOW_SAMPLES"] == "20"
    assert env["TEMPERATURE_WINDOW_SAMPLES"] == "10"
    assert env["VIBRATION_WEIGHT"] == "0.7"
    assert env["TEMPERATURE_WEIGHT"] == "0.3"
    assert env["MODEL_BACKEND"] == "online-baseline"
    assert env["MODEL_VERSION"] == "baseline-1.0.0"
    assert env["SERVICE_DEVICE_ID"] == "arduino-001"
    assert env["SERVICE_ASSET_ID"] == "arduino-001"
    assert env["SERVICE_NODE_ID"] == {
        "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}}
    }
    assert env["RESULT_DB_PATH"] == "/var/lib/sensor-anomaly-demo/results.db"
    assert env["RESULT_RETENTION_ROWS"] == "100000"
    assert pod["spec"]["automountServiceAccountToken"] is False
    assert pod["spec"]["securityContext"]["fsGroup"] == 65532
    assert pod["spec"].get("hostNetwork") is not True
    assert container["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["resources"]["requests"] == {"cpu": "25m", "memory": "64Mi"}
    assert container["resources"]["limits"] == {"cpu": "250m", "memory": "128Mi"}
    assert {
        probe["httpGet"]["path"]
        for probe in (
            container["startupProbe"],
            container["readinessProbe"],
            container["livenessProbe"],
        )
    } == {"/healthz", "/readyz"}
    assert service["spec"]["ports"] == [
        {"name": "http", "port": 8080, "targetPort": "http"}
    ]
    assert "clusterIP" not in service["spec"]
    assert claim["spec"]["storageClassName"] == "local-path"
    assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert claim["spec"]["resources"]["requests"]["storage"] == "1Gi"
    volumes = {item["name"]: item for item in pod["spec"]["volumes"]}
    mounts = {item["name"]: item for item in container["volumeMounts"]}
    assert volumes["state"]["persistentVolumeClaim"]["claimName"] == (
        "sensor-anomaly-demo-state"
    )
    assert mounts["state"]["mountPath"] == "/var/lib/sensor-anomaly-demo"
    assert "hostPath:" not in rendered
    assert "hostNetwork: true" not in rendered
    assert "influx" not in rendered.lower()
    assert "mqtt" not in rendered.lower()


def test_network_policy_declares_only_dns_device_input_and_dashboard_reader() -> None:
    _, resources = render_resources()
    policy = resource(resources, "NetworkPolicy", "sensor-anomaly-demo-network")
    assert policy["spec"]["policyTypes"] == ["Ingress", "Egress"]
    ingress = policy["spec"]["ingress"]
    egress = policy["spec"]["egress"]

    assert ingress == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "default"}
                    },
                    "podSelector": {"matchLabels": {"app": "state-aggregator"}},
                }
            ],
            "ports": [{"port": 8080, "protocol": "TCP"}],
        }
    ]
    assert any(
        rule.get("ports")
        == [
            {"port": 53, "protocol": "UDP"},
            {"port": 53, "protocol": "TCP"},
        ]
        for rule in egress
    )
    assert any(
        rule.get("to")
        == [
            {
                "podSelector": {
                    "matchLabels": {"app.kubernetes.io/name": "device-serial-jetson"}
                }
            }
        ]
        and rule.get("ports") == [{"port": 59910, "protocol": "TCP"}]
        for rule in egress
    )


def test_argocd_retires_fake_vision_app_and_declares_sensor_demo_app() -> None:
    apps_text = (REPO_ROOT / "edge-orch-argocd/argocd-apps.yaml").read_text(
        encoding="utf-8"
    )
    assert "edge-orch-factory-vision-inspection-ai" not in apps_text

    application = yaml.safe_load(
        (REPO_ROOT / "edge-orch-argocd/sensor-anomaly-demo-app.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert application["metadata"] == {
        "name": "edge-orch-sensor-anomaly-demo",
        "namespace": "argocd",
    }
    assert application["spec"]["source"]["path"] == (
        "edge-orch/sensor-anomaly-demo/k8s"
    )
    assert application["spec"]["source"]["targetRevision"] == "main"
    assert application["spec"]["destination"]["namespace"] == "edgex-edge"
    assert application["spec"]["syncPolicy"]["automated"] == {
        "prune": True,
        "selfHeal": True,
    }


def test_ci_builds_and_deploys_sensor_demo_by_digest_through_argocd() -> None:
    workflow = (REPO_ROOT / ".github/workflows/docker-build-push.yml").read_text(
        encoding="utf-8"
    )

    assert '"edge-orch/sensor-anomaly-demo/**"' in workflow
    assert "sensor-anomaly-demo-build-metadata.json" in workflow
    assert "SENSOR_ANOMALY_DEMO_IMAGE=" in workflow
    assert "kubectl patch application edge-orch-sensor-anomaly-demo" in workflow
    assert "kubectl set image deployment/sensor-anomaly-demo" not in workflow
