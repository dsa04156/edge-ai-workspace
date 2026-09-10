"""Placement and lifecycle controller for three Llama operating methods."""

from __future__ import annotations

from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import statistics
import threading
import time
from typing import Any
from urllib import request
import uuid

from placement import PlacementEngine, PolicyConfig, TIERS


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "18101"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
REQUEST_LOG = DATA_DIR / "requests.jsonl"
ACTIVATION_LOG = DATA_DIR / "activations.jsonl"
METHOD_LOG = DATA_DIR / "methods.jsonl"
IDLE_TIMEOUT_SECONDS = float(os.getenv("IDLE_TIMEOUT_SECONDS", "30"))
MONITOR_INTERVAL_SECONDS = float(os.getenv("MONITOR_INTERVAL_SECONDS", "1"))
METHODS = ("always_on", "cold_on_demand", "cached_on_demand")
WORKERS = {tier: os.environ[f"{tier.upper()}_URL"].rstrip("/") for tier in TIERS}
DEFAULT_ACTIVATION_MS = {
    "always_on": {"nano": 0.0, "agx": 0.0, "spark": 0.0},
    "cold_on_demand": {
        "nano": float(os.getenv("COLD_NANO_ACTIVATION_MS", "5000")),
        "agx": float(os.getenv("COLD_AGX_ACTIVATION_MS", "40646")),
        "spark": float(os.getenv("COLD_SPARK_ACTIVATION_MS", "38465")),
    },
    "cached_on_demand": {
        "nano": float(os.getenv("CACHED_NANO_ACTIVATION_MS", "1000")),
        "agx": float(os.getenv("CACHED_AGX_ACTIVATION_MS", "1187")),
        "spark": float(os.getenv("CACHED_SPARK_ACTIVATION_MS", "1187")),
    },
}
ENGINE = PlacementEngine(
    PolicyConfig(
        min_improvement=float(os.getenv("MIN_IMPROVEMENT", "0.15")),
        overload_dwell_seconds=float(os.getenv("OVERLOAD_DWELL_SECONDS", "2")),
        recovery_dwell_seconds=float(os.getenv("RECOVERY_DWELL_SECONDS", "4")),
        cooldown_seconds=float(os.getenv("COOLDOWN_SECONDS", "5")),
        queue_high=int(os.getenv("QUEUE_HIGH", "8")),
        ttft_high_ms=float(os.getenv("TTFT_HIGH_MS", "1500")),
        min_tokens_per_second=float(os.getenv("MIN_TOKENS_PER_SECOND", "39.5")),
    )
)
ENGINE_LOCK = threading.RLock()
LOG_LOCK = threading.Lock()
METHOD_LOCK = threading.Lock()
CURRENT_METHOD = "unconfigured"
METHOD_READY = False
ACTIVATION_HISTORY: dict[tuple[str, str], list[float]] = defaultdict(list)


def http_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[Any, float]:
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(
        url,
        data=body,
        method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with request.urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    return result, 1000.0 * (time.perf_counter() - started)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with LOG_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def activation_estimate(method: str, tier: str, state: str) -> float:
    if state == "ACTIVE":
        return 0.0
    values = ACTIVATION_HISTORY.get((method, tier), [])
    if values:
        return float(statistics.median(values[-5:]))
    return DEFAULT_ACTIVATION_MS.get(method, DEFAULT_ACTIVATION_MS["cold_on_demand"])[tier]


def snapshot(tier: str) -> dict[str, Any]:
    try:
        metrics, rtt_ms = http_json(f"{WORKERS[tier]}/metrics", timeout=4.0)
        health, _ = http_json(f"{WORKERS[tier]}/health", timeout=4.0)
        state = str(health.get("node_state") or metrics.get("node_state") or "COLD")
        return {
            **metrics,
            "agent_healthy": bool(health.get("agent_healthy")),
            "available": bool(health.get("agent_healthy")),
            "healthy": bool(health.get("inference_ready")),
            "inference_ready": bool(health.get("inference_ready")),
            "model_digest": health.get("model_digest"),
            "node_state": state,
            "rtt_ms": round(rtt_ms, 3),
            "activation_estimate_ms": activation_estimate(CURRENT_METHOD, tier, state),
        }
    except Exception as exc:
        return {
            "agent_healthy": False,
            "available": False,
            "healthy": False,
            "inference_ready": False,
            "node_state": "UNKNOWN",
            "rtt_ms": None,
            "active_requests": 0,
            "queue_length": 0,
            "max_concurrency": 1,
            "profile_inference_ms": 1e9,
            "activation_estimate_ms": 1e9,
            "error": f"snapshot_failed:{type(exc).__name__}:{exc}",
        }


def all_snapshots() -> dict[str, dict[str, Any]]:
    return {tier: snapshot(tier) for tier in TIERS}


def record_activation(method: str, tier: str, phase: str, reason: str, result: dict[str, Any]) -> None:
    record = {
        "event": "activation",
        "timestamp": time.time(),
        "method": method,
        "node": tier,
        "physical_node": result.get("transition", {}).get("physical_node"),
        "phase": phase,
        "reason": reason,
        **{key: value for key, value in result.items() if key != "transition"},
    }
    append_jsonl(ACTIVATION_LOG, record)
    if phase == "workload" and result.get("node_state") == "ACTIVE":
        value = float(result.get("activation_time_ms") or 0.0)
        if value > 0:
            ACTIVATION_HISTORY[(method, tier)].append(value)


def activate_node(
    tier: str,
    *,
    method: str,
    phase: str,
    reason: str,
    target_state: str = "ACTIVE",
) -> dict[str, Any]:
    result, _ = http_json(
        f"{WORKERS[tier]}/activate",
        {"target_state": target_state, "reason": reason},
        timeout=1300.0,
    )
    if result.get("activation_required"):
        record_activation(method, tier, phase, reason, result)
    return result


def deactivate_node(tier: str, *, method: str, phase: str, reason: str, target_state: str) -> dict[str, Any]:
    result, _ = http_json(
        f"{WORKERS[tier]}/deactivate",
        {"target_state": target_state, "reason": reason},
        timeout=180.0,
    )
    if result.get("deactivation_required"):
        append_jsonl(
            ACTIVATION_LOG,
            {
                "event": "deactivation",
                "timestamp": time.time(),
                "method": method,
                "node": tier,
                "physical_node": result.get("transition", {}).get("physical_node"),
                "phase": phase,
                "reason": reason,
                **{key: value for key, value in result.items() if key != "transition"},
            },
        )
    return result


def reset_engine() -> None:
    ENGINE.route = "nano"
    ENGINE.cooldown_until = 0.0
    ENGINE.overload_since = {tier: None for tier in TIERS}
    ENGINE.recovery_since = {tier: None for tier in TIERS}


def configure_method(method: str) -> dict[str, Any]:
    global CURRENT_METHOD, METHOD_READY
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    with METHOD_LOCK, ENGINE_LOCK:
        METHOD_READY = False
        CURRENT_METHOD = method
        reset_engine()
        started = time.time()
        actions: list[dict[str, Any]] = []
        actions.append(
            {"node": "nano", **activate_node("nano", method=method, phase="setup", reason=f"method_setup:{method}")}
        )
        for tier in ("agx", "spark"):
            if method == "always_on":
                result = activate_node(tier, method=method, phase="setup", reason=f"method_setup:{method}")
            elif method == "cold_on_demand":
                result = deactivate_node(
                    tier,
                    method=method,
                    phase="setup",
                    reason=f"method_setup:{method}",
                    target_state="COLD",
                )
            else:
                result = activate_node(
                    tier,
                    method=method,
                    phase="setup",
                    reason=f"method_setup:{method}:cache_prime",
                    target_state="CACHED",
                )
            actions.append({"node": tier, **result})
        snapshots = all_snapshots()
        expected = {
            "always_on": {"nano": "ACTIVE", "agx": "ACTIVE", "spark": "ACTIVE"},
            "cold_on_demand": {"nano": "ACTIVE", "agx": "COLD", "spark": "COLD"},
            "cached_on_demand": {"nano": "ACTIVE", "agx": "CACHED", "spark": "CACHED"},
        }[method]
        actual = {tier: snapshots[tier].get("node_state") for tier in TIERS}
        if actual != expected:
            raise RuntimeError(f"method setup state mismatch: expected={expected} actual={actual}")
        if not snapshots["nano"].get("inference_ready"):
            raise RuntimeError("nano is not ready after method setup")
        if method == "always_on" and not all(snapshots[tier].get("inference_ready") for tier in TIERS):
            raise RuntimeError("always_on remote worker is not ready")
        METHOD_READY = True
        record = {
            "event": "method_configured",
            "timestamp": time.time(),
            "started_timestamp": started,
            "method": method,
            "duration_ms": round(1000.0 * (time.time() - started), 3),
            "states": actual,
        }
        append_jsonl(METHOD_LOG, record)
        return {**record, "actions": actions}


def idle_monitor() -> None:
    while True:
        time.sleep(MONITOR_INTERVAL_SECONDS)
        if not METHOD_READY or CURRENT_METHOD in {"unconfigured", "always_on"}:
            continue
        if not ENGINE_LOCK.acquire(blocking=False):
            continue
        try:
            target_state = "COLD" if CURRENT_METHOD == "cold_on_demand" else "CACHED"
            now = time.time()
            for tier in ("agx", "spark"):
                snap = snapshot(tier)
                if snap.get("node_state") != "ACTIVE":
                    continue
                anchor = snap.get("last_request_timestamp") or snap.get("ready_timestamp")
                idle = now - float(anchor) if anchor else 0.0
                if (
                    int(snap.get("active_requests") or 0) == 0
                    and int(snap.get("queue_length") or 0) == 0
                    and idle >= IDLE_TIMEOUT_SECONDS
                ):
                    deactivate_node(
                        tier,
                        method=CURRENT_METHOD,
                        phase="idle_release",
                        reason=f"idle_timeout:{IDLE_TIMEOUT_SECONDS:g}s",
                        target_state=target_state,
                    )
                    if ENGINE.route == tier:
                        reset_engine()
        except Exception as exc:
            print(json.dumps({"event": "idle_monitor_error", "error": f"{type(exc).__name__}:{exc}"}), flush=True)
        finally:
            ENGINE_LOCK.release()


def route_generate(payload: dict[str, Any]) -> dict[str, Any]:
    if not METHOD_READY:
        raise RuntimeError("method_not_configured")
    request_id = str(payload.get("request_id") or uuid.uuid4())
    mode = str(payload.get("placement_mode") or "dynamic")
    static_node = payload.get("target_node")
    received_timestamp = time.time()
    total_started = time.perf_counter()
    activation: dict[str, Any] = {"activation_required": False}
    with ENGINE_LOCK:
        snapshots = all_snapshots()
        if ENGINE.route != "nano" and snapshots[ENGINE.route].get("node_state") != "ACTIVE":
            reset_engine()
        previous_route = ENGINE.route
        decision = ENGINE.select(snapshots, mode=mode, static_node=static_node)
        selected_before = snapshots[decision.node]
        if selected_before.get("node_state") != "ACTIVE":
            try:
                activation = activate_node(
                    decision.node,
                    method=CURRENT_METHOD,
                    phase="workload",
                    reason=decision.reason,
                )
            except Exception:
                ENGINE.route = previous_route
                raise
            selected_after = snapshot(decision.node)
            if not selected_after.get("inference_ready"):
                ENGINE.route = previous_route
                raise RuntimeError(f"selected node {decision.node} is not READY after activation")
        elif not selected_before.get("inference_ready"):
            raise RuntimeError(f"selected node {decision.node} is not READY")

    forwarded = {
        "request_id": request_id,
        "prompt": payload.get("prompt"),
        "max_tokens": payload.get("max_tokens", 32),
    }
    result, _ = http_json(
        f"{WORKERS[decision.node]}/generate",
        forwarded,
        timeout=float(payload.get("timeout_seconds") or 900),
    )
    completed_timestamp = time.time()
    actual_latency_ms = 1000.0 * (time.perf_counter() - total_started)
    log_record = {
        "event": "request_completed",
        "request_id": request_id,
        "timestamp": received_timestamp,
        "completed_timestamp": completed_timestamp,
        "method": CURRENT_METHOD,
        "selected_node": decision.node,
        "physical_node": selected_before.get("node_id"),
        "node_state_before": selected_before.get("node_state"),
        "selection_reason": decision.reason,
        "concurrency": payload.get("concurrency"),
        "queue_length": selected_before.get("queue_length"),
        "active_requests": selected_before.get("active_requests"),
        "cpu_utilization_percent": selected_before.get("cpu_utilization_percent"),
        "gpu_utilization_percent": selected_before.get("gpu_utilization_percent"),
        "gpu_util": selected_before.get("gpu_utilization_percent"),
        "gpu_memory_used_mib": selected_before.get("gpu_memory_used_mib"),
        "gpu_memory_used": selected_before.get("gpu_memory_used_mib"),
        "gpu_measurement_attributable": selected_before.get("gpu_measurement_attributable"),
        "ram_utilization_percent": selected_before.get("ram_utilization_percent"),
        "temperature_celsius": selected_before.get("temperature_celsius"),
        "inference_process_rss_mib": selected_before.get("inference_process_rss_mib"),
        "model_cache_bytes": selected_before.get("model_cache_bytes"),
        "ttft_ms": result.get("ttft_ms"),
        "TTFT": result.get("ttft_ms"),
        "tokens_per_second": result.get("tokens_per_second"),
        "rtt_ms": selected_before.get("rtt_ms"),
        "RTT": selected_before.get("rtt_ms"),
        "predicted_e2e_ms": round(decision.predicted_e2e_ms, 3),
        "activation_required": bool(activation.get("activation_required")),
        "activation_time_ms": activation.get("activation_time_ms", 0.0),
        "activation_time": activation.get("activation_time_ms", 0.0),
        "worker_start_ms": activation.get("worker_start_ms", 0.0),
        "model_remote_download_ms": activation.get("model_remote_download_ms", 0.0),
        "model_load_ms": activation.get("model_load_ms", 0.0),
        "model_load_time": activation.get("model_load_ms", 0.0),
        "ready_timestamp": activation.get("ready_timestamp"),
        "actual_latency_ms": round(actual_latency_ms, 3),
        "actual_latency": round(actual_latency_ms, 3),
        "worker_actual_e2e_ms": result.get("actual_e2e_ms"),
        "placement_mode": mode,
        "candidate_predicted_e2e_ms": {key: round(value, 3) for key, value in decision.candidates.items()},
    }
    append_jsonl(REQUEST_LOG, log_record)
    return {**result, "placement": log_record}


def worker_transitions() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for tier in TIERS:
        try:
            result, _ = http_json(f"{WORKERS[tier]}/transitions", timeout=3.0)
            records.extend(result)
        except Exception:
            continue
    return sorted(records, key=lambda item: float(item.get("timestamp") or 0.0))


class Handler(BaseHTTPRequestHandler):
    server_version = "LlamaOffloadController/2.0"

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
            snapshots = all_snapshots()
            agents = sum(1 for item in snapshots.values() if item.get("agent_healthy"))
            self._write(
                HTTPStatus.OK,
                {
                    "controller_healthy": True,
                    "method_ready": METHOD_READY,
                    "method": CURRENT_METHOD,
                    "agent_ready_count": agents,
                    "required_count": len(TIERS),
                    "nodes": snapshots,
                },
            )
        elif self.path == "/metrics":
            self._write(
                HTTPStatus.OK,
                {
                    "timestamp": time.time(),
                    "method": CURRENT_METHOD,
                    "method_ready": METHOD_READY,
                    "route": ENGINE.route,
                    "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS,
                    "nodes": all_snapshots(),
                },
            )
        elif self.path == "/logs":
            self._write(HTTPStatus.OK, read_jsonl(REQUEST_LOG))
        elif self.path == "/activations":
            self._write(HTTPStatus.OK, read_jsonl(ACTIVATION_LOG))
        elif self.path == "/methods":
            self._write(HTTPStatus.OK, read_jsonl(METHOD_LOG))
        elif self.path == "/state-transitions":
            self._write(HTTPStatus.OK, worker_transitions())
        else:
            self._write(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._payload()
            if self.path == "/generate":
                self._write(HTTPStatus.OK, route_generate(payload))
            elif self.path == "/method":
                self._write(HTTPStatus.OK, configure_method(str(payload.get("method") or "")))
            else:
                self._write(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ValueError as exc:
            self._write(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._write(HTTPStatus.BAD_GATEWAY, {"error": f"controller_failed:{type(exc).__name__}:{exc}"})


if __name__ == "__main__":
    threading.Thread(target=idle_monitor, name="idle-monitor", daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
