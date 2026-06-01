from __future__ import annotations

import shlex
import subprocess
from typing import Any


BLOCKED_TOKENS = {
    "apply",
    "delete",
    "patch",
    "label",
    "annotate",
    "scale",
    "rollout",
    "restart",
    "replace",
    "cordon",
    "drain",
    "uncordon",
}


def run_shell(command: str) -> dict[str, Any]:
    """테스트용이며 운영 전 제거/분리 필요.

    This helper is intentionally restricted. It must not run deletion, restart,
    deployment mutation, scale, rollout, apply, delete, patch, label, or
    annotate commands.
    """

    try:
        tokens = {token.lower() for token in shlex.split(command)}
    except ValueError as exc:
        return {"error": f"invalid command: {exc}"}

    if tokens & BLOCKED_TOKENS:
        return {
            "command": command,
            "blocked": True,
            "error": "mutating operations are blocked in this initial version",
        }

    completed = subprocess.run(
        command,
        shell=True,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[:20000],
        "stderr": completed.stderr[:20000],
    }
