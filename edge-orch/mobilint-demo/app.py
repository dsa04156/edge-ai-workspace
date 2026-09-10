"""Fixed-input ARIES core-sharing demonstration, not a production inference API."""
import concurrent.futures
import hashlib
import json
import multiprocessing as mp
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODELS = {"candy": 0, "mosaic": 1}


def validate_request(body):
    if not isinstance(body, dict) or set(body) - {"seed", "iterations"}:
        raise ValueError("Only seed and iterations are accepted")
    seed, iterations = body.get("seed", 0), body.get("iterations", 1)
    if type(seed) is not int or not 0 <= seed <= 4294967295:
        raise ValueError("seed must be an integer in [0, 4294967295]")
    if type(iterations) is not int or not 1 <= iterations <= 50:
        raise ValueError("iterations must be an integer in [1, 50]")
    return seed, iterations


def worker(name, core, inbox, outbox):
    import qbruntime
    import numpy as np

    model = None
    try:
        config = qbruntime.ModelConfig()
        target = qbruntime.CoreId(qbruntime.Cluster.Cluster0, getattr(qbruntime.Core, f"Core{core}"))
        assert config.set_single_core_mode(core_ids=[target])
        path = Path(os.environ.get("MODEL_DIR", "/models")) / f"style_{name}.mxq"
        accelerator = qbruntime.Accelerator(0)
        model = qbruntime.Model(str(path), config)
        model.launch(accelerator)
        actual = [str(c) for c in model.get_target_cores()]
        assert len(actual) == 1 and str(target) == actual[0], actual
        shape = tuple(model.get_model_input_shape()[0])
        info = {"id": name, "core": actual[0], "input_shape": shape,
                "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "pid": os.getpid(), "ready": True}
        outbox.put({"info": info})
        while True:
            task = inbox.get()
            if task is None:
                break
            seed, iterations, begin_at = task
            # A deterministic fixture; no camera, sensor, uploads or remote model paths.
            data = np.random.default_rng(seed).uniform(-1, 1, shape).astype(np.float32)
            if begin_at > time.monotonic():
                time.sleep(max(0, begin_at - time.monotonic()))
            start = time.monotonic_ns()
            for _ in range(iterations):
                outputs = model.infer([data])
            end = time.monotonic_ns()
            output = np.asarray(outputs[0])
            assert output.shape == shape and np.isfinite(output).all()
            outbox.put({"model": name, "core": actual[0], "pid": os.getpid(),
                        "seed": seed, "iterations": iterations,
                        "start_ns": start, "end_ns": end,
                        "duration_ms": (end - start) / 1e6,
                        "output_shape": output.shape,
                        "output_sha256": hashlib.sha256(output.tobytes()).hexdigest(),
                        "output_mean": float(output.mean()), "finite": True})
    except Exception as exc:
        outbox.put({"error": str(exc)})
    finally:
        if model is not None:
            model.dispose()


class Busy(Exception):
    pass


class Runtime:
    def __init__(self):
        self.workers = {}
        self.locks = {name: threading.Lock() for name in MODELS}
        self.failed = set()
        self.last = None
        ctx = mp.get_context("spawn")
        try:
            for name, core in MODELS.items():
                inbox, outbox = ctx.Queue(1), ctx.Queue(1)
                process = ctx.Process(target=worker, args=(name, core, inbox, outbox), daemon=True)
                process.start()
                self.workers[name] = {"process": process, "inbox": inbox, "outbox": outbox}
                reply = outbox.get(timeout=30)
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                self.workers[name]["info"] = reply["info"]
        except Exception:
            self.close()
            raise

    def status(self):
        return {"demo": "Mobilint ARIES2 core sharing", "input": "synthetic fixture",
                "device": "aries0", "allocation": "one NPU to one Pod",
                "models": [dict(w["info"], ready=w["process"].is_alive() and n not in self.failed,
                                busy=self.locks[n].locked()) for n, w in self.workers.items()],
                "last_result": self.last,
                "limits": "No Pod-level core, memory or fault isolation"}

    def call(self, name, seed, iterations, begin_at=0):
        if name in self.failed or not self.workers[name]["process"].is_alive():
            raise RuntimeError("model worker unavailable")
        w = self.workers[name]
        try:
            w["inbox"].put_nowait((seed, iterations, begin_at))
            reply = w["outbox"].get(timeout=15)
            if "error" in reply:
                raise RuntimeError(reply["error"])
            return reply
        except (queue.Empty, queue.Full, RuntimeError):
            # Fail closed: never reuse a queue containing a late response after timeout.
            self.failed.add(name)
            raise RuntimeError("model worker failed or timed out; restart required") from None

    def infer(self, names, body):
        seed, iterations = validate_request(body)
        acquired = []
        try:
            for name in sorted(names):
                if not self.locks[name].acquire(blocking=False):
                    raise Busy("model busy; retry after the current request completes")
                acquired.append(name)
            begin_at = time.monotonic() + 0.05 if len(names) > 1 else 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
                futures = [pool.submit(self.call, n, seed, iterations, begin_at) for n in names]
                results = [f.result() for f in futures]
            overlap = max(0, min(r["end_ns"] for r in results) - max(r["start_ns"] for r in results)) / 1e6 if len(results) > 1 else 0
            self.last = {"results": results, "overlap_ms": overlap,
                         "overlap_boundary": "host intervals around SDK inference loops, not NPU kernel timing"}
            return self.last
        finally:
            for name in reversed(acquired):
                self.locks[name].release()

    def close(self):
        for w in self.workers.values():
            try:
                w["inbox"].put_nowait(None)
            except queue.Full:
                pass
            w["process"].join(timeout=2)
            if w["process"].is_alive():
                w["process"].terminate()
                w["process"].join(timeout=2)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path not in ("/", "/healthz", "/models"):
            return self.respond(404, {"error": "not found"})
        status = self.server.runtime.status()
        healthy = all(m["ready"] for m in status["models"])
        self.respond(200 if healthy else 503, status)

    def do_POST(self):
        routes = {"/infer/candy": ["candy"], "/infer/mosaic": ["mosaic"],
                  "/demo/parallel": ["candy", "mosaic"]}
        if self.path not in routes:
            return self.respond(404, {"error": "unknown fixed model"})
        try:
            self.connection.settimeout(5)
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Transfer-Encoding is not supported")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("JSON body must be 1..1024 bytes")
            body = json.loads(self.rfile.read(length))
            self.respond(200, self.server.runtime.infer(routes[self.path], body))
        except (ValueError, TimeoutError) as exc:
            self.respond(400, {"error": str(exc)})
        except Busy as exc:
            self.respond(409, {"error": str(exc)})
        except RuntimeError as exc:
            self.respond(503, {"error": str(exc)})


if __name__ == "__main__":
    runtime = Runtime()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.runtime = runtime
    try:
        server.serve_forever()
    finally:
        server.server_close()
        runtime.close()
