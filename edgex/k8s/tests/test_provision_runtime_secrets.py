from __future__ import annotations

import os
import subprocess
from pathlib import Path

from test_runtime_secret_preflight import REQUIRED_SECRETS


K8S_DIR = Path(__file__).resolve().parents[1]
SCRIPT = K8S_DIR / "scripts" / "provision-runtime-secrets.sh"

FAKE_KUBECTL = """#!/bin/sh
set -eu

printf '%s\\n' "$*" >> "${PROVISION_KUBECTL_LOG:?}"

if [ "$1" = "get" ] && [ "$2" = "namespace" ]; then
    exit 0
fi

if [ "$1" = "apply" ] && [ "$2" = "-f" ]; then
    exit 0
fi

if [ "$1" = "-n" ] && [ "$3" = "get" ] && [ "$4" = "secret" ]; then
    if [ "$#" -gt 5 ]; then
        printf '%s' 'ZmFrZQ=='
    fi
    exit 0
fi

if [ "$1" = "-n" ] && [ "$3" = "create" ] \
    && [ "$4" = "secret" ] && [ "$5" = "generic" ]; then
    printf '%s\\n' 'apiVersion: v1' 'kind: Secret'
    exit 0
fi

exit 1
"""


def test_provision_script_is_syntax_valid_and_rejects_unknown_arguments() -> None:
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)

    result = subprocess.run(
        [str(SCRIPT), "--unsafe"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "usage:" in result.stderr
    assert result.stdout == ""


def test_provision_script_covers_preflight_inventory_without_literal_secrets() -> None:
    source = SCRIPT.read_text()

    for namespace, name, keys in REQUIRED_SECRETS:
        assert f"apply_secret {namespace} {name}" in source
        for key in keys:
            assert f"--from-file={key}=" in source

    assert "jetson-auth" in source
    assert "etri-dev0001-jetorn" in source
    assert "--from-literal" not in source
    assert "printf '%s' edgex" in source
    assert "random_hex" in source
    assert "tr -d '\\r\\n'" in source
    assert "printf '%s\\n' edgex" not in source
    assert "unexpectedly contains a newline" in source
    assert '"${#hex_value}" -ne 64' in source
    assert "umask 077" in source
    assert "mktemp -d" in source
    assert "trap cleanup" in source
    assert "--replace" in source
    assert "--replace-telemetry" in source
    assert "preflight-runtime-secrets.sh" in source


def test_replace_telemetry_applies_only_telemetry_secrets(tmp_path: Path) -> None:
    kubectl = tmp_path / "kubectl"
    log = tmp_path / "kubectl-calls"
    kubectl.write_text(FAKE_KUBECTL)
    kubectl.chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), "--replace-telemetry"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "KUBECTL": str(kubectl),
            "OPENSSL": "openssl",
            "PROVISION_KUBECTL_LOG": str(log),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Runtime Secret preflight passed.\n" in result.stdout
    create_calls = [
        line
        for line in log.read_text().splitlines()
        if " create secret generic " in f" {line} "
    ]
    assert {
        "edgex-telemetry-edge-auth",
        "edgex-ingest-gateway-tls",
        "edgex-edge-agent-sensehat-credentials",
        "edgex-edge-agent-sensehat-gateway-mtls",
        "edgex-edge-agent-jetson-credentials",
        "edgex-edge-agent-jetson-gateway-mtls",
    } == {
        line.split(" create secret generic ", 1)[1].split(" ", 1)[0]
        for line in create_calls
    }
    assert not any("edgex-postgres-credentials" in line for line in create_calls)
    assert not any("edgex-telemetry-plane-credentials" in line for line in create_calls)
