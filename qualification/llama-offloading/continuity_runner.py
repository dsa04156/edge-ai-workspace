"""Operator CLI: real-Service calibration, frozen-policy round trips, durable evidence."""
from __future__ import annotations
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib import request
import uuid

from continuity_policy import CONTRACT, MODEL_DIGEST, NODES, PROMPT, Policy, freeze, p95, positive, stable, validate_policy, workload_stages

URLS = {n: f"http://llama-{n}.llama-continuity-test.svc.cluster.local:18110" for n in NODES}


def write_new(path, value):
    with Path(path).open("x") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())


class Client:
    def call(self, node, path, payload=None, timeout=5):
        body = None if payload is None else json.dumps(payload).encode()
        req = request.Request(URLS[node]+path, data=body, headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=timeout) as res:
            return json.load(res)

    def snapshot(self, node):
        try:
            m, h = self.call(node, "/metrics"), self.call(node, "/health")
            return {**m, **h, "observed_at": time.monotonic()}
        except Exception as exc:
            return {"observed_at": time.monotonic(), "error": str(exc), "inference_ready": False}

    def generate(self, node, row, emit=None):
        payload = {"request_id": row["request_id"], "prompt": PROMPT, "max_tokens": CONTRACT["max_tokens"]}
        req = request.Request(URLS[node]+"/generate/stream", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
        first, result = None, None
        try:
            with request.urlopen(req, timeout=120) as res:
                for line in res:
                    event = json.loads(line)
                    if event.get("type") == "error":
                        raise RuntimeError(event["error"])
                    if event.get("type") == "token" and event.get("text") and first is None:
                        first = time.monotonic()
                        row["first_token_at"] = first
                        if emit:
                            emit()
                    if event.get("type") == "result":
                        if result is not None:
                            raise RuntimeError("duplicate final result")
                        result = event
            if first is None or not result or result.get("request_id") != row["request_id"] or result.get("node_id") != NODES[node] or result.get("model_digest") != MODEL_DIGEST:
                raise RuntimeError("missing token/result or request/node/model identity mismatch")
            row.update(status="ok", identity_verified=True, actual_node=result["node_id"],
                       model_digest=result["model_digest"], response=result["response"],
                       ttft_ms=(first-row["arrival_at"])*1000)
        except Exception as exc:
            row.update(status="unknown", identity_verified=False, error=str(exc))
        row.update(completed_at=time.monotonic())
        row["latency_ms"] = (row["completed_at"]-row["arrival_at"])*1000
        return row

    def probe(self, node):
        row = {"request_id": "probe-"+uuid.uuid4().hex, "arrival_at": time.monotonic()}
        self.generate(node, row)
        if row["status"] != "ok":
            raise RuntimeError(f"{node} inference probe failed: {row.get('error')}")
        return row

    def prepare(self):
        # Neither worker may have requests owned by another operator.
        for node in NODES:
            s = self.snapshot(node)
            if s.get("node_id") != NODES[node] or not s.get("management_runtime_running") or s.get("active_requests") != 0 or s.get("queue_length") != 0:
                raise RuntimeError(f"{node}: Service identity/runtime/idle preflight failed: {s}")
        self.call("nano", "/activate", {"target_state": "ACTIVE", "reason": "continuity_setup"}, 180)
        self.call("agx", "/activate", {"target_state": "CACHED", "reason": "continuity_cache_prime"}, 1200)
        for node in NODES:
            if self.snapshot(node).get("model_digest") != MODEL_DIGEST:
                raise RuntimeError(f"{node}: model digest mismatch")

    def activate(self):
        before = self.snapshot("agx")
        if before.get("model_loaded") is not False or before.get("model_cached") is not True:
            raise RuntimeError("activation baseline must start with actual CACHED model")
        start = time.monotonic()
        result = self.call("agx", "/activate", {"target_state": "ACTIVE", "reason": "continuity_pressure"}, 180)
        probe = self.probe("agx")
        return {"elapsed_ms": (time.monotonic()-start)*1000, "verified": True,
                "download_ms": result.get("model_remote_download_ms"), "probe": probe}

    def release(self):
        s = self.snapshot("agx")
        if s.get("active_requests") != 0 or s.get("queue_length") != 0:
            raise RuntimeError("AGX busy or unobserved; model release blocked")
        self.call("agx", "/deactivate", {"target_state": "CACHED", "reason": "continuity_idle"}, 90)
        s = self.snapshot("agx")
        if not (s.get("node_id") == NODES["agx"] and s.get("model_digest") == MODEL_DIGEST
                and s.get("node_state") == "CACHED" and s.get("model_loaded") is False
                and s.get("model_vram_mib") == 0):
            raise RuntimeError("AGX cache/model residency release not verified")
        return s


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / "continuity.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS entries (run_id TEXT NOT NULL, category TEXT NOT NULL, entry_key TEXT NOT NULL, sequence INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(run_id,category,entry_key))")
        self.db.commit()

    def save(self, record):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO records VALUES (?, ?)",
                            (record["id"], json.dumps(record, allow_nan=False)))
            if record.get("status") != "running":
                # Final full snapshot and delta retirement are one durable transaction.
                self.db.execute("DELETE FROM entries WHERE run_id=?", (record["id"],))
            self.db.commit()

    def put_entries(self, run_id, entries):
        """Small FULL-sync transaction; dispatch row and event commit together."""
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?)",
                [(run_id, category, str(key), sequence, json.dumps(body, allow_nan=False))
                 for category, key, sequence, body in entries])
            self.db.commit()

    def hydrate(self, record):
        with self.lock:
            for category in ("request", "event", "sample"):
                values = [json.loads(body) for (body,) in self.db.execute(
                    "SELECT body FROM entries WHERE run_id=? AND category=? ORDER BY sequence",
                    (record["id"], category))]
                if values:
                    record[category+"s"] = values
        return record

    def latest(self):
        with self.lock:
            row = self.db.execute("SELECT body FROM records ORDER BY rowid DESC LIMIT 1").fetchone()
            return self.hydrate(json.loads(row[0])) if row else None

    def unfinished(self):
        with self.lock:
            rows = [json.loads(b) for (b,) in self.db.execute("SELECT body FROM records")]
            return [self.hydrate(r) for r in rows if r.get("status") in {"running", "interrupted"}]

    def close(self):
        self.db.close()


def baseline_batch(client, node, phase, repeat, rps, duration=30):
    """Open-loop, bounded calibration. A rejected scheduled arrival remains a failure."""
    if phase == "low":
        rps = CONTRACT["calibration_low_rps"]
        duration = 30/rps
    result = {"node": node, "phase": phase, "repeat": repeat, "rps": rps,
              "duration_seconds": duration, "requests": [], "outstanding": [],
              "started_at": time.time(), "before": client.snapshot(node)}
    start = time.monotonic()
    planned = 30 if phase == "low" else max(1, math.floor(duration*rps))
    result["planned"] = planned
    futures = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        for i in range(planned):
            due = start+(i+1 if phase == "low" else i)/rps
            while time.monotonic() < due:
                result["outstanding"].append(sum(not f.done() for f in futures))
                time.sleep(min(.25, max(0, due-time.monotonic())))
            row = {"request_id": uuid.uuid4().hex, "arrival_at": due, "selected_node": node}
            result["requests"].append(row)
            if sum(not f.done() for f in futures) >= 32:
                row.update(status="rejected", error="calibration_capacity_limit")
            else:
                row["dispatch_at"] = time.monotonic()
                future = pool.submit(client.generate, node, row)
                futures.append(future)
                if phase == "low":
                    future.result()
        while phase != "low" and time.monotonic() < start+duration:
            result["outstanding"].append(sum(not f.done() for f in futures))
            time.sleep(.25)
        result["completed_during_arrivals"] = sum(r.get("status") == "ok" and r.get("completed_at", math.inf) <= start+duration for r in result["requests"])
    result.update(finished_at=time.time(), after=client.snapshot(node))
    return result


def busy_batch(client, node, repeat):
    """Separate saturated single-request service cost from idle-arrival SLO."""
    client.probe(node)
    result = {"node": node, "phase": "busy", "repeat": repeat, "planned": 30,
              "method": CONTRACT["calibration_busy_strategy"], "started_at": time.time(),
              "before": client.snapshot(node), "requests": []}
    for _ in range(30):
        row = {"request_id": uuid.uuid4().hex, "arrival_at": time.monotonic(), "selected_node": node}
        row["dispatch_at"] = time.monotonic()
        client.generate(node, row)
        result["requests"].append(row)
        if row.get("status") != "ok":
            raise RuntimeError(f"{node}: busy service measurement failed")
    result.update(finished_at=time.time(), after=client.snapshot(node))
    return result


def measure_agx_admission(client, record, journal):
    """Measure the actual 120% condition when it lies inside the coarse load bracket."""
    slo = 2*max(p95([q["ttft_ms"] for q in b["requests"]]) for b in record["batches"] if b["phase"] == "low")
    capacity = {}
    for node in NODES:
        runs = [b for b in record["batches"] if b["node"] == node and b["phase"] == "load"]
        passed = [rate for rate in {b["rps"] for b in runs}
                  if len(group := [b for b in runs if b["rps"] == rate]) == 3
                  and all(stable(b, slo) for b in group)]
        capacity[node] = max(passed, default=0)
    if capacity["nano"] and capacity["agx"] < 1.2*capacity["nano"]:
        if record.get("agx_admission"):
            raise ValueError("admission evidence already exists")
        record["agx_admission"] = []
        for repeat in range(3):
            record["agx_admission"].append(baseline_batch(client, "agx", "admission", repeat, 1.2*capacity["nano"]))
            journal.save(record)


def calibrate(client, journal, output):
    if Path(output).exists():
        raise FileExistsError("baseline already exists; use a new evidence directory")
    record = {"id": uuid.uuid4().hex, "kind": "live-calibration/v2", "contract": CONTRACT,
              "started_at": time.time(), "status": "running", "batches": [], "activations": [], "gpu_evidence": {}}
    journal.save(record)
    try:
        client.prepare()
        client.activate()
        for node in NODES:
            client.probe(node)
            record["gpu_evidence"][node] = client.snapshot(node)
            evidence = record["gpu_evidence"][node]
            if evidence.get("node_id") != NODES[node] or evidence.get("model_digest") != MODEL_DIGEST or not positive(evidence.get("model_vram_mib")):
                raise RuntimeError(f"{node}: real GPU/model evidence missing; load sweep blocked")
        for repeat in range(3):
            for node in (list(NODES) if repeat % 2 == 0 else list(reversed(NODES))):
                record["batches"].append(baseline_batch(client, node, "low", repeat, CONTRACT["calibration_low_rps"]))
                journal.save(record)
        slo = 2*max(p95([q["ttft_ms"] for q in b["requests"]]) for b in record["batches"])
        bracketed = set()
        for rate in (.25, .5, 1., 2., 4., 8., 12., 16.):
            for repeat in range(3):
                for node in (list(NODES) if repeat % 2 == 0 else list(reversed(NODES))):
                    if node in bracketed:
                        continue
                    record["batches"].append(baseline_batch(client, node, "load", repeat, rate))
                    journal.save(record)
            for node in NODES:
                group = [b for b in record["batches"] if b["phase"] == "load" and b["node"] == node and b["rps"] == rate]
                if len(group) == 3 and not all(stable(b, slo) for b in group):
                    bracketed.add(node)
            if bracketed == set(NODES):
                break
        measure_agx_admission(client, record, journal)
        for repeat in range(3):
            for node in (list(NODES) if repeat % 2 == 0 else list(reversed(NODES))):
                record["batches"].append(busy_batch(client, node, repeat))
                journal.save(record)
        for _ in range(10):
            client.release()
            record["activations"].append(client.activate())
            journal.save(record)
        client.release()
        record["status"] = "completed"
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        # An uncertain request may still be executing: release() checks actual worker idle.
        try:
            record["cleanup"] = client.release()
        except Exception as cleanup:
            record["cleanup_error"] = str(cleanup)
    finally:
        journal.save(record)
        write_new(output, record)
    return record


def round_trip(client, journal, policy, control=False):
    validate_policy(policy)
    stages = workload_stages(policy)
    arrivals, offset = [], 0.
    for phase, seconds, rate in stages:
        arrivals.extend((offset+i/rate, phase) for i in range(math.floor(seconds*rate)))
        offset += seconds
    run = {"id": uuid.uuid4().hex, "kind": "nano-agx-roundtrip/v1", "policy_id": policy["policy_id"],
           "contract": CONTRACT, "control": control, "status": "running", "started_at": time.time(),
           "stages": stages, "planned": len(arrivals), "requests": [], "events": [], "samples": []}
    lock = journal.lock
    def request_entry(row):
        return ("request", row["request_id"], row["sequence"], row)
    def event(name, _request=None, **fields):
        with lock:
            run["events"].append({"event": name, "at": time.monotonic(), **fields})
            sequence = len(run["events"])-1
            entries = [("event", sequence, sequence, run["events"][-1])]
            if _request is not None:
                entries.append(request_entry(_request))
            journal.put_entries(run["id"], entries)
    journal.save(run)
    pending, recent = deque(), deque()
    state = Policy(policy)
    snapshots, inflight = {}, {"nano": 0, "agx": 0}
    stop_poll = threading.Event()
    wake = threading.Event()
    def poll(node):
        while not stop_poll.is_set():
            snapshot = client.snapshot(node)
            with lock:
                snapshots[node] = snapshot
            wake.set()
            stop_poll.wait(.5)
    pollers = []
    last_remote = time.monotonic()
    remote_error = False
    action_future, action_name = None, None
    pool = ThreadPoolExecutor(max_workers=3)
    actions = ThreadPoolExecutor(max_workers=1)
    try:
        client.prepare()
        for node in NODES:
            snapshots[node] = client.snapshot(node)
            t = threading.Thread(target=poll, args=(node,), daemon=True)
            t.start()
            pollers.append(t)
        base, index, next_sample = time.monotonic(), 0, 0.
        run["workload_started"] = base
        event("workload_started")
        def send(row, node):
            nonlocal last_remote, remote_error
            client.generate(node, row, lambda: journal.put_entries(run["id"], [request_entry(row)]))
            with lock:
                inflight[node] -= 1
                if node == "agx":
                    last_remote = time.monotonic()
                    remote_error = remote_error or row["status"] != "ok"
                event("response", _request=row, request_id=row["request_id"], node=node, status=row["status"])
            wake.set()
        while True:
            wake.clear()
            now = time.monotonic()
            with lock:
                while index < len(arrivals) and now >= base+arrivals[index][0]:
                    due, phase = arrivals[index]
                    recent.append(base+due)
                    row = {"request_id": f"{run['id']}-{index}", "sequence": index, "arrival_at": base+due,
                           "received_at": now, "phase": phase, "status": "queued", "accepted": True,
                           "admitted_node": state.target, "selected_node": state.target}
                    if len(pending) >= policy["queue_limit"]:
                        row.update(status="rejected", accepted=False, error="admission_queue_full", completed_at=now)
                    else:
                        pending.append(row)
                    run["requests"].append(row)
                    journal.put_entries(run["id"], [request_entry(row)])
                    index += 1
                while recent and recent[0] < now-policy["settings"]["rate_window_seconds"]:
                    recent.popleft()
                rate = len(recent)/policy["settings"]["rate_window_seconds"]
                probe = None
                if action_future and action_future.done():
                    try:
                        outcome = action_future.result()
                        probe = True
                        event(action_name+"_verified", evidence=outcome)
                        if action_name == "release":
                            state.state = "RELEASED"
                    except Exception as exc:
                        probe = False
                        event(action_name+"_failed", error=str(exc))
                        if action_name == "release":
                            state.state = "RELEASE_BLOCKED"
                    action_future = None
                if not control:
                    queued_by_node = {n: sum(r["selected_node"] == n for r in pending) for n in NODES}
                    commands = state.step(now, rate, len(pending), inflight, snapshots, last_remote, probe, remote_error, queued_by_node=queued_by_node)
                    for command in commands:
                        if command == "fallback":
                            # Only unsent requests can change their admission route.
                            moved = []
                            for row in pending:
                                if row["selected_node"] == "agx":
                                    row.update(selected_node="nano", rerouted_from="agx")
                                    moved.append(row["request_id"])
                            event("reroute_unsent", request_ids=moved, target="nano")
                        event(command, rate=rate, queue=len(pending), target=state.target,
                              prediction=state.last_prediction if command == "activate" else None)
                        if command in {"activate", "probe_nano", "release"}:
                            action_name = command
                            fn = {"activate": client.activate, "probe_nano": lambda: client.probe("nano"), "release": client.release}[command]
                            action_future = actions.submit(fn)
                            action_future.add_done_callback(lambda _: wake.set())
                # Drain already accepted work on its node while new arrivals use
                # the current route. Switching must not move an existing queue.
                for node in NODES:
                    row = next((r for r in pending if r["selected_node"] == node), None)
                    if row is not None and inflight[node] == 0 and state.fresh(node, snapshots, now):
                        pending.remove(row)
                        row.update(dispatch_at=now, activation_window=state.state == "PREPARING")
                        inflight[node] += 1
                        # Durable intent precedes network send. Unknown outcomes are never replayed.
                        event("dispatch", _request=row, request_id=row["request_id"], node=node,
                              ready_observed_at=snapshots[node]["observed_at"])
                        pool.submit(send, row, node)
                if now >= next_sample:
                    run["samples"].append({"at": now, "rate": rate, "queue": len(pending),
                                           "state": state.state, "target": state.target,
                                           "inflight": inflight.copy(), "nodes": dict(snapshots)})
                    sequence = len(run["samples"])-1
                    journal.put_entries(run["id"], [("sample", sequence, sequence, run["samples"][-1])])
                    next_sample = now+1
                finished = index == len(arrivals) and not pending and not any(inflight.values())
                if finished and not action_future and (control or state.state in {"RELEASED", "RELEASE_BLOCKED", "FAULT_LOCAL", "LOCAL"}):
                    break
                if now > base+offset+300:
                    raise TimeoutError("round-trip deadline; incomplete work is not success")
            arrival_wait = base+arrivals[index][0]-time.monotonic() if index < len(arrivals) else .05
            wake.wait(max(0., min(.05, arrival_wait)))
        run["status"] = "completed"
    except Exception as exc:
        run.update(status="failed", error=str(exc))
    finally:
        pool.shutdown(wait=True)
        actions.shutdown(wait=True)
        stop_poll.set()
        for t in pollers:
            t.join(timeout=12)
        # Cleanup is distinct from successful policy return. Never silently infer it.
        if not control and state.state != "RELEASED":
            try:
                client.probe("nano")
                event("cleanup", evidence=client.release())
            except Exception as exc:
                event("cleanup_blocked", error=str(exc))
        for row in pending:
            row.update(status="uncompleted", error="run_ended_before_dispatch")
        run["finished_at"] = time.time()
        run["final_state"] = state.state
        journal.save(run)
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["idle", "preflight", "calibrate", "freeze", "run", "verify", "recover"])
    parser.add_argument("--data", default="/data")
    parser.add_argument("--baseline", default="/data/baseline.json")
    parser.add_argument("--policy", default="/data/policy.json")
    args = parser.parse_args()
    if args.mode == "idle":
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/health" else 404)
                self.end_headers()
                self.wfile.write(b"operator qualification controller; execute CLI explicitly")
        ThreadingHTTPServer(("0.0.0.0", 18112), Handler).serve_forever()
        return
    client = Client()
    Path(args.data).mkdir(parents=True, exist_ok=True)
    # A new evidence directory must not create a second independent operator lock.
    with Path(os.getenv("CONTINUITY_LOCK_FILE", "/data/operator.lock")).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = Journal(args.data)
        try:
            unfinished = journal.unfinished()
            if unfinished and args.mode not in {"recover", "verify", "preflight"}:
                for record in unfinished:
                    record["status"] = "interrupted"
                    journal.save(record)
                raise RuntimeError("interrupted evidence exists; recover explicitly without replay")
            if args.mode == "preflight":
                print(json.dumps({n: client.snapshot(n) for n in NODES}, indent=2))
            elif args.mode == "calibrate":
                record = calibrate(client, journal, args.baseline)
                if record["status"] != "completed":
                    raise RuntimeError(record.get("error"))
            elif args.mode == "freeze":
                baseline = json.loads(Path(args.baseline).read_text())
                write_new(args.policy, freeze(baseline))
            elif args.mode == "run":
                policy = validate_policy(json.loads(Path(args.policy).read_text()))
                if freeze(json.loads(Path(args.baseline).read_text())) != policy:
                    raise ValueError("frozen baseline mismatch")
                for repeat in range(10):
                    # Alternate paired order to reduce time/thermal confounding.
                    for control in ([True, False] if repeat % 2 == 0 else [False, True]):
                        run = round_trip(client, journal, policy, control)
                        run["repeat"] = repeat
                        journal.save(run)
                        write_new(Path(args.data)/(run["id"]+".json"), run)
                        if run["status"] != "completed" or run.get("final_state") in {"FAULT_LOCAL", "RELEASE_BLOCKED"}:
                            raise RuntimeError("run failed; evidence retained, no automatic retry")
                        from continuity_report import evaluate
                        verdict = evaluate(policy, run)
                        write_new(Path(args.data)/(run["id"]+"-verdict.json"), verdict)
                        if not verdict["passed"]:
                            raise RuntimeError("qualification failed; frozen thresholds retained; inspect verdict before another attempt")
            elif args.mode == "verify":
                from continuity_report import report
                policy = validate_policy(json.loads(Path(args.policy).read_text()))
                runs = [json.loads(p.read_text()) for p in Path(args.data).glob("*.json")]
                result = report(policy, [r for r in runs if r.get("kind") == "nano-agx-roundtrip/v1"])
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if not result["passed"]:
                    raise SystemExit(1)
            elif args.mode == "recover":
                client.probe("nano")
                evidence = client.release()
                for record in unfinished:
                    record.update(status="interrupted_recovered", recovery=evidence)
                    journal.save(record)
                print("Recovery verified; interrupted requests were not replayed")
        finally:
            journal.close()


if __name__ == "__main__":
    main()
