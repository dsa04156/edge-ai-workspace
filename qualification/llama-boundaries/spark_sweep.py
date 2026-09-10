"""Bounded common-setting GPU sweep in the existing, idle DGX Spark demo Pod.

Pauses only the ordered demo controller; retains its PVC and restores replicas.
The owned native server has an independent 360-second timeout and loopback bind.
Model files, worker Pod, GPU reservation and Ollama daemon remain unchanged.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time
import urllib.request

import bench

KUBE = ["rtk", "proxy", "kubectl", "--context=kubernetes-admin@kubernetes"]
NS = "llama-continuity-test"
NODE = "etri-ser0003-cg0ms0"
CONTROLLER = "ordered-offload-controller"
DEMO = "http://offload-demo.192.168.0.56.sslip.io/api/demo"


def command(args, **kw):
    return subprocess.check_output(args, text=True, timeout=kw.pop("timeout", 30), **kw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cfg = bench.load_config(Path(__file__).with_name("spark-sweep.json"))
    with urllib.request.urlopen(DEMO, timeout=10) as response:
        before = json.load(response)
    if before["active"] or not before["can_start"]:
        raise RuntimeError("Demo must be idle and ready before borrowing Spark")
    pods = json.loads(command(KUBE + ["-n", NS, "get", "pods", "-l", "app=llama-spark", "-o", "json"]))["items"]
    pods = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
    if len(pods) != 1 or pods[0]["spec"]["nodeName"] != NODE:
        raise RuntimeError("Expected exactly one Spark Pod on the fixed DGX node")
    pod = pods[0]["metadata"]["name"]
    prefix = KUBE + ["-n", NS, "exec", pod, "-c", "inference-runtime", "--"]
    api_prefix = KUBE + ["-n", NS, "exec", pod, "-c", "api", "--"]
    deployment = json.loads(command(KUBE + ["-n", NS, "get", "deployment", CONTROLLER, "-o", "json"]))
    replicas = deployment["spec"]["replicas"]
    if replicas != 1:
        raise RuntimeError("Expected running single-replica demo controller")
    r = cfg["runtime"]
    env = ["env", "LD_LIBRARY_PATH=" + r["library_path"], "GGML_BACKEND_PATH=" + r["backend_path"]]
    model_hash = command(prefix + ["sha256sum", cfg["model"]["path"]]).split()[0]
    version = command(prefix + env + [r["binary"], "--version"], stderr=subprocess.STDOUT)
    if model_hash != cfg["model"]["sha256"] or r["reported_revision"] not in version:
        raise RuntimeError("Common model/runtime identity mismatch")
    processes = command(prefix + ["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"])
    if processes.strip():
        raise RuntimeError("Spark GPU has another compute process")
    provenance = {"config": cfg, "node": NODE, "pod": pod, "pod_uid": pods[0]["metadata"]["uid"],
                  "containers": pods[0]["status"]["containerStatuses"], "runtime_version": version,
                  "model_sha256": model_hash, "gpu_inventory": command(prefix + ["nvidia-smi"]),
                  "runtime_binary_sha256": command(prefix + ["sha256sum", r["binary"]]).split()[0],
                  "timing_scope": "API sidecar client to native server in same Pod over loopback",
                  "client_resources": pods[0]["spec"]["containers"][0]["resources"],
                  "reservation": "Existing Spark Pod and nvidia.com/gpu=1 retained"}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    (output / "demo-before.json").write_text(json.dumps(before, indent=2))
    token = output.name
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", token):
        raise ValueError("Output basename must be a simple run identifier")
    remote_dir = "/dev/shm/" + token
    pid_path = "/dev/shm/" + token + ".pid"
    events = bench.Journal(output / "events.jsonl")
    samples = bench.Journal(output / "resources.jsonl")
    server = client = None
    paused = False
    def on_signal(signum, frame):
        raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        paused = True
        command(KUBE + ["-n", NS, "scale", "deployment/" + CONTROLLER, "--replicas=0"])
        command(KUBE + ["-n", NS, "wait", "--for=delete", "pod", "-l", "app=" + CONTROLLER, "--timeout=45s"], timeout=50)
        events.write({"event": "demo_paused", "timestamp": time.time()})
        # CACHED is a precondition, not an instruction to unload somebody else's model.
        health = json.loads(command(api_prefix + ["python", "-c", "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:18110/health').read().decode())"]))
        if health["model_loaded"] or health["node_state"] != "CACHED":
            raise RuntimeError("Spark model must remain CACHED")
        command(api_prefix + ["mkdir", remote_dir])
        for name in ("bench.py", "sweep.py"):
            command(KUBE + ["-n", NS, "cp", "--no-preserve=true", str(Path(__file__).with_name(name)), pod + ":" + remote_dir + "/" + name, "-c", "api"])
        cmd = "set -e; echo $$ > " + shlex.quote(pid_path) + "; exec " + shlex.join(env + bench.runtime_args(cfg))
        log = open(output / "server.log", "x")
        server = subprocess.Popen(prefix + ["timeout", "--signal=TERM", "--kill-after=10s", "360", "sh", "-c", cmd], stdout=log, stderr=subprocess.STDOUT)
        warmup = """import sys,time,json
sys.path.insert(0,sys.argv[1]); import bench
base='http://127.0.0.1:18200'
for i in range(90):
 try:
  if bench.api(base,'/health',timeout=1).get('status')=='ok': break
 except (OSError,ValueError): pass
 time.sleep(.5)
else: raise RuntimeError('activation timeout')
b=bench.dataset(base,1,{'input_tokens':512,'output_tokens':128,'seed':20260907})[0]
r=bench.stream(base,b,run_id=sys.argv[1],request_id='warmup',phase='warmup',node='etri-ser0003-cg0ms0',planned_at=time.time(),timeout=30)
print(json.dumps(r)); assert r['status']=='ok' and r['zero_prefix_reuse_verified']
"""
        ready = command(api_prefix + ["python", "-c", warmup, remote_dir], timeout=100)
        (output / "warmup.json").write_text(ready)
        logs = (output / "server.log").read_text()
        layers = re.search(r"offloaded (\d+)/(\d+) layers to GPU", logs)
        gpu = command(prefix + ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader"])
        if not layers or layers[1] != layers[2] or int(layers[1]) == 0 or "llama-server" not in gpu:
            raise RuntimeError("Full GPU layer and owned process evidence required")
        events.write({"event": "gpu_ready", "layers": layers.groups(), "gpu_process": gpu, "timestamp": time.time()})
        print("GPU verified; warmup complete; starting unchanged common sweep", flush=True)
        with open(output / "client.log", "x") as client_log:
            client = subprocess.Popen(api_prefix + ["timeout", "280", "python", remote_dir + "/sweep.py", "--node", NODE, "--output", remote_dir + "/sweep"], stdout=client_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 290
            while client.poll() is None:
                gpu = command(prefix + ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,power.draw", "--format=csv,noheader,nounits"])
                sample = {"timestamp": time.time(), "gpu_csv": gpu}
                samples.write(sample)
                temp = float(gpu.split(",")[1])
                if temp >= 80 or time.monotonic() > deadline or server.poll() is not None:
                    raise RuntimeError("Runtime, temperature or wall-clock safety stop")
                time.sleep(2)
            if client.returncode:
                raise RuntimeError("Sweep failed; inspect client.log")
    finally:
        # Export partial evidence too. Cleanup errors must not skip controller restoration.
        try:
            subprocess.run(KUBE + ["-n", NS, "cp", pod + ":" + remote_dir + "/sweep", str(output / "sweep"), "-c", "api"], timeout=30, check=False)
            if server is not None:
                pid = command(prefix + ["cat", pid_path]).strip()
                if not pid.isdigit():
                    raise RuntimeError("Invalid owned process id")
                cmdline = command(prefix + ["cat", "/proc/" + pid + "/cmdline"])
                if r["binary"] not in cmdline or "18200" not in cmdline:
                    raise RuntimeError("Owned process identity changed")
                command(prefix + ["kill", "-TERM", pid])
                server.wait(timeout=20)
                log.close()
            for _ in range(20):
                after_gpu = command(prefix + ["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"])
                if not after_gpu.strip():
                    break
                time.sleep(.5)
            events.write({"event": "owned_server_stopped", "gpu_processes": after_gpu, "timestamp": time.time()})
            if after_gpu.strip():
                raise RuntimeError("GPU compute process still present")
        finally:
            if paused:
                command(KUBE + ["-n", NS, "scale", "deployment/" + CONTROLLER, "--replicas=" + str(replicas)])
                command(KUBE + ["-n", NS, "rollout", "status", "deployment/" + CONTROLLER, "--timeout=60s"], timeout=65)
                events.write({"event": "demo_replicas_restored", "replicas": replicas, "timestamp": time.time()})
            events.close()
            samples.close()
    print((output / "sweep/complete.json").read_text(), flush=True)


if __name__ == "__main__":
    main()
