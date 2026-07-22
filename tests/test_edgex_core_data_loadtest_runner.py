import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "tools" / "run_edgex_core_data_loadtest.sh"


def script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_runner_defaults_to_1000_devices_at_one_hz():
    text = script()
    assert 'DEVICES="${DEVICES:-1000}"' in text
    assert 'PER_DEVICE_HZ="${PER_DEVICE_HZ:-1}"' in text
    assert 'DURATION="${DURATION:-60s}"' in text
    assert 'CONCURRENCY="${CONCURRENCY:-128}"' in text


def test_runner_executes_inside_server2_with_service_dns():
    text = script()
    assert "edgex-core-data.edgex-system.svc.cluster.local:59880" in text
    assert "kubernetes.io/hostname: etri-ser0002-cgnmsb" in text
    assert "automountServiceAccountToken: false" in text
    assert "emptyDir: {}" in text
    assert "kubectl cp" in text
    assert "CGO_ENABLED=0 GOOS=linux GOARCH=amd64" in text


def test_runner_uses_a_pinned_unprivileged_ephemeral_image():
    text = script()
    assert re.search(r"image: busybox:1\.36\.1@sha256:[0-9a-f]{64}", text)
    assert "runAsNonRoot: true" in text
    assert "runAsUser: 65534" in text
    assert "allowPrivilegeEscalation: false" in text
    assert "readOnlyRootFilesystem: true" in text
    assert "seccompProfile:" in text
    assert "type: RuntimeDefault" in text


def test_runner_cleans_only_its_run_scoped_pod_and_keeps_json_report():
    text = script()
    assert 'POD_NAME="edgex-core-data-loadtest-${RUN_ID}"' in text
    assert 'kubectl -n "$NAMESPACE" delete pod "$POD_NAME"' in text
    assert 'KEEP_RESOURCES="${KEEP_RESOURCES:-0}"' in text
    assert "trap cleanup EXIT INT TERM" in text
    assert 'REPORT_DIR="$ROOT_DIR/artifacts/edgex-loadtest"' in text
    assert 'LATEST_REPORT="$REPORT_DIR/latest.json"' in text


def test_generated_load_reports_are_not_tracked_as_source():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/artifacts/edgex-loadtest/" in gitignore


def test_runner_does_not_use_fixed_network_addresses_or_mutate_operating_manifests():
    text = script()
    assert "192.168." not in text
    assert "clusterIP" not in text
    assert "edgemesh" not in text.lower()
    assert "kubectl patch" not in text
    assert "kubectl scale" not in text

    root_kustomization = (ROOT / "edgex" / "k8s" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "loadtest" not in root_kustomization.lower()
