from __future__ import annotations

import os
import subprocess
from pathlib import Path


K8S_DIR = Path(__file__).resolve().parents[1]
SCRIPT = K8S_DIR / "scripts" / "rebuild-central-messagebus.sh"


def run_script(tmp_path: Path, *arguments: str) -> list[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "calls.log"
    fake_rtk = bin_dir / "rtk"
    fake_rtk.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'printf "%s\\n" "$*" >>"$REBUILD_TEST_LOG"\n'
    )
    fake_rtk.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
    environment["REBUILD_TEST_LOG"] = str(log_path)
    subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        cwd=K8S_DIR.parents[1],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return log_path.read_text().splitlines()


def test_default_mode_never_deletes_or_applies_live_resources(tmp_path: Path) -> None:
    calls = run_script(tmp_path)
    assert calls == [
        "kubectl config current-context",
        "kubectl get nodes -o wide",
        "kubectl kustomize edgex/k8s",
        "kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml",
    ]
    assert not any("delete" in call for call in calls)
    assert "kubectl apply -k edgex/k8s" not in calls


def test_execute_validates_nodes_and_dry_run_before_exact_namespace_delete(
    tmp_path: Path,
) -> None:
    calls = run_script(tmp_path, "--execute")
    delete_call = "kubectl delete namespace telemetry --ignore-not-found=true --wait=true --timeout=300s"
    assert delete_call in calls
    delete_index = calls.index(delete_call)
    for required_call in (
        "kubectl get node etri-ser0002-cgnmsb",
        "kubectl get node etri-dev0001-jetorn",
        "kubectl get node etri-dev0003-raspi5",
        "kubectl apply --dry-run=server -f /tmp/edgex-central-messagebus.yaml",
    ):
        assert required_call in calls[:delete_index]
    assert calls[delete_index + 1] == "kubectl apply -k edgex/k8s"
