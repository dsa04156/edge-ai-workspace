"""Synthetic contract fixture only; no sensor data and no claimed AI inference."""
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
inflight = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        with lock:
            count = inflight
        self.respond(200, {"ready": True, "inFlight": count,
                           "ioContract": os.environ["PLATFORM_IO_CONTRACT"]})

    def do_POST(self):
        global inflight
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 65536:
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            delay = float(body.get("delaySeconds", 0.1))
            if not math.isfinite(delay) or not 0 <= delay <= 5:
                raise ValueError()
        except (ValueError, TypeError):
            return self.respond(400, {"reason": "invalid_synthetic_input"})
        with lock:
            inflight += 1
        try:
            time.sleep(delay)
            self.respond(200, {"requestId": self.headers.get("X-Request-ID"),
                "node": os.environ.get("PLATFORM_NODE"), "ioContract": os.environ["PLATFORM_IO_CONTRACT"],
                "output": body.get("input"), "synthetic": True})
        finally:
            with lock:
                inflight -= 1


ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PLATFORM_PORT", "8080"))), Handler).serve_forever()
