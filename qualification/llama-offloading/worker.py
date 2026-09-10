"""Stateful per-node Llama runtime for cold/cached/active qualification."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from urllib import parse, request


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "18100"))
NODE_ID = os.getenv("NODE_ID", "unknown")
ROLE = os.getenv("ROLE", "unknown")
MODEL = os.getenv("MODEL", "llama3.2:1b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11435").rstrip("/")
MAX_CONCURRENCY = max(1, int(os.getenv("MAX_CONCURRENCY", "1")))
PROFILE_INFERENCE_MS = float(os.getenv("PROFILE_INFERENCE_MS", "1000"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "600"))
ACTIVATION_TIMEOUT_SECONDS = float(os.getenv("ACTIVATION_TIMEOUT_SECONDS", "1200"))
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL", "http://prometheus-operated.kube-system.svc.cluster.local:9090"
).rstrip("/")
GPU_MODEL = os.getenv("GPU_MODEL", "")
VALID_STATES = {"COLD", "CACHED", "ACTIVE"}


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.lifecycle_lock = threading.Lock()
        self.slots = threading.Semaphore(MAX_CONCURRENCY)
        self.node_state = "COLD"
        self.state_changed_timestamp = time.time()
        self.activation_started_timestamp: float | None = None
        self.ready_timestamp: float | None = None
        self.last_request_timestamp: float | None = None
        self.deactivation_timestamp: float | None = None
        self.active_requests = 0
        self.queue_length = 0
        self.completed_requests = 0
        self.failed_requests = 0
        self.last_ttft_ms = 0.0
        self.last_tokens_per_second = 0.0
        self.last_inference_ms = 0.0
        self.ewma_ttft_ms = 0.0
        self.ewma_tokens_per_second = 0.0
        self.ewma_inference_ms = PROFILE_INFERENCE_MS
        self.last_activation: dict[str, Any] = {}
        self.last_deactivation: dict[str, Any] = {}
        self.transition_records: list[dict[str, Any]] = []
        self.cpu_previous: tuple[int, int] | None = None

    @staticmethod
    def _ewma(old: float, new: float, alpha: float = 0.25) -> float:
        return new if old <= 0 else alpha * new + (1.0 - alpha) * old

    def transition(self, new_state: str, reason: str) -> dict[str, Any]:
        if new_state not in VALID_STATES:
            raise ValueError(f"invalid node state: {new_state}")
        with self.lock:
            old_state = self.node_state
            changed_at = time.time()
            self.node_state = new_state
            self.state_changed_timestamp = changed_at
            record = {
                "timestamp": changed_at,
                "node": ROLE,
                "physical_node": NODE_ID,
                "old_state": old_state,
                "new_state": new_state,
                "reason": reason,
            }
            self.transition_records.append(record)
        print(json.dumps({"event": "state_transition", **record}), flush=True)
        return record

    def finish(self, *, ttft_ms: float, tps: float, inference_ms: float, failed: bool) -> None:
        with self.lock:
            self.active_requests -= 1
            self.last_request_timestamp = time.time()
            if failed:
                self.failed_requests += 1
                return
            self.completed_requests += 1
            self.last_ttft_ms = ttft_ms
            self.last_tokens_per_second = tps
            self.last_inference_ms = inference_ms
            self.ewma_ttft_ms = self._ewma(self.ewma_ttft_ms, ttft_ms)
            self.ewma_tokens_per_second = self._ewma(self.ewma_tokens_per_second, tps)
            self.ewma_inference_ms = self._ewma(self.ewma_inference_ms, inference_ms)


STATE = State()


def read_cpu_percent() -> float | None:
    try:
        fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        total = sum(fields)
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        with STATE.lock:
            previous = STATE.cpu_previous
            STATE.cpu_previous = (total, idle)
        if previous is None or total <= previous[0]:
            return None
        return round(100.0 * (1.0 - (idle - previous[1]) / (total - previous[0])), 3)
    except (OSError, ValueError, IndexError):
        return None


def read_ram_percent() -> float | None:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0])
        return round(100.0 * (1.0 - values["MemAvailable"] / values["MemTotal"]), 3)
    except (OSError, ValueError, KeyError):
        return None


def read_temperature() -> float | None:
    temperatures: list[float] = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(path.read_text().strip())
            temperatures.append(value / 1000.0 if value > 1000 else value)
        except (OSError, TypeError, UnicodeError, ValueError):
            continue
    return round(max(temperatures), 3) if temperatures else None


def ollama_process_rss_mib(process_kind: str) -> float | None:
    needles = ("ollama runner", "llama-server") if process_kind == "runner" else ("ollama serve", "/bin/ollama serve")
    total_kib = 0
    found = False
    try:
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
                if not any(needle in cmdline for needle in needles):
                    continue
                for line in (proc / "status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        total_kib += int(line.split()[1])
                        found = True
                        break
            except (OSError, UnicodeError, ValueError):
                continue
        return round(total_kib / 1024.0, 3) if found else 0.0
    except OSError:
        return None


def read_gpu_metrics() -> dict[str, Any]:
    unavailable = {
        "gpu_model": GPU_MODEL or None,
        "gpu_utilization_percent": None,
        "gpu_memory_used_mib": None,
        "gpu_memory_total_mib": None,
        "gpu_memory_utilization_percent": None,
        "gpu_temperature_celsius": None,
        "gpu_metrics_reason": "dcgm_not_available_for_node" if not GPU_MODEL else "dcgm_query_failed",
        "gpu_measurement_attributable": False,
    }
    if not GPU_MODEL:
        return unavailable
    metric_names = "DCGM_FI_DEV_GPU_UTIL|DCGM_FI_DEV_FB_USED|DCGM_FI_DEV_FB_FREE|DCGM_FI_DEV_GPU_TEMP"
    query = f'{{__name__=~"{metric_names}",modelName={json.dumps(GPU_MODEL)}}}'
    url = f"{PROMETHEUS_URL}/api/v1/query?{parse.urlencode({'query': query})}"
    try:
        with request.urlopen(url, timeout=1.0) as response:
            payload = json.load(response)
        values = {
            item.get("metric", {}).get("__name__"): float(item["value"][1])
            for item in payload.get("data", {}).get("result", [])
        }
        util = values.get("DCGM_FI_DEV_GPU_UTIL")
        used = values.get("DCGM_FI_DEV_FB_USED")
        free = values.get("DCGM_FI_DEV_FB_FREE")
        total = used + free if used is not None and free is not None else None
        if util is None:
            return unavailable
        return {
            "gpu_model": GPU_MODEL,
            "gpu_utilization_percent": util,
            "gpu_memory_used_mib": used,
            "gpu_memory_total_mib": total,
            "gpu_memory_utilization_percent": round(100.0 * used / total, 3) if used is not None and total else None,
            "gpu_temperature_celsius": values.get("DCGM_FI_DEV_GPU_TEMP"),
            "gpu_metrics_reason": "dcgm_shared_with_existing_workload",
            "gpu_measurement_attributable": False,
        }
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return unavailable


def http_json(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str | None = None,
    timeout: float = 5.0,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(
        f"{OLLAMA_URL}{path}",
        data=body,
        method=method or ("GET" if body is None else "POST"),
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def runtime_up() -> bool:
    try:
        http_json("/api/version", timeout=0.5)
        return True
    except Exception:
        return False


def wait_runtime(timeout: float = 30.0) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if runtime_up():
            return 1000.0 * (time.perf_counter() - started)
        time.sleep(0.1)
    raise TimeoutError("ollama management runtime did not become ready")


def model_metadata() -> dict[str, Any] | None:
    if not runtime_up():
        return None
    tags = http_json("/api/tags", timeout=3.0)
    return next(
        (item for item in tags.get("models", []) if item.get("name") == MODEL or item.get("model") == MODEL),
        None,
    )


def model_loaded() -> bool:
    if not runtime_up():
        return False
    try:
        running = http_json("/api/ps", timeout=3.0)
        return any(item.get("name") == MODEL or item.get("model") == MODEL for item in running.get("models", []))
    except Exception:
        return False


def model_vram_mib() -> float | None:
    """Ollama model residency, not total device memory or utilization."""
    try:
        running = http_json("/api/ps", timeout=3.0)
        model = next((m for m in running.get("models", []) if m.get("name") == MODEL or m.get("model") == MODEL), None)
        if model is None:
            return 0.0
        value = model.get("size_vram")
        return round(float(value) / 1048576, 3) if value is not None else None
    except Exception:
        return None


def pull_model() -> tuple[float, str | None]:
    started = time.perf_counter()
    result = http_json("/api/pull", {"model": MODEL, "stream": False}, timeout=ACTIVATION_TIMEOUT_SECONDS)
    duration = 1000.0 * (time.perf_counter() - started)
    metadata = model_metadata()
    if not metadata:
        raise RuntimeError(f"model pull did not produce local model: {result}")
    return duration, metadata.get("digest")


def delete_model() -> float:
    started = time.perf_counter()
    try:
        http_json("/api/delete", {"model": MODEL}, method="DELETE", timeout=60.0)
    except Exception as exc:
        if model_metadata() is not None:
            raise RuntimeError(f"model delete failed: {type(exc).__name__}:{exc}") from exc
    return 1000.0 * (time.perf_counter() - started)


def unload_model() -> float:
    if not model_loaded():
        return 0.0
    started = time.perf_counter()
    http_json("/api/generate", {"model": MODEL, "keep_alive": 0, "stream": False}, timeout=60.0)
    deadline = time.perf_counter() + 30.0
    while model_loaded() and time.perf_counter() < deadline:
        time.sleep(0.1)
    if model_loaded():
        raise TimeoutError("ollama model runner did not unload")
    return 1000.0 * (time.perf_counter() - started)


def warm_model() -> tuple[float, str | None]:
    started = time.perf_counter()
    http_json(
        "/api/generate",
        {
            "model": MODEL,
            "prompt": "Reply only with OK.",
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": 0, "seed": 42, "num_predict": 1, "num_ctx": 2048},
        },
        timeout=ACTIVATION_TIMEOUT_SECONDS,
    )
    duration = 1000.0 * (time.perf_counter() - started)
    metadata = model_metadata()
    if not model_loaded():
        raise RuntimeError("model warm-up completed but /api/ps is not ready")
    return duration, metadata.get("digest") if metadata else None


def activate(payload: dict[str, Any]) -> dict[str, Any]:
    target_state = str(payload.get("target_state") or "ACTIVE").upper()
    if target_state not in {"ACTIVE", "CACHED"}:
        raise ValueError("target_state must be ACTIVE or CACHED")
    if os.getenv("CONTINUITY_SOURCE") == "1" and target_state != "ACTIVE":
        raise ValueError("continuity source runtime must stay ACTIVE")
    reason = str(payload.get("reason") or "api_activate")
    with STATE.lifecycle_lock:
        with STATE.lock:
            before = STATE.node_state
        if target_state == "ACTIVE" and before == "ACTIVE" and model_loaded():
            return {
                **STATE.last_activation,
                "activation_required": False,
                "node_state_before": before,
                "node_state": "ACTIVE",
            }
        metadata = model_metadata() if runtime_up() else None
        if target_state == "CACHED" and before == "CACHED" and metadata is not None and not model_loaded():
            return {"activation_required": False, "node_state_before": before, "node_state": "CACHED"}

        activation_started = time.time()
        total_started = time.perf_counter()
        with STATE.lock:
            STATE.activation_started_timestamp = activation_started
        worker_start_ms = wait_runtime()
        remote_download_ms = 0.0
        metadata = model_metadata()
        if metadata is None:
            remote_download_ms, model_digest = pull_model()
        else:
            model_digest = metadata.get("digest")

        if target_state == "CACHED":
            worker_stop_ms = unload_model()
            transition = STATE.transition("CACHED", reason)
            result = {
                "activation_required": True,
                "node_state_before": before,
                "node_state": "CACHED",
                "activation_started_timestamp": activation_started,
                "ready_timestamp": None,
                "worker_start_ms": round(worker_start_ms, 3),
                "model_remote_download_ms": round(remote_download_ms, 3),
                "model_load_ms": 0.0,
                "cuda_initialization_ms": None,
                "endpoint_ready_ms": 0.0,
                "worker_stop_ms": round(worker_stop_ms, 3),
                "worker_lifecycle_note": "Ollama management daemon remains resident; inference runner is unloaded",
                "activation_time_ms": round(1000.0 * (time.perf_counter() - total_started), 3),
                "model_digest": model_digest,
                "transition": transition,
            }
            with STATE.lock:
                STATE.last_activation = result
            return result

        model_load_ms, model_digest = warm_model()
        ready_timestamp = time.time()
        transition = STATE.transition("ACTIVE", reason)
        result = {
            "activation_required": True,
            "node_state_before": before,
            "node_state": "ACTIVE",
            "activation_started_timestamp": activation_started,
            "ready_timestamp": ready_timestamp,
            "worker_start_ms": round(worker_start_ms, 3),
            "model_remote_download_ms": round(remote_download_ms, 3),
            "model_load_ms": round(model_load_ms, 3),
            "cuda_initialization_ms": None,
            "endpoint_ready_ms": round(1000.0 * (time.perf_counter() - total_started), 3),
            "activation_time_ms": round(1000.0 * (time.perf_counter() - total_started), 3),
            "model_digest": model_digest,
            "transition": transition,
        }
        with STATE.lock:
            STATE.ready_timestamp = ready_timestamp
            STATE.last_activation = result
        return result


def deactivate(payload: dict[str, Any]) -> dict[str, Any]:
    if os.getenv("CONTINUITY_SOURCE") == "1":
        raise ValueError("continuity source model release is disabled")
    target_state = str(payload.get("target_state") or "CACHED").upper()
    if target_state not in {"COLD", "CACHED"}:
        raise ValueError("target_state must be COLD or CACHED")
    reason = str(payload.get("reason") or "api_deactivate")
    with STATE.lifecycle_lock:
        with STATE.lock:
            before = STATE.node_state
            busy = STATE.active_requests > 0 or STATE.queue_length > 0
        if busy:
            raise RuntimeError("worker_busy")
        metadata = model_metadata() if runtime_up() else None
        if before == "CACHED" and target_state == "CACHED" and metadata is not None and not model_loaded():
            return {"deactivation_required": False, "node_state_before": before, "node_state": target_state}
        if before == "COLD" and target_state == "COLD" and metadata is None and not model_loaded():
            return {"deactivation_required": False, "node_state_before": before, "node_state": target_state}

        started_at = time.time()
        started = time.perf_counter()
        worker_start_ms = wait_runtime()
        unload_ms = unload_model()
        delete_ms = 0.0
        if target_state == "COLD":
            if model_metadata() is not None:
                delete_ms = delete_model()
        worker_stop_ms = unload_ms
        transition = STATE.transition(target_state, reason)
        deactivation_timestamp = time.time()
        result = {
            "deactivation_required": True,
            "node_state_before": before,
            "node_state": target_state,
            "deactivation_started_timestamp": started_at,
            "deactivation_timestamp": deactivation_timestamp,
            "worker_start_ms": round(worker_start_ms, 3),
            "model_unload_ms": round(unload_ms, 3),
            "model_delete_ms": round(delete_ms, 3),
            "worker_stop_ms": round(worker_stop_ms, 3),
            "worker_lifecycle_note": "Ollama management daemon remains resident; inference runner is unloaded",
            "deactivation_time_ms": round(1000.0 * (time.perf_counter() - started), 3),
            "transition": transition,
        }
        with STATE.lock:
            STATE.deactivation_timestamp = deactivation_timestamp
            STATE.ready_timestamp = None
            STATE.last_deactivation = result
        return result


def health() -> dict[str, Any]:
    up = runtime_up()
    metadata = model_metadata() if up else None
    loaded = model_loaded() if up else False
    with STATE.lock:
        state = STATE.node_state
    return {
        "agent_healthy": True,
        "inference_ready": state == "ACTIVE" and up and loaded,
        "node_state": state,
        "management_runtime_running": up,
        "inference_worker_running": loaded,
        "runtime_running": up,
        "model_cached": metadata is not None,
        "model_loaded": loaded,
        "node_id": NODE_ID,
        "role": ROLE,
        "model": MODEL,
        "model_digest": metadata.get("digest") if metadata else None,
        "runtime": "ollama",
    }


def metrics() -> dict[str, Any]:
    now = time.time()
    up = runtime_up()
    metadata = model_metadata() if up else None
    loaded = model_loaded() if up else False
    with STATE.lock:
        service = {
            "node_state": STATE.node_state,
            "state_changed_timestamp": STATE.state_changed_timestamp,
            "activation_started_timestamp": STATE.activation_started_timestamp,
            "ready_timestamp": STATE.ready_timestamp,
            "last_request_timestamp": STATE.last_request_timestamp,
            "deactivation_timestamp": STATE.deactivation_timestamp,
            "idle_seconds": None if STATE.last_request_timestamp is None else max(0.0, now - STATE.last_request_timestamp),
            "active_requests": STATE.active_requests,
            "queue_length": STATE.queue_length,
            "completed_requests": STATE.completed_requests,
            "failed_requests": STATE.failed_requests,
            "last_ttft_ms": round(STATE.last_ttft_ms, 3),
            "last_tokens_per_second": round(STATE.last_tokens_per_second, 3),
            "last_inference_ms": round(STATE.last_inference_ms, 3),
            "ewma_ttft_ms": round(STATE.ewma_ttft_ms, 3),
            "ewma_tokens_per_second": round(STATE.ewma_tokens_per_second, 3),
            "ewma_inference_ms": round(STATE.ewma_inference_ms, 3),
            "last_activation": STATE.last_activation,
            "last_deactivation": STATE.last_deactivation,
        }
    return {
        "timestamp": now,
        "node_id": NODE_ID,
        "role": ROLE,
        "model": MODEL,
        "max_concurrency": MAX_CONCURRENCY,
        "profile_inference_ms": PROFILE_INFERENCE_MS,
        "management_runtime_running": up,
        "inference_worker_running": loaded,
        "runtime_running": up,
        "model_cached": metadata is not None,
        "model_cache_bytes": metadata.get("size") if metadata else 0,
        "model_vram_mib": model_vram_mib(),
        "inference_process_rss_mib": ollama_process_rss_mib("runner"),
        "management_process_rss_mib": ollama_process_rss_mib("serve"),
        "cpu_utilization_percent": read_cpu_percent(),
        "ram_utilization_percent": read_ram_percent(),
        "temperature_celsius": read_temperature(),
        **read_gpu_metrics(),
        **service,
    }


def generate(payload: dict[str, Any], on_token=None) -> dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    with STATE.lock:
        if STATE.node_state != "ACTIVE":
            raise RuntimeError(f"worker_not_active:{STATE.node_state}")
    if not model_loaded():
        raise RuntimeError("worker_not_ready")
    request_id = str(payload.get("request_id") or "")
    max_tokens = max(1, min(256, int(payload.get("max_tokens") or 32)))
    queued_at = time.perf_counter()
    with STATE.lock:
        STATE.queue_length += 1
    acquired = False
    try:
        STATE.slots.acquire()
        acquired = True
        started = time.perf_counter()
        with STATE.lock:
            STATE.queue_length -= 1
            STATE.active_requests += 1
        req = request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps(
                {
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": True,
                    "keep_alive": -1,
                    "options": {"temperature": 0, "seed": 42, "num_predict": max_tokens, "num_ctx": 2048},
                }
            ).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        chunks: list[str] = []
        first_token_at: float | None = None
        final: dict[str, Any] = {}
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line)
                text = str(event.get("response") or "")
                if text and first_token_at is None:
                    first_token_at = time.perf_counter()
                if text and on_token is not None:
                    on_token(text)
                chunks.append(text)
                if event.get("done"):
                    final = event
        finished = time.perf_counter()
        ttft_ms = 1000.0 * ((first_token_at or finished) - queued_at)
        inference_ms = 1000.0 * (finished - started)
        actual_e2e_ms = 1000.0 * (finished - queued_at)
        eval_count = int(final.get("eval_count") or max(1, len("".join(chunks).split())))
        eval_duration_ns = int(final.get("eval_duration") or 0)
        tps = eval_count / (eval_duration_ns / 1_000_000_000) if eval_duration_ns > 0 else eval_count / max(inference_ms / 1000.0, 0.001)
        result = {
            "request_id": request_id,
            "node_id": NODE_ID,
            "role": ROLE,
            "node_state": "ACTIVE",
            "model": MODEL,
            "response": "".join(chunks),
            "model_digest": (model_metadata() or {}).get("digest"),
            "queue_wait_ms": round(1000.0 * (started - queued_at), 3),
            "ttft_ms": round(ttft_ms, 3),
            "tokens_per_second": round(tps, 3),
            "inference_ms": round(inference_ms, 3),
            "actual_e2e_ms": round(actual_e2e_ms, 3),
            "eval_count": eval_count,
        }
        STATE.finish(ttft_ms=ttft_ms, tps=tps, inference_ms=inference_ms, failed=False)
        return result
    except Exception:
        if acquired:
            STATE.finish(ttft_ms=0.0, tps=0.0, inference_ms=0.0, failed=True)
        else:
            with STATE.lock:
                STATE.queue_length -= 1
        raise
    finally:
        if acquired:
            STATE.slots.release()


def transitions() -> list[dict[str, Any]]:
    with STATE.lock:
        return list(STATE.transition_records)


class Handler(BaseHTTPRequestHandler):
    server_version = "LlamaLifecycleWorker/2.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(json.dumps({"timestamp": time.time(), "message": fmt % args}), flush=True)

    def _write(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write(HTTPStatus.OK, health())
        elif self.path == "/metrics":
            self._write(HTTPStatus.OK, metrics())
        elif self.path == "/transitions":
            self._write(HTTPStatus.OK, transitions())
        else:
            self._write(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        streaming = False
        try:
            payload = self._payload()
            if self.path == "/generate/stream":
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                streaming = True

                def emit(event):
                    self.wfile.write((json.dumps(event) + "\n").encode())
                    self.wfile.flush()

                result = generate(payload, lambda token: emit({"type": "token", "text": token}))
                emit({"type": "result", **result})
            elif self.path == "/generate":
                self._write(HTTPStatus.OK, generate(payload))
            elif self.path == "/activate":
                self._write(HTTPStatus.OK, activate(payload))
            elif self.path == "/deactivate":
                self._write(HTTPStatus.OK, deactivate(payload))
            else:
                self._write(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ValueError as exc:
            if streaming:
                self._stream_error(exc)
                return
            self._write(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            if streaming:
                self._stream_error(exc)
                return
            status = HTTPStatus.CONFLICT if str(exc) == "worker_busy" else HTTPStatus.SERVICE_UNAVAILABLE
            self._write(status, {"error": str(exc)})
        except Exception as exc:
            if streaming:
                self._stream_error(exc)
                return
            self._write(HTTPStatus.BAD_GATEWAY, {"error": f"operation_failed:{type(exc).__name__}:{exc}"})

    def _stream_error(self, exc):
        try:
            self.wfile.write((json.dumps({"type": "error", "error": str(exc)}) + "\n").encode())
            self.wfile.flush()
        except OSError:
            pass  # Client disconnected; never retry an uncertain inference.


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
