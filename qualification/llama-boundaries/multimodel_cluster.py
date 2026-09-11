"""Bounded native GPU comparison on the three explicitly selected devices.

Reuses existing GPU containers, loopback API clients and llama-server d222767c7.
Only the llama-inference RuntimeService is suspended, then restored; no Pod,
GPU reservation, sensor service, shared controller or host setting is changed.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import bench

HERE = Path(__file__).resolve().parent
K = ["rtk", "proxy", "kubectl", "--context=kubernetes-admin@kubernetes"]
NODES = {
    "nano": {"node": "etri-dev0001-jetorn", "ns": "llama-offload-eval", "app": "llama-worker-nano", "cache": "/root/.ollama/models/blobs", "cuda": "cuda_jetpack6", "port": 18100},
    "agx": {"node": "etri-dev0005-jetagx", "ns": "llama-continuity-test", "app": "llama-agx", "cache": "/models/blobs", "cuda": "cuda_jetpack6", "port": 18110},
    "spark": {"node": "etri-ser0003-cg0ms0", "ns": "llama-continuity-test", "app": "llama-spark", "cache": "/models/blobs", "cuda": "cuda_v13", "port": 18110},
}


def command(args, timeout=30):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=timeout)


def pin_nodes():
    nodes = json.loads(json.dumps(NODES))
    for name, n in nodes.items():
        deployment = json.loads(command(K + ["-n", n["ns"], "get", "deployment", n["app"], "-o", "json"]))
        selector = ",".join(k + "=" + v for k, v in deployment["spec"]["selector"]["matchLabels"].items())
        pods = json.loads(command(K + ["-n", n["ns"], "get", "pods", "-l", selector, "-o", "json"]))["items"]
        pods = [p for p in pods if not p["metadata"].get("deletionTimestamp")
                and p.get("status", {}).get("phase") not in ("Failed", "Succeeded")]
        if len(pods) != 1 or pods[0]["spec"].get("nodeName") != n["node"]:
            raise RuntimeError("Exact device Pod identity not available: " + name)
        p = pods[0]
        if not all(c["ready"] for c in p["status"]["containerStatuses"]):
            raise RuntimeError("Pod not ready: " + name)
        n.update(pod=p["metadata"]["name"], uid=p["metadata"]["uid"], before=p)
    return nodes


def prefix(n, container="inference-runtime"):
    return K + ["-n", n["ns"], "exec", n["pod"], "-c", container, "--"]


def py(n, code, *args, timeout=30):
    return command(prefix(n, "api") + ["python", "-c", code, *map(str, args)], timeout)


def metrics(n):
    return json.loads(py(n, "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:" + str(n["port"]) + "/metrics',timeout=5).read().decode())"))


def stage_node(name, n, models, output):
    out = output / name
    out.mkdir()
    command(prefix(n) + ["mkdir", "-p", n["cache"]])
    staged = []
    for m in models:
        path = n["cache"] + "/sha256-" + m["sha256"]
        print(json.dumps({"event": "pulling_model", "node": name, "model": m["model"]}), flush=True)
        with (out / (m["slug"] + "-pull.log")).open("x") as log:
            subprocess.run(prefix(n) + ["/bin/ollama", "pull", m["model"]], stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=True)
        actual = command(prefix(n) + ["sha256sum", path], 180).split()[0]
        if actual != m["sha256"]:
            raise RuntimeError("Remote model digest mismatch")
        staged.append({"model": m["model"], "sha256": actual, "path": path})
        (out / "staged.json").write_text(json.dumps(staged, indent=2))
        print(json.dumps({"event": "model_staged", "node": name, "model": m["model"]}), flush=True)
    return staged


def service():
    return json.loads(command(K + ["-n", "platform-runtime", "get", "runtimeservice", "llama-inference", "-o", "json"]))


def set_suspended(expected, desired, uid):
    patch = [{"op": "test", "path": "/metadata/uid", "value": uid},
             {"op": "test", "path": "/spec/suspended", "value": expected},
             {"op": "replace", "path": "/spec/suspended", "value": desired}]
    command(K + ["-n", "platform-runtime", "patch", "runtimeservice", "llama-inference", "--type=json", "-p", json.dumps(patch)])


def wait_phase(phase, seconds=100):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        s = service()
        if s.get("status", {}).get("phase") == phase:
            return s
        time.sleep(2)
    raise TimeoutError("RuntimeService did not reach " + phase)


def watchdog(output):
    owner = json.loads((output / "owner.json").read_text())
    def identity():
        try:
            return Path(f"/proc/{owner['pid']}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except FileNotFoundError:
            return None
    while identity() == owner["identity"]:
        if (output / "service-restored.json").exists():
            return
        time.sleep(5)
    # Each native worker has its own 900s timeout. Do not restore a service over
    # an orphaned measurement process. The fallback operates only on our UID.
    time.sleep(930)
    if (output / "service-restored.json").exists():
        return
    current = service()
    if current["metadata"]["uid"] != owner["uid"]:
        raise RuntimeError("Service replaced; watchdog will not mutate it")
    if current["spec"]["suspended"]:
        set_suspended(True, False, owner["uid"])
        (output / "watchdog-restored.json").write_text(json.dumps(wait_phase("Serving", 120), indent=2))


def runtime_config(n, m):
    cfg = bench.load_config(HERE / "common-0332.json")
    cfg["model"] = {"family": m["model"], "quantization": "Q8_0", "sha256": m["sha256"],
                    "path": n["cache"] + "/sha256-" + m["sha256"]}
    cfg["runtime"].update(binary="/usr/lib/ollama/llama-server", context=4096,
        library_path="/usr/lib/ollama:/usr/lib/ollama/" + n["cuda"] + ":/usr/lib/aarch64-linux-gnu/nvidia:/usr/lib/aarch64-linux-gnu/tegra",
        backend_path="/usr/lib/ollama/" + n["cuda"] + "/libggml-cuda.so")
    return cfg


def run_cell(name, n, m, block, output):
    out = output / name / (m["slug"] + f"-b{block}")
    out.mkdir(parents=True)
    token = output.name + "-" + name + "-" + m["slug"] + f"-b{block}"
    remote = "/dev/shm/" + token
    pidfile = remote + ".pid"
    cfg = runtime_config(n, m)
    r = cfg["runtime"]
    env = ["env", "LD_LIBRARY_PATH=" + r["library_path"], "GGML_BACKEND_PATH=" + r["backend_path"]]
    version = command(prefix(n) + env + [r["binary"], "--version"])
    if "d222767c7" not in version:
        raise RuntimeError("Runtime revision mismatch")
    if metrics(n)["active_requests"] or metrics(n)["queue_length"] or metrics(n)["model_vram_mib"]:
        raise RuntimeError("Existing worker is not idle/unloaded")
    py(n, "import socket;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',18200));s.close()")
    command(prefix(n, "api") + ["mkdir", remote])
    for filename in ("bench.py", "multimodel_client.py"):
        command(K + ["-n", n["ns"], "cp", "--no-preserve=true", str(HERE / filename), n["pod"] + ":" + remote + "/" + filename, "-c", "api"])
    (out / "provenance.json").write_text(json.dumps({"node": name, "physical_node": n["node"], "pod_uid": n["uid"],
        "config": cfg, "version": version, "model": m, "block": block,
        "timing_scope": "device-local API sidecar to runtime loopback", "quality_evaluation": False}, indent=2))
    events, samples = bench.Journal(out / "events.jsonl"), bench.Journal(out / "resources.jsonl")
    server = client = None
    log = open(out / "server.log", "x")
    started = time.monotonic()
    cleanup = {"process_exited": False, "port_released": False}
    try:
        launch = "set -e; echo $$ > " + shlex.quote(pidfile) + "; exec " + shlex.join(env + bench.runtime_args(cfg))
        server = subprocess.Popen(prefix(n) + ["timeout", "--signal=TERM", "--kill-after=15s", "900", "sh", "-c", launch], stdout=log, stderr=subprocess.STDOUT)
        events.write({"event": "activation_started", "timestamp": time.time()})
        py(n, "import time,urllib.request,json\nfor i in range(180):\n try:\n  if json.load(urllib.request.urlopen('http://127.0.0.1:18200/health',timeout=1)).get('status')=='ok':break\n except (OSError,ValueError):pass\n time.sleep(.5)\nelse:raise RuntimeError('activation deadline')", timeout=110)
        text = (out / "server.log").read_text()
        layers = re.search(r"offloaded (\d+)/(\d+) layers to GPU", text)
        pid = command(prefix(n) + ["cat", pidfile]).strip()
        maps = command(prefix(n) + ["cat", "/proc/" + pid + "/maps"])
        if not layers or layers[1] != layers[2] or int(layers[1]) == 0 or "libggml-cuda.so" not in maps:
            raise RuntimeError("Full GPU offload + owned CUDA maps not verified")
        events.write({"event": "gpu_health_ready", "timestamp": time.time(), "activation_health_ms": (time.monotonic() - started) * 1000, "layers": list(layers.groups()), "pid": pid})
        print(json.dumps({"event": "cell_gpu_ready", "node": name, "model": m["model"], "block": block, "layers": list(layers.groups())}), flush=True)
        with open(out / "client.log", "x") as client_log:
            client = subprocess.Popen(prefix(n, "api") + ["python", remote + "/multimodel_client.py", "--output", remote + "/workload", "--node", n["node"], "--block", str(block)], stdout=client_log, stderr=subprocess.STDOUT)
            while client.poll() is None:
                if server.poll() is not None or time.monotonic() - started > 840:
                    raise RuntimeError("Owned server exited or experiment deadline")
                shell = "cat /proc/" + pid + "/status; cat /proc/meminfo; cat /sys/devices/platform/bus@0/17000000.gpu/load 2>/dev/null || true; nvidia-smi --query-gpu=name,temperature.gpu,memory.used,power.draw --format=csv,noheader,nounits 2>/dev/null || true; cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null || true"
                sample = command(prefix(n) + ["sh", "-c", shell])
                samples.write({"timestamp": time.time(), "sample": sample})
                available = re.search(r"MemAvailable:\s+(\d+)", sample)
                if available and int(available[1]) < 700 * 1024:
                    raise RuntimeError("Device RAM guard")
                temperatures = re.findall(r"(?m)^([0-9]{4,6})$", sample)
                gpu_temp = re.search(r"(?m)^.+,\s*([0-9.]+),\s*", sample)
                if any(int(t) >= 80000 for t in temperatures) or (gpu_temp and float(gpu_temp[1]) >= 80):
                    raise RuntimeError("Device temperature guard")
                time.sleep(3)
            if client.returncode:
                raise RuntimeError("Client failed; inspect preserved client.log")
    finally:
        try:
            command(K + ["-n", n["ns"], "cp", n["pod"] + ":" + remote + "/workload", str(out / "workload"), "-c", "api"], 45)
        except Exception as e:
            cleanup["export_error"] = str(e)
        if server is not None:
            try:
                pid = command(prefix(n) + ["cat", pidfile]).strip()
                if not pid.isdigit():
                    raise ValueError("Invalid owned PID")
                # Verify PID still refers to this exact model and endpoint before signaling.
                script = "if [ -e /proc/" + pid + "/cmdline ]; then tr '\\000' ' ' < /proc/" + pid + "/cmdline; fi"
                cmdline = command(prefix(n) + ["sh", "-c", script])
                if cmdline:
                    if cfg["model"]["path"] not in cmdline or "18200" not in cmdline:
                        raise RuntimeError("PID identity changed")
                    command(prefix(n) + ["kill", "-TERM", pid])
                server.wait(timeout=25)
                cleanup["process_exited"] = True
                py(n, "import socket;s=socket.socket();s.settimeout(2);r=s.connect_ex(('127.0.0.1',18200));s.close();assert r != 0")
                cleanup["port_released"] = True
            except Exception as e:
                cleanup["error"] = str(e)
        if client is not None and client.poll() is None:
            client.wait(timeout=190)
        log.close()
        events.close()
        samples.close()
        (out / "cleanup.json").write_text(json.dumps(cleanup, indent=2))
    if not cleanup["process_exited"] or not cleanup["port_released"] or cleanup.get("export_error"):
        raise RuntimeError("Cleanup/export verification failed")
    print(json.dumps({"event": "cell_complete", "node": name, "model": m["model"], "block": block}), flush=True)


def run_node(name, n, models, output, order, stage_roots):
    deadline = time.monotonic() + 1800
    while True:
        ready = False
        for stage_root in stage_roots:
            try:
                staged = json.loads((stage_root / name / "staged.json").read_text())
                pinned = json.loads((stage_root / "nodes-before.json").read_text())[name]
                ready = pinned["uid"] == n["uid"] and {m["sha256"] for m in models} == {m["sha256"] for m in staged}
            except (OSError, ValueError, KeyError):
                continue
            if ready:
                break
        if ready:
            break
        if time.monotonic() > deadline:
            raise TimeoutError("All six pinned models must be staged before GPU measurement")
        time.sleep(5)
    print(json.dumps({"event": "device_staging_verified", "node": name}), flush=True)
    # Abort this device after a failed cell; retain partial results; other devices independent.
    for block, slugs in enumerate(order):
        for slug in slugs:
            run_cell(name, n, next(m for m in models if m["slug"] == slug), block, output)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["stage", "run", "watch"])
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--nodes", nargs="+", choices=list(NODES), default=list(NODES))
    p.add_argument("--stage-root", nargs="+", type=Path, default=[])
    a = p.parse_args()
    if a.action == "watch":
        watchdog(a.output)
        return
    models = json.loads(a.models.read_text())
    nodes = pin_nodes()
    nodes = {name: n for name, n in nodes.items() if name in a.nodes}
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "nodes-before.json").write_text(json.dumps(nodes, indent=2))
    (a.output / "models.json").write_text(json.dumps(models, indent=2))
    if a.action == "stage":
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {name: pool.submit(stage_node, name, n, models, a.output) for name, n in nodes.items()}
            for name, f in futures.items():
                f.result()
        return
    before = service()
    if not a.stage_root:
        raise ValueError("run requires --stage-root with per-device hash verification")
    (a.output / "service-before.json").write_text(json.dumps(before, indent=2))
    if before["spec"]["suspended"] or before["status"].get("load", {}).get("inFlightAndPending", 0):
        raise RuntimeError("Llama service must be serving and idle")
    order, rng = [[m["slug"] for m in sorted(models, key=lambda m: m["size_bytes"])]], random.Random(20260910)
    for _ in range(2):
        slugs = [m["slug"] for m in models]
        rng.shuffle(slugs)
        order.append(slugs)
    (a.output / "plan.json").write_text(json.dumps({"order": order, "blocks": 3, "nodes": list(nodes),
        "order_design": "first compatibility block ascending model file size; two seeded randomized blocks",
        "scope": "fixed-work GPU serving performance; no quality or live offloading claims", "started_at": time.time()}, indent=2))
    (a.output / "source-hashes.json").write_text(json.dumps({f: bench.digest(HERE / f) for f in
        ("bench.py", "multimodel_client.py", "multimodel_cluster.py", "common-0332.json", "config.json")}, indent=2))
    paused = False
    errors = {}
    owner = {"pid": os.getpid(), "identity": Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()[19],
             "uid": before["metadata"]["uid"]}
    (a.output / "owner.json").write_text(json.dumps(owner))
    with (a.output / "watchdog.log").open("x") as log:
        subprocess.Popen(["rtk", "proxy", sys.executable, str(Path(__file__).resolve()), "watch", "--models", str(a.models.resolve()),
                          "--output", str(a.output.resolve())], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        set_suspended(False, True, before["metadata"]["uid"])
        paused = True
        wait_phase("Suspended")
        (a.output / "suspended.json").write_text(json.dumps(service(), indent=2))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(run_node, name, n, models, a.output, order, a.stage_root): name for name, n in nodes.items()}
            for f in concurrent.futures.as_completed(futures):
                name = futures[f]
                try:
                    f.result()
                except Exception as e:
                    errors[name] = str(e)
                    print(json.dumps({"event": "device_failed", "node": name, "error": str(e)}), flush=True)
    finally:
        (a.output / "errors.json").write_text(json.dumps(errors, indent=2))
        if paused:
            set_suspended(True, False, before["metadata"]["uid"])
            after = wait_phase("Serving", 120)
            (a.output / "service-restored.json").write_text(json.dumps(after, indent=2))
        (a.output / "nodes-after.json").write_text(json.dumps(pin_nodes(), indent=2))
    if errors:
        raise RuntimeError("Some devices failed; see errors.json")


if __name__ == "__main__":
    main()
