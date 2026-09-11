"""Read-only Spark GPU metrics from the NVIDIA runtime's nvidia-smi."""
import csv
import io
import math
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

COMMAND = ["nvidia-smi", "--query-gpu=index,temperature.gpu,utilization.gpu,power.draw", "--format=csv,noheader,nounits"]
FIELDS = (
    ("spark_gpu_temperature_celsius", -50, 200),
    ("spark_gpu_utilization_percent", 0, 100),
    ("spark_gpu_power_watts", 0, 1000),
)


def parse_metrics(output: str) -> list[str]:
    lines = []
    seen = set()
    for row in csv.reader(io.StringIO(output), skipinitialspace=True):
        if not row:
            continue
        if len(row) != 4 or not row[0].strip().isdigit() or row[0].strip() in seen:
            raise ValueError("invalid_gpu_row")
        gpu = row[0].strip()
        seen.add(gpu)
        for (name, minimum, maximum), raw in zip(FIELDS, row[1:]):
            try:
                value = float(raw)
            except ValueError:
                continue  # Unsupported fields stay absent, never zero.
            if math.isfinite(value) and minimum <= value <= maximum:
                lines.append(f'{name}{{gpu="{gpu}"}} {value}')
    if not lines:
        raise ValueError("no_supported_metrics")
    return lines


def collect() -> str:
    try:
        result = subprocess.run(COMMAND, capture_output=True, text=True, check=True, timeout=3)
        lines = parse_metrics(result.stdout)
        success = 1
    except (OSError, subprocess.SubprocessError, ValueError):
        lines, success = [], 0
    headers = ["# HELP spark_gpu_collector_success Current nvidia-smi query returned usable metrics.",
               "# TYPE spark_gpu_collector_success gauge"]
    for name, _, _ in FIELDS:
        headers.extend([f"# HELP {name} Current device observation from nvidia-smi.", f"# TYPE {name} gauge"])
    return "\n".join(headers + [f"spark_gpu_collector_success {success}"] + lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            status, body = 200, "ok\n"
        elif self.path == "/metrics":
            status, body = 200, collect()
        else:
            status, body = 404, "not found\n"
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9402), Handler).serve_forever()
