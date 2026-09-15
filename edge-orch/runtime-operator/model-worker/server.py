"""Real CPU inference on a trained model; bounded JSON Open Inference Protocol V2."""
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAW = (Path(__file__).parent / "model.json").read_bytes()
MODEL = json.loads(RAW)
VERSION = hashlib.sha256(RAW).hexdigest()
NAME = MODEL["model_name"]
INPUTS = [{"name": "pixels", "datatype": "FP32", "shape": [1, 64]}]
OUTPUTS = [{"name": "class", "datatype": "INT64", "shape": [1]},
           {"name": "squared_distances", "datatype": "FP64", "shape": [1, 10]}]
lock = threading.Lock()
inflight = 0
draining = False


def infer(body):
    if not isinstance(body, dict) or set(body) - {"id", "inputs"}:
        raise ValueError("invalid_request")
    inputs = body.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1:
        raise ValueError("one_image_required")
    tensor = inputs[0]
    if not isinstance(tensor, dict) or set(tensor) != {"name", "datatype", "shape", "data"}:
        raise ValueError("invalid_tensor")
    if any(tensor.get(key) != value for key, value in INPUTS[0].items()):
        raise ValueError("image_shape_or_datatype_mismatch")
    pixels = tensor["data"]
    if (not isinstance(pixels, list) or len(pixels) != 64
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 16 for v in pixels)):
        raise ValueError("pixels_must_be_64_finite_values_between_0_and_16")
    distances = [sum((v - c) ** 2 for v, c in zip(pixels, centroid)) for centroid in MODEL["centroids"]]
    label = min(range(10), key=distances.__getitem__)
    return {"model_name": NAME, "model_version": VERSION, "id": body.get("id", ""),
            "outputs": [{**OUTPUTS[0], "data": [label]}, {**OUTPUTS[1], "data": distances}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, body):
        encoded = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The completed inference remains an unknown outcome to a disconnected caller.

    def do_GET(self):
        with lock:
            active, stopping = inflight, draining
        metadata = {"model_name": NAME, "model_version": VERSION, "inputs": INPUTS, "outputs": OUTPUTS}
        if self.path == "/ready":
            return self.respond(503 if stopping else 200, {**metadata, "ready": not stopping,
                "inFlight": active, "ioContract": os.environ.get("PLATFORM_IO_CONTRACT", "edgeai.image-digits.v1")})
        if self.path in ("/v2/health/live", "/v2/health/ready", f"/v2/models/{NAME}/ready"):
            return self.respond(503 if stopping else 200, {})
        if self.path == f"/v2/models/{NAME}":
            return self.respond(200, {"name": NAME, "versions": [VERSION], "platform": "python-cpu",
                                      "inputs": INPUTS, "outputs": OUTPUTS})
        return self.respond(404, {"error": "not_found"})

    def do_POST(self):
        global inflight
        if self.path != f"/v2/models/{NAME}/infer":
            return self.respond(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("invalid_body_size")
            self.connection.settimeout(10)
            body = json.loads(self.rfile.read(length))
        except (ValueError, TypeError, OSError):
            return self.respond(400, {"error": "invalid_request"})
        with lock:
            if draining:
                return self.respond(503, {"error": "draining"})
            if inflight >= 8:
                return self.respond(429, {"error": "capacity_exceeded"})
            inflight += 1
        try:
            started = time.monotonic()
            result = infer(body)
            result["parameters"] = {"inference_ms": (time.monotonic() - started) * 1000,
                                    "node": os.environ.get("PLATFORM_NODE", "local")}
            self.respond(200, result)
        except (ValueError, TypeError):
            self.respond(400, {"error": "input_outside_model_contract"})
        finally:
            with lock:
                inflight -= 1


def main():
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PLATFORM_PORT", "8080"))), Handler)
    server.daemon_threads = False
    def stop(*_):
        global draining
        with lock:
            draining = True
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
