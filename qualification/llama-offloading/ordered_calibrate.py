"""Bounded actual Spark profile for the ordered demo (not the prior v2 suite)."""
import concurrent.futures
import json
import math
from pathlib import Path
import time
import urllib.request
import uuid

URL = "http://llama-spark.llama-continuity-test.svc.cluster.local:18110"
NODE = "etri-ser0003-cg0ms0"
DIGEST = "baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878"
PROMPT = "In one short sentence, explain why edge computing reduces latency."


def call(path, payload=None):
    request = urllib.request.Request(URL + path, data=json.dumps(payload).encode() if payload else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def generate(request_id, scheduled=None):
    start = scheduled if scheduled is not None else time.monotonic()
    request = urllib.request.Request(URL + "/generate/stream", data=json.dumps({
        "request_id": request_id, "prompt": PROMPT, "max_tokens": 8}).encode(),
        headers={"Content-Type": "application/json"})
    first = None
    result = None
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            event = json.loads(line)
            if event.get("type") == "token" and event.get("text") and first is None:
                first = time.monotonic()
            if event.get("type") == "result":
                result = event
            if event.get("type") == "error":
                raise RuntimeError("worker_stream_error")
    assert result and first and result["node_id"] == NODE and result["model_digest"] == DIGEST
    assert result["request_id"] == request_id
    return {"request_id": request_id, "node": NODE, "ttft_ms": 1000 * (first - start),
            "latency_ms": 1000 * (time.monotonic() - start), "status": "ok"}


def p95(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1]


def run(output):
    record = {"kind": "ordered-demo-spark-profile/v1", "started_at": time.time(),
              "node": NODE, "model_digest": DIGEST, "busy_batches": [], "activations": [], "load_batches": []}
    def save():
        Path(output).write_text(json.dumps(record, indent=2) + "\n")
    try:
        if call("/health").get("inference_ready") is not True:
            call("/activate", {"target_state": "ACTIVE", "reason": "ordered_profile_prepare"})
        record["before"] = {**call("/metrics"), **call("/health")}
        assert record["before"]["model_vram_mib"] > 0
        for repeat in range(3):
            rows = [generate(f"busy-{repeat}-{i}-{uuid.uuid4().hex}") for i in range(30)]
            record["busy_batches"].append(rows)
            print("busy", repeat, "p95_ms", p95([r["latency_ms"] for r in rows]), flush=True)
            save()
        for repeat in range(10):
            call("/deactivate", {"target_state": "CACHED", "reason": "ordered_profile"})
            before = call("/health")
            assert before["model_loaded"] is False and before["model_cached"] is True
            start = time.monotonic()
            activation = call("/activate", {"target_state": "ACTIVE", "reason": "ordered_profile"})
            probe = generate("activation-" + uuid.uuid4().hex)
            elapsed = 1000 * (time.monotonic() - start)
            assert activation["model_remote_download_ms"] == 0
            record["activations"].append({"elapsed_ms": elapsed, "activation": activation, "probe": probe})
            print("activation", repeat, "elapsed_ms", elapsed, flush=True)
            save()
        for repeat in range(3):
            start = time.monotonic() + .2
            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                futures = []
                for index in range(180):
                    due = start + index / 6
                    time.sleep(max(0, due - time.monotonic()))
                    futures.append(pool.submit(generate, f"load-{repeat}-{index}-{uuid.uuid4().hex}", due))
                rows = [f.result() for f in futures]
            elapsed = time.monotonic() - start
            batch = {"rps": 6, "duration_seconds": 30, "completion_seconds": elapsed, "requests": rows,
                     "p95_ttft_ms": p95([r["ttft_ms"] for r in rows])}
            record["load_batches"].append(batch)
            print("load", repeat, "p95_ttft_ms", batch["p95_ttft_ms"], "completion_seconds", elapsed, flush=True)
            save()
        record["qualified"] = all(b["p95_ttft_ms"] <= 548.4096340078395 and b["completion_seconds"] <= 31
                                   for b in record["load_batches"])
        record["profile"] = {"capacity_rps": 6, "service_ms": max(p95([r["latency_ms"] for r in rows])
                             for rows in record["busy_batches"]),
                             "low_ttft_ms": max(p95([r["ttft_ms"] for r in rows]) for rows in record["busy_batches"]),
                             "activation_ms": max(a["elapsed_ms"] for a in record["activations"])}
    finally:
        call("/deactivate", {"target_state": "CACHED", "reason": "ordered_profile_complete"})
        record["after"] = {**call("/metrics"), **call("/health")}
        record["finished_at"] = time.time()
        save()
    print(json.dumps({"qualified": record["qualified"], "profile": record["profile"]}), flush=True)


if __name__ == "__main__":
    import sys
    run(sys.argv[1])
