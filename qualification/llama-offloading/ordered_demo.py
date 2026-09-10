"""Drive a real, automatically decided Nano -> Orin -> Spark -> Orin -> Nano demo.

Runs inside the isolated controller Pod; never forces a cutover or modifies a
threshold. Final JSON and JSONL requests remain in its persistent data directory.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:18113/api/runtime-model-offloading"
PROMPT = "In one short sentence, explain why edge computing reduces latency."
PHASES = [("nano", 2, 30), ("orin", 3.8, 140), ("spark", 5.6, 100),
          ("return_orin", 2.7, 100), ("return_nano", 2, 100)]


def call(path="", payload=None):
    headers = {"Content-Type": "application/json"}
    if payload:
        headers["X-Execution-Token"] = os.environ["EXECUTION_MANAGEMENT_TOKEN"]
    request = urllib.request.Request(BASE + path, data=json.dumps(payload).encode() if payload else None,
                                     headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def run(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    prefix = uuid.uuid4().hex[:12]
    states = []
    results = []
    stopped = threading.Event()
    lock = threading.Lock()
    before = call()
    baseline_cycles = before["cycles_completed"]
    order = before["execution_order"]
    def observe():
        while not stopped.is_set():
            try:
                state = call()
                row = {"at": time.time(), **state}
                states.append(row)
                with (directory / "states.jsonl").open("a") as file:
                    file.write(json.dumps(row) + "\n")
            except Exception as exc:
                states.append({"at": time.time(), "observation_error": type(exc).__name__})
            stopped.wait(.5)
    def generate(request_id, due, phase):
        try:
            response = call("/generate", {"request_id": request_id, "prompt": PROMPT, "max_tokens": 8})
            row = {"phase": phase, "scheduled_at": due, "finished_at": time.monotonic(), **response}
        except Exception as exc:
            row = {"request_id": request_id, "phase": phase, "status": "client_error", "error": type(exc).__name__}
        with lock:
            results.append(row)
            with (directory / "requests.jsonl").open("a") as file:
                file.write(json.dumps(row) + "\n")
    watcher = threading.Thread(target=observe)
    watcher.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            for phase, rate, duration in PHASES:
                print("phase", phase, "rps", rate, "seconds", duration, flush=True)
                start = time.monotonic() + .1
                for index in range(round(rate * duration)):
                    due = start + index / rate
                    time.sleep(max(0, due - time.monotonic()))
                    pool.submit(generate, f"{prefix}-{phase}-{index}", due, phase)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            after = call()
            if after["cycles_completed"] > baseline_cycles and not after["retained_models"]:
                break
            time.sleep(1)
    finally:
        stopped.set()
        watcher.join()
    after = call()
    visited = []
    for state in states:
        node = state.get("target_node")
        if node and (not visited or visited[-1] != node):
            visited.append(node)
    expected = order + order[-2::-1]
    planned = sum(round(rate * duration) for _, rate, duration in PHASES)
    ok = sum(r["status"] == "ok" for r in results)
    record = {"kind": "actual-ordered-demo/v1", "before": before, "after": after,
              "planned": planned, "completed": len(results), "ok": ok,
              "unique_ids": len({r["request_id"] for r in results}),
              "visited": visited, "expected": expected,
              "passed": visited == expected and ok == planned and len(results) == planned
                        and len({r["request_id"] for r in results}) == planned
                        and after["cycles_completed"] > baseline_cycles and not after["retained_models"],
              "history": call("/history?limit=100")}
    (directory / "summary.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("planned", "completed", "ok", "visited", "passed")}), flush=True)
    if not record["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    import sys
    run(sys.argv[1])
