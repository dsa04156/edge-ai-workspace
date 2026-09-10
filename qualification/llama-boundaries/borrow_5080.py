"""Approved fixed RTX5080 borrowing using the existing tested restoration saga.

hold: maximum eight minutes before restoration; an independent watchdog recovers
after parent death. restore: explicit crash-recovery entry point using persisted state.
No arbitrary node/deployment/manifest input is accepted.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "llama-offloading"))
from gpu_session import GPUSession, APP, WORKER

CONTEXT = "kubernetes-admin@kubernetes"


def kube(*args):
    proc = subprocess.run(["kubectl", f"--context={CONTEXT}", *args], capture_output=True, text=True, timeout=20)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip())
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def api(path, patch=None):
    if patch is None:
        return kube("get", "--raw", path)
    if path == APP:
        return kube("-n", "argocd", "patch", "applications.argoproj.io", "edge-orch-sensor-anomaly-demo", "--type=json", "-p", json.dumps(patch), "-o", "json")
    if path == WORKER + "/scale":
        return kube("-n", "llama-offload-eval", "patch", "deployments.apps", "llama-worker-spark", "--subresource=scale", "--type=json", "-p", json.dumps(patch), "-o", "json")
    raise ValueError("Mutation outside fixed approved scope")


def probe():
    svc = kube("-n", "edgex-edge", "get", "service", "sensor-anomaly-inference-server1", "-o", "json")
    base = f"http://{svc['spec']['clusterIP']}:8080"
    for path in ("/healthz", "/api/v1/augmentation-readyz"):
        with urllib.request.urlopen(base + path, timeout=5) as response:
            if response.status != 200:
                return False
    return True


def identity(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def restore(state):
    session = GPUSession(state, api=api, probe=probe)
    session.restore()
    print(json.dumps(session.view()), flush=True)


def watchdog(state):
    guard = json.loads((state / "guard.json").read_text())
    pid = guard["pid"]
    while identity(pid) == guard["start_ticks"] and time.time() < guard["deadline"]:
        time.sleep(1)
    if identity(pid) == guard["start_ticks"]:
        os.kill(pid, signal.SIGTERM)
        limit = time.monotonic() + 60
        while identity(pid) == guard["start_ticks"] and time.monotonic() < limit:
            time.sleep(1)
        if identity(pid) == guard["start_ticks"]:
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
    restore(state)


def hold(state):
    state.mkdir(parents=True, exist_ok=False)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    session = GPUSession(state, api=api, probe=probe)
    # Persistent recovery info is written before the first external mutation.
    (state / "guard.json").write_text(json.dumps({"pid": os.getpid(), "start_ticks": identity(os.getpid()), "deadline": time.time() + 480}))
    with open(state / "watchdog.log", "x") as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watchdog", "--state", str(state.resolve())], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        session.acquire(stop)
        (state / "prepared.json").write_text(json.dumps(session.view(), indent=2))
        print(json.dumps({"event": "prepared", "state": str(state)}), flush=True)
        deadline = json.loads((state / "guard.json").read_text())["deadline"]
        while not stop.is_set() and not (state / "STOP").exists() and time.time() < deadline:
            time.sleep(.5)
    finally:
        session.restore()
        (state / "restored.json").write_text(json.dumps(session.view(), indent=2))
        print(json.dumps({"event": "restored", "state": str(state)}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["hold", "restore", "watchdog", "check"])
    p.add_argument("--state", type=Path, required=True)
    args = p.parse_args()
    if args.action == "check":
        print(json.dumps({"sensor_health": probe(), "context": CONTEXT}))
    else:
        {"hold": hold, "restore": restore, "watchdog": watchdog}[args.action](args.state)
