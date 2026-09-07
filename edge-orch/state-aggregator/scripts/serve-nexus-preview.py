"""Serve the NEXUS workspace with a bounded GET-only testbed read proxy."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener
import json

STATIC = Path(__file__).resolve().parents[1] / "app/static"
UPSTREAM = "http://aggregator.192.168.0.56.sslip.io"
OPENER = build_opener(ProxyHandler({}))

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def respond(self, status, payload, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path.startswith(("/state/", "/api/", "/management/")):
            try:
                with OPENER.open(Request(UPSTREAM + self.path, headers={"Accept": "application/json"}), timeout=18) as response:
                    self.respond(response.status, response.read(), response.headers.get("Content-Type", "application/json"))
            except HTTPError as error:
                self.respond(error.code, error.read())
            except (URLError, TimeoutError, OSError):
                self.respond(502, json.dumps({"detail": "Testbed observation unavailable"}).encode())
            return
        if parsed.path in ("/", "/dashboard"):
            self.path = "/nexus/index.html"
        elif parsed.path == "/classic":
            self.path = "/index.html"
        elif parsed.path.startswith("/static/"):
            self.path = parsed.path.removeprefix("/static")
        super().do_GET()

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8769), Handler).serve_forever()
