from __future__ import annotations

import subprocess
from pathlib import Path

from test_runtime_secret_preflight import REQUIRED_SECRETS


K8S_DIR = Path(__file__).resolve().parents[1]
SCRIPT = K8S_DIR / "scripts" / "provision-runtime-secrets.sh"


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

    assert "jetson" not in source
    assert '"etri-dev0001-jetorn"' not in source
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
    assert "preflight-runtime-secrets.sh" in source
