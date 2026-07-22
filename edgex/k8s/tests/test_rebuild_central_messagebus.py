from __future__ import annotations

import os
import subprocess
from pathlib import Path


K8S_DIR = Path(__file__).resolve().parents[1]
SCRIPT = K8S_DIR / "scripts" / "rebuild-central-messagebus.sh"


def test_legacy_messagebus_rebuild_script_is_fail_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "rtk-calls.log"
    fake_rtk = bin_dir / "rtk"
    fake_rtk.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >>'{call_log}'\n"
    )
    fake_rtk.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{bin_dir}:{environment['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPT), "--execute"],
        cwd=K8S_DIR.parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "폐기" in result.stderr
    assert "edgex/k8s" in result.stderr
    assert not call_log.exists()
