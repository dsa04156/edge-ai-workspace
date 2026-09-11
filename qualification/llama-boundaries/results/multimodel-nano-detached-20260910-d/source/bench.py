"""Isolated llama-server qualification. Standard library only; no production writes.

smoke owns only its child process. replay never activates/stops a remote server.
Raw token IDs and final server token counts, not SSE chunks, define workload.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid


def load_config(path):
    obj = json.loads(Path(path).read_text())
    parent = obj.pop("extends", None)
    if parent is None:
        return obj
    base = load_config(Path(path).parent / parent)
    for key, value in obj.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def api(base, path, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers=headers())
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def headers():
    values = {"Content-Type": "application/json"}
    if os.getenv("BOUNDARY_KEY_FILE"):
        values["Authorization"] = "Bearer " + Path(os.environ["BOUNDARY_KEY_FILE"]).read_text().strip()
    return values


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return {"exit_code": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"exit_code": None, "stdout": None, "stderr": str(e)}


class Journal:
    def __init__(self, path):
        self.file = open(path, "x", buffering=1)
        self.lock = threading.Lock()

    def write(self, value):
        with self.lock:
            self.file.write(json.dumps(value, ensure_ascii=False) + "\n")
            self.file.flush()

    def close(self):
        self.file.close()


def thermal_zones(root=Path('/sys/class/thermal')):
    rows = []
    for zone in root.glob('thermal_zone*'):
        try:
            rows.append({'name': (zone / 'type').read_text().strip(),
                         'temperature_c': int((zone / 'temp').read_text()) / 1000})
        except (OSError, ValueError, TypeError) as exc:
            rows.append({'name': zone.name, 'temperature_c': None,
                         'error': type(exc).__name__})
    return rows


def resources():
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        mem[key] = int(value.split()[0])
    cpu = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    gpu = command(["nvidia-smi", "--query-gpu=uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,power.limit", "--format=csv,noheader,nounits"])
    rows = []
    if gpu["exit_code"] == 0:
        for row in csv.reader(gpu["stdout"].splitlines(), skipinitialspace=True):
            values = {"uuid": row[0], "name": row[1]}
            for key, val in zip(["memory_used_mib", "memory_total_mib", "utilization_pct", "temperature_c", "power_w", "power_limit_w"], row[2:]):
                try:
                    values[key] = float(val)
                except ValueError:
                    values[key] = None
            rows.append(values)
    return {"timestamp": time.time(), "host": socket.gethostname(), "cpu_ticks": cpu,
            "ram_used_mib": (mem["MemTotal"] - mem["MemAvailable"]) / 1024,
            "ram_available_mib": mem["MemAvailable"] / 1024, "gpu": rows or None,
            "gpu_error": gpu["stderr"] if gpu["exit_code"] else None,
            "thermal_zones": thermal_zones(),
            "system_power_w": None, "power_scope": "GPU device only, includes other processes",
            "throttling": command(["nvidia-smi", "--query-gpu=clocks_event_reasons.active", "--format=csv,noheader"]) }


def check_safety(sample, cfg):
    if sample["ram_available_mib"] < cfg["min_available_ram_mib"]:
        raise RuntimeError("RAM safety limit")
    for zone in sample.get('thermal_zones', []):
        if zone['temperature_c'] is not None and zone['temperature_c'] >= cfg['max_temperature_c']:
            raise RuntimeError('Thermal zone safety limit: ' + zone['name'])
    for gpu in sample.get("gpu") or []:
        if gpu["temperature_c"] is not None and gpu["temperature_c"] >= cfg["max_temperature_c"]:
            raise RuntimeError("GPU temperature safety limit")


def gpu_processes():
    result = command(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"])
    if result["exit_code"] != 0:
        return None
    return [int(row[0]) for row in csv.reader(result["stdout"].splitlines()) if row and row[0].strip().isdigit()]


def stream(base, body, *, run_id, request_id, phase, node, planned_at, timeout):
    sent = time.time()
    start = time.monotonic()
    record = {"run_id": run_id, "request_id": request_id, "phase": phase, "selected_node": node,
              "requester": socket.gethostname(), "planned_at": planned_at, "sent_at": sent,
              "generator_delay_ms": max(0, (sent - planned_at) * 1000), "first_at": None,
              "input_tokens_requested": len(body["prompt"]), "output_tokens_requested": body["n_predict"],
              "actual_input_tokens": None, "actual_output_tokens": None, "ttft_ms": None,
              "decode_tokens_per_second": None, "server_timings": None, "status": "failed",
              "retry": False, "fallback": False, "partial_response": False,
              "pure_network_ms": None, "cache_prompt": body.get("cache_prompt"), "ignore_eos": body.get("ignore_eos")}
    final = None
    req = urllib.request.Request(base + "/completion", data=json.dumps({**body, "stream": True}).encode(), headers=headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for raw in response:
                if time.monotonic() - start > timeout:
                    raise TimeoutError("overall request deadline")
                if not raw.startswith(b"data:"):
                    continue
                payload = raw[5:].strip()
                if payload == b"[DONE]":
                    break
                item = json.loads(payload)
                if item.get("error"):
                    raise RuntimeError(str(item["error"]))
                # Empty keepalives and terminal timing chunks are not generated output.
                if item.get("content") and record["first_at"] is None:
                    record["first_at"] = time.time()
                    record["ttft_ms"] = (time.monotonic() - start) * 1000
                    record["partial_response"] = True
                if item.get("stop") is True:
                    final = item
        if final is None:
            raise ValueError("stream ended without terminal token counters")
        timings = final.get("timings", {})
        record.update(actual_input_tokens=final.get("tokens_evaluated"),
                      actual_output_tokens=final.get("tokens_predicted", timings.get("predicted_n")),
                      server_timings=timings, decode_tokens_per_second=timings.get("predicted_per_second"),
                      stop_type=final.get("stop_type"), tokens_cached=final.get("tokens_cached"),
                      status="ok")
        if record["actual_input_tokens"] != len(body["prompt"]):
            record["status"] = "input_length_mismatch"
        elif record["actual_output_tokens"] != body["n_predict"]:
            record["status"] = "short_output"
        elif body.get("cache_prompt") is False and timings.get("cache_n", 0) > 0:
            record["status"] = "unexpected_cache_reuse"
        record["zero_prefix_reuse_verified"] = timings.get("cache_n") == 0
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
        if isinstance(e, (TimeoutError, socket.timeout)):
            record["status"] = "timeout"
        elif isinstance(e, urllib.error.HTTPError) and e.code in (429, 503):
            record["status"] = "rejected"
    record.update(completed_at=time.time(), latency_ms=(time.monotonic() - start) * 1000)
    return record


def dataset(base, count, cfg):
    """Synthetic fixed-work token fixture; not an instruction-following quality eval."""
    size = cfg["input_tokens"]
    data = []
    for i in range(count):
        text = f"Case {cfg['seed']} number {i}. Explain how a factory monitors temperature and vibration. " + "A sensor records a measurement for comparison. " * size
        tokens = api(base, "/tokenize", {"content": text, "add_special": True})["tokens"][:size]
        if len(tokens) != size or not all(isinstance(t, int) for t in tokens):
            raise ValueError("tokenizer did not supply exact integer token fixture")
        data.append({"request_id": f"prompt-{i:04d}", "prompt": tokens, "n_predict": cfg["output_tokens"],
                     "cache_prompt": False, "ignore_eos": True, "temperature": 0, "seed": cfg["seed"] + i})
    return data


def percentile(values, q):
    if not values:
        return None
    a = sorted(values)
    pos = (len(a) - 1) * q
    lo = math.floor(pos)
    return a[lo] + (a[math.ceil(pos)] - a[lo]) * (pos - lo)


def summarize(records):
    records = [r for r in records if r["phase"] == "measure"]
    good = [r for r in records if r["status"] == "ok"]
    span = max((r["completed_at"] for r in records), default=0) - min((r["planned_at"] for r in records), default=0)
    return {"n": len(records), "successful": len(good), "failure_rate": 1 - len(good) / len(records) if records else None,
            "p50_latency_ms": percentile([r["latency_ms"] for r in good], .5),
            "p95_latency_ms": percentile([r["latency_ms"] for r in good], .95),
            "p50_ttft_ms": percentile([r["ttft_ms"] for r in good if r["ttft_ms"] is not None], .5),
            "p95_ttft_ms": percentile([r["ttft_ms"] for r in good if r["ttft_ms"] is not None], .95),
            "completed_requests_per_s": len(good) / span if span > 0 else None,
            "output_tokens_per_s": sum(r["actual_output_tokens"] for r in good) / span if span > 0 else None,
            "threshold_validated": False, "note": "Smoke quantiles are descriptive, not a saturation boundary."}


def runtime_args(cfg):
    r = cfg["runtime"]
    return [r["binary"], "--model", cfg["model"]["path"], "--host", r["host"], "--port", str(r["port"]),
            "--threads", str(r["threads"]), "--ctx-size", str(r["context"]), "--batch-size", str(r["batch"]),
            "--ubatch-size", str(r["ubatch"]), "--parallel", str(r["parallel_slots"]),
            "--gpu-layers", str(r["gpu_layers"]), "--cache-type-k", r["kv_type"], "--cache-type-v", r["kv_type"],
            "--flash-attn", r["flash_attention"], "--cache-ram", "0", "--cache-reuse", "0", "--metrics", "--verbose"]


def smoke(cfg, output, hold_seconds=0, workload_sweep=False):
    output.mkdir(parents=True, exist_ok=False)
    run_id = output.name
    r = cfg["runtime"]
    base = f"http://{'127.0.0.1' if r['host'] == '0.0.0.0' else r['host']}:{r['port']}"
    # Fail before launch if this endpoint is already owned by another process.
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((r["host"], r["port"]))
    if digest(cfg["model"]["path"]) != cfg["model"]["sha256"]:
        raise ValueError("model SHA256 mismatch")
    env = {**os.environ, "LD_LIBRARY_PATH": r["library_path"], "GGML_BACKEND_PATH": r["backend_path"]}
    version = subprocess.check_output([r["binary"], "--version"], env=env, stderr=subprocess.STDOUT, text=True)
    if r["reported_revision"] not in version:
        raise ValueError("runtime revision mismatch")
    help_text = subprocess.check_output([r["binary"], "--help"], env=env, stderr=subprocess.STDOUT, text=True)
    (output / "runtime-help.txt").write_text(help_text)
    provenance = {"config": cfg, "hostname": socket.gethostname(), "architecture": platform.machine(),
                  "kernel": platform.release(), "os_release": Path("/etc/os-release").read_text(),
                  "runtime_version": version, "binary_sha256": digest(r["binary"]),
                  "model_sha256_verified": True, "arguments": runtime_args(cfg),
                  "cpu": command(["lscpu"]), "driver": command(["nvidia-smi"]),
                  "cuda_toolkit": command(["nvcc", "--version"]),
                  "power_mode": command(["nvpmodel", "-q"]),
                  "upstream_revision_verified": False, "method": "cached-on-demand", "image_preparation": "not applicable: host process"}
    (output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2))
    events, samples, requests = [Journal(output / f"{name}.jsonl") for name in ("events", "resources", "requests")]
    stop = threading.Event()
    safety_failure = []
    def collect():
        previous = None
        while not stop.is_set():
            sample = resources()
            ticks = sample["cpu_ticks"]
            if previous:
                total = sum(ticks) - sum(previous)
                sample["cpu_utilization_pct"] = 100 * (1 - (sum(ticks[3:5]) - sum(previous[3:5])) / total) if total else None
            else:
                sample["cpu_utilization_pct"] = None
            previous = ticks
            samples.write(sample)
            try:
                check_safety(sample, cfg["safety"])
            except RuntimeError as e:
                safety_failure.append(str(e))
            stop.wait(.5)
    check_safety(resources(), cfg["safety"])
    jetson = r.get("gpu_verification") == "jetson-owned-cuda-maps"
    if jetson and platform.machine() != "aarch64":
        raise RuntimeError("Jetson verification is restricted to ARM64")
    if not jetson and gpu_processes() != []:
        raise RuntimeError("GPU compute workload present or inventory unavailable; not borrowing it")
    monitor = threading.Thread(target=collect, daemon=True)
    monitor.start()
    proc = None
    records = []
    started = time.monotonic()
    try:
        events.write({"timestamp": time.time(), "event": "activation_requested", "old_state": "CACHED", "new_state": "LOADING"})
        with open(output / "server.log", "x") as log:
            args = runtime_args(cfg)
            if os.getenv("BOUNDARY_KEY_FILE"):
                args += ["--api-key-file", os.environ["BOUNDARY_KEY_FILE"]]
            elif r["host"] == "0.0.0.0":
                raise ValueError("LAN listener requires a private API key file")
            proc = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        health_started = time.monotonic()
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"llama-server exited {proc.returncode}; inspect server.log")
            if safety_failure or time.monotonic() - health_started > cfg["safety"]["activation_timeout_s"]:
                raise RuntimeError(f"activation aborted: {safety_failure or 'deadline'}")
            try:
                if api(base, "/health", timeout=1).get("status") == "ok":
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.2)
        log_text = (output / "server.log").read_text()
        offload = re.search(r"offloaded (\d+)/(\d+) layers to GPU", log_text)
        pids = gpu_processes()
        owned_cuda = proc.pid in (pids or [])
        if jetson:
            owned_cuda = "libggml-cuda.so" in Path(f"/proc/{proc.pid}/maps").read_text()
        if not offload or int(offload[1]) == 0 or offload[1] != offload[2] or not owned_cuda:
            raise RuntimeError("GPU verification failed: require all layers plus owned PID in nvidia-smi")
        events.write({"timestamp": time.time(), "event": "health_ok", "elapsed_ms": (time.monotonic() - started) * 1000, "gpu_layers": list(offload.groups()), "pid": proc.pid})
        fixtures = dataset(base, cfg["safety"]["max_smoke_requests"] + 2, cfg["workload"])
        (output / "dataset.json").write_text(json.dumps(fixtures, indent=2))
        probe = {**fixtures[0], "prompt": fixtures[0]["prompt"][:32], "n_predict": 1}
        for i, body in enumerate([probe, fixtures[1], *fixtures[2:]]):
            if safety_failure or time.monotonic() - started > cfg["safety"]["max_smoke_duration_s"]:
                raise RuntimeError(f"smoke safety stop: {safety_failure or 'wall deadline'}")
            phase = "readiness_probe" if i == 0 else "warmup" if i == 1 else "measure"
            rec = stream(base, body, run_id=run_id, request_id=body["request_id"], phase=phase,
                         node=socket.gethostname(), planned_at=time.time(), timeout=cfg["safety"]["request_timeout_s"])
            rec["concurrency"] = 1
            rec["model_sha256"] = cfg["model"]["sha256"]
            rec["runtime_revision"] = r["reported_revision"]
            rec["method"] = "cached-on-demand"
            requests.write(rec)
            records.append(rec)
            if rec["status"] != "ok":
                raise RuntimeError(f"request failed: {rec}")
            if phase == "readiness_probe":
                events.write({"timestamp": time.time(), "event": "inference_ready", "old_state": "LOADING", "new_state": "ACTIVE", "activation_ms": (time.monotonic() - started) * 1000,
                              "cuda_init_ms": None, "model_read_ms": None, "gpu_load_ms": None, "note": "Composite includes tokenizer fixture preparation and explicit probe; component times unavailable."})
        for concurrency in cfg.get("ramp_concurrency", []):
            if concurrency not in (2, 4, 8):
                raise ValueError("Only explicit small ramp stages 2,4,8 supported")
            if safety_failure or time.monotonic() - started > cfg["safety"]["max_smoke_duration_s"]:
                raise RuntimeError(f"ramp safety stop: {safety_failure or 'wall deadline'}")
            planned = time.time()
            stage = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                pending = [pool.submit(stream, base, fixtures[2 + i % (len(fixtures) - 2)],
                                       run_id=run_id, request_id=f"c{concurrency}-{i}", phase="measure",
                                       node=socket.gethostname(), planned_at=planned,
                                       timeout=cfg["safety"]["request_timeout_s"])
                           for i in range(concurrency)]
                for future in concurrent.futures.as_completed(pending):
                    rec = future.result()
                    rec.update(concurrency=concurrency, model_sha256=cfg["model"]["sha256"],
                               runtime_revision=r["reported_revision"], method="cached-on-demand")
                    requests.write(rec)
                    records.append(rec)
                    stage.append(rec)
            if any(rec["status"] != "ok" for rec in stage):
                raise RuntimeError("Ramp failure; later stages cancelled")
        summary = summarize(records)
        summary["by_concurrency"] = {str(c): summarize([rec for rec in records if rec["concurrency"] == c]) for c in sorted({rec["concurrency"] for rec in records})}
        (output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
        if workload_sweep:
            import sweep
            def guard_sweep():
                if safety_failure or proc.poll() is not None:
                    raise RuntimeError(f'Sweep safety stop: {safety_failure}')
            sweep.run(base, output / 'sweep', socket.gethostname(), guard_sweep)
        if hold_seconds:
            events.write({"timestamp": time.time(), "event": "paired_client_window", "maximum_seconds": hold_seconds})
            print(json.dumps({"event": "paired_client_window", "pid": os.getpid()}), flush=True)
            deadline = time.monotonic() + hold_seconds
            while time.monotonic() < deadline:
                if (output / "STOP").exists():
                    break
                if safety_failure or proc.poll() is not None:
                    raise RuntimeError(f"server window safety stop: {safety_failure}")
                time.sleep(.2)
    finally:
        if proc is not None:
            release_start = time.monotonic()
            events.write({"timestamp": time.time(), "event": "deactivation_requested", "pid": proc.pid})
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
            pids = gpu_processes()
            until = time.monotonic() + 10
            while pids is not None and proc.pid in pids and time.monotonic() < until:
                time.sleep(.2)
                pids = gpu_processes()
            returned = (pids is not None and proc.pid not in pids) if not jetson else None
            events.write({"timestamp": time.time(), "event": "release_checked", "old_state": "ACTIVE", "new_state": "CACHED" if returned else "UNVERIFIED", "process_exited": proc.poll() is not None, "gpu_allocation_released": returned,
                          "kubernetes_reservation": "not applicable: host process", "release_ms": (time.monotonic() - release_start) * 1000, "model_file_retained": Path(cfg["model"]["path"]).exists()})
        stop.set()
        monitor.join(timeout=15)
        for journal in (events, samples, requests):
            journal.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["smoke"])
    p.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--key-file", type=Path)
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--hold-seconds", type=int, default=0, choices=range(0, 301), metavar="0..300")
    args = p.parse_args()
    if args.key_file:
        os.environ["BOUNDARY_KEY_FILE"] = str(args.key_file.resolve())
    def terminate(signum, frame):
        raise KeyboardInterrupt(f"termination signal {signum}")
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGHUP, terminate)
    smoke(load_config(args.config), args.output, args.hold_seconds, args.sweep)


if __name__ == "__main__":
    main()
