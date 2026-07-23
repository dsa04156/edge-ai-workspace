from __future__ import annotations

import subprocess
from pathlib import Path


K8S_DIR = Path(__file__).resolve().parents[1]
PROVISION = K8S_DIR / "scripts" / "provision-adapter-management-secrets.sh"
PREFLIGHT = K8S_DIR / "scripts" / "preflight-adapter-management-secrets.sh"


def test_secret_scripts_are_shell_valid_and_never_embed_literal_values() -> None:
    subprocess.run(["sh", "-n", str(PROVISION)], check=True)
    subprocess.run(["sh", "-n", str(PREFLIGHT)], check=True)

    provision = PROVISION.read_text()
    assert "umask 077" in provision
    assert "mktemp -d" in provision
    assert "trap cleanup" in provision
    assert "--from-file=internal-hmac-key=" in provision
    assert "--from-file=admin-token=" in provision
    assert "--from-file=management-hmac-key=" in provision
    assert "--from-literal" not in provision
    assert "edgex-edge edgex-adapter-management-auth" in provision
    assert "default edgex-adapter-management-auth" in provision
    assert "preflight-adapter-management-secrets.sh" in provision


def test_preflight_requires_shared_internal_key_and_dashboard_keys() -> None:
    source = PREFLIGHT.read_text()

    assert "default edgex-adapter-management-auth" in source
    assert "edgex-edge edgex-adapter-management-auth" in source
    assert "admin-token management-hmac-key internal-hmac-key" in source
    assert "internal HMAC keys do not match" in source
