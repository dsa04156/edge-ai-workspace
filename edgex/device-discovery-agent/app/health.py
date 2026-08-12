from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Callable


class HealthState:
    def __init__(
        self,
        *,
        ready_window_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ready_window_seconds = ready_window_seconds
        self.clock = clock
        self._lock = Lock()
        self._last_report_success: float | None = None

    def mark_report_success(self) -> None:
        with self._lock:
            self._last_report_success = self.clock()

    def is_ready(self) -> bool:
        with self._lock:
            last_success = self._last_report_success
        return (
            last_success is not None
            and self.clock() - last_success < self.ready_window_seconds
        )


def _handler_for(state: HealthState) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._respond(200, {"status": "ok"})
                return
            if self.path == "/readyz":
                ready = state.is_ready()
                self._respond(
                    200 if ready else 503,
                    {"status": "ready" if ready else "not-ready"},
                )
                return
            self._respond(404, {"status": "not-found"})

        def _respond(self, status: int, payload: dict[str, str]) -> None:
            body = json.dumps(
                payload,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return HealthHandler


def start_health_server(
    state: HealthState,
    *,
    port: int,
    host: str = "0.0.0.0",
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _handler_for(state))
    server.daemon_threads = True
    thread = Thread(
        target=server.serve_forever,
        name="discovery-health-server",
        daemon=True,
    )
    thread.start()
    return server
