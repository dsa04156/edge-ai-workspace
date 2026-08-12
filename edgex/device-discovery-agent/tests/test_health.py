from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import urlopen

from app.health import HealthState, start_health_server


def _get(url: str) -> tuple[int, dict[str, str]]:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_health_server_separates_process_liveness_from_report_readiness():
    now = [100.0]
    state = HealthState(
        ready_window_seconds=90,
        clock=lambda: now[0],
    )
    server = start_health_server(state, host="127.0.0.1", port=0)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert _get(f"{base_url}/healthz") == (200, {"status": "ok"})
        assert _get(f"{base_url}/readyz") == (
            503,
            {"status": "not-ready"},
        )

        state.mark_report_success()
        assert _get(f"{base_url}/readyz") == (
            200,
            {"status": "ready"},
        )

        now[0] = 190.0
        assert _get(f"{base_url}/readyz") == (
            503,
            {"status": "not-ready"},
        )
        assert _get(f"{base_url}/healthz") == (200, {"status": "ok"})
        assert _get(f"{base_url}/missing") == (
            404,
            {"status": "not-found"},
        )
    finally:
        server.shutdown()
        server.server_close()
