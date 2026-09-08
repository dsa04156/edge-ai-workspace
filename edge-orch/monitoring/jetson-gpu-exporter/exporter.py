"""Read-only Jetson GPU load exporter; no driver/control operations."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOAD = Path("/host-gpu/load")


def parse_load(text):
    value = int(text.strip())
    if not 0 <= value <= 1000:
        raise ValueError("GPU load outside driver range")
    return value / 1000.0


def metrics(path=LOAD):
    lines = ["# HELP jetson_gpu_collector_success GPU load read succeeded.",
             "# TYPE jetson_gpu_collector_success gauge"]
    try:
        value = parse_load(path.read_text())
    except (OSError, ValueError):
        return "\n".join(lines + ["jetson_gpu_collector_success 0", ""])
    return "\n".join(lines + ["jetson_gpu_collector_success 1",
        "# HELP jetson_gpu_utilization_ratio Jetson driver GPU load (0..1), not GPU memory allocation.",
        "# TYPE jetson_gpu_utilization_ratio gauge",
        f"jetson_gpu_utilization_ratio {value}", ""])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/metrics", "/healthz"}:
            self.send_error(404)
            return
        body = (metrics() if self.path == "/metrics" else "ok\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9401), Handler).serve_forever()
