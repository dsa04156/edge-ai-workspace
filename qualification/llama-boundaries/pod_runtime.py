"""Bounded direct llama-server inside the fixed borrowed RTX5080 worker Pod.

Pod/accelerator teardown remains owned by borrow_5080's persistent restoration saga.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

import bench
from borrow_5080 import kube, CONTEXT, api, APP


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--borrow-state", type=Path, required=True)
    p.add_argument("--local-sweep", action="store_true")
    args = p.parse_args()
    borrowing = json.loads((args.borrow_state / "prepared.json").read_text())
    if api(APP)["metadata"].get("annotations", {}).get("llama-demo.edge-ai.io/session") != borrowing["id"]:
        raise RuntimeError("Borrowing ownership mismatch")
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["BOUNDARY_KEY_FILE"] = str(args.key_file.resolve())
    pods = kube("-n", "llama-offload-eval", "get", "pods", "-l", "edge-ai.io/qualification-role=spark", "-o", "json")["items"]
    pods = [p for p in pods if not p["metadata"].get("deletionTimestamp") and p["status"]["phase"] == "Running"]
    if len(pods) != 1 or pods[0]["spec"]["nodeName"] != "etri-ser0002-cgnmsb":
        raise RuntimeError("Expected exactly one fixed RTX5080 worker")
    pod = pods[0]["metadata"]["name"]
    prefix = ["kubectl", f"--context={CONTEXT}", "-n", "llama-offload-eval", "exec", pod, "-c", "inference-runtime", "--"]
    def remote(command):
        return subprocess.check_output(prefix + command, text=True, stderr=subprocess.STDOUT, timeout=20)
    model = "/models/blobs/sha256-74701a8c35f6c8d9a4b91f3f3497643001d63e0c7a84e085bed452548fa88d45"
    if remote(["sha256sum", model]).split()[0] != bench.load_config(Path(__file__).with_name("common-0332.json"))["model"]["sha256"]:
        raise RuntimeError("model hash mismatch")
    with socket.socket() as s:
        s.settimeout(2)
        if s.connect_ex(("192.168.0.5", 18200)) == 0:
            raise RuntimeError("experiment port already occupied")
    subprocess.run(["kubectl", f"--context={CONTEXT}", "-n", "llama-offload-eval", "cp", "--no-preserve=true", str(args.key_file), f"{pod}:/tmp/boundary-study.key", "-c", "inference-runtime"], check=True, timeout=20)
    cfg = bench.load_config(Path(__file__).with_name("common-0332.json"))
    cfg["model"]["path"] = model
    cfg["runtime"].update(binary="/usr/lib/ollama/llama-server", host="0.0.0.0", port=18200)
    if args.local_sweep:
        cfg['runtime']['context'] = 4096
    command = ["timeout", "240", "env", "GGML_BACKEND_PATH=/usr/lib/ollama/cuda_v12/libggml-cuda.so", "LD_LIBRARY_PATH=/usr/lib/ollama:/usr/lib/ollama/cuda_v12", *bench.runtime_args(cfg), "--api-key-file", "/tmp/boundary-study.key"]
    provenance = {"pod_uid": pods[0]["metadata"]["uid"], "pod": pod, "node": "etri-ser0002-cgnmsb", "config": cfg,
                  "binary_sha256": remote(["sha256sum", "/usr/lib/ollama/llama-server"]), "gpu_inventory": remote(["nvidia-smi"]),
                  "reservation": "nvidia.com/gpu=1 on borrowed Pod; released only when that Pod is deleted"}
    (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2))
    events = bench.Journal(args.output / "events.jsonl")
    requests = bench.Journal(args.output / "requests.jsonl")
    start = time.monotonic()
    events.write({"event": "activation_requested", "timestamp": time.time(), "old_state": "CACHED", "new_state": "LOADING"})
    with open(args.output / "server.log", "x") as log:
        proc = subprocess.Popen(prefix + command, stdout=log, stderr=subprocess.STDOUT)
    base = "http://192.168.0.5:18200"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("remote runtime exited; inspect server.log")
            try:
                if bench.api(base, "/health", timeout=1).get("status") == "ok":
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.2)
        else:
            raise TimeoutError("remote activation deadline")
        logs = (args.output / "server.log").read_text()
        layers = re.search(r"offloaded (\d+)/(\d+) layers to GPU", logs)
        if not layers or layers[1] != layers[2] or int(layers[1]) == 0:
            raise RuntimeError("GPU layer verification failed")
        gpu = remote(["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"])
        if "llama-server" not in gpu:
            raise RuntimeError("GPU compute process not verified")
        events.write({"event": "health_ok", "timestamp": time.time(), "elapsed_ms": (time.monotonic()-start)*1000, "gpu_evidence": gpu})
        fixtures = bench.dataset(base, 2, cfg["workload"])
        for i, body in enumerate([{**fixtures[0], "prompt": fixtures[0]["prompt"][:32], "n_predict": 1}, fixtures[1]]):
            phase = "readiness_probe" if i == 0 else "warmup"
            row = bench.stream(base, body, run_id=args.output.name, request_id=phase, phase=phase, node="etri-ser0002-cgnmsb", planned_at=time.time(), timeout=30)
            row["concurrency"] = 1
            requests.write(row)
            if row["status"] != "ok":
                raise RuntimeError("remote probe/warmup failed")
            if i == 0:
                events.write({"event": "inference_ready", "timestamp": time.time(), "activation_ms": (time.monotonic()-start)*1000, "old_state": "LOADING", "new_state": "ACTIVE"})
        (args.output / "READY").write_text("GPU, inference probe and warmup verified\n")
        print(json.dumps({"event": "ready", "node": "RTX5080"}), flush=True)
        if args.local_sweep:
            sweep_path = '/dev/shm/' + args.output.name
            for source, dest in [(Path(__file__).with_name('bench.py'), '/dev/shm/bench.py'),
                                 (Path(__file__).with_name('sweep.py'), '/dev/shm/sweep.py'),
                                 (args.key_file, '/dev/shm/boundary-study.key')]:
                subprocess.run(['kubectl',f'--context={CONTEXT}','-n','llama-offload-eval',
                                'cp','--no-preserve=true',str(source),f'{pod}:{dest}','-c','api'],check=True,timeout=20)
            try:
                subprocess.run(['kubectl',f'--context={CONTEXT}','-n','llama-offload-eval','exec',pod,'-c','api','--',
                                'python3','/dev/shm/sweep.py','--node','etri-ser0002-cgnmsb','--output',sweep_path,
                                '--key-file','/dev/shm/boundary-study.key'],check=True,timeout=200)
            finally:
                subprocess.run(['kubectl',f'--context={CONTEXT}','-n','llama-offload-eval','cp',
                                f'{pod}:{sweep_path}',str(args.output/'sweep'),'-c','api'],check=True,timeout=30)
            return
        while proc.poll() is None and not (args.output / "STOP").exists() and time.monotonic()-start < 210:
            time.sleep(.5)
    finally:
        # The timeout kills only this process if its exec connection is lost.
        # The borrowing saga deletes the whole owned worker Pod before restoring sensor.
        events.write({"event": "teardown_delegated_to_borrowing_saga", "timestamp": time.time()})
        events.close()
        requests.close()


if __name__ == "__main__":
    main()
