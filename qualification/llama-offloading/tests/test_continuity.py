import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import continuity_policy as cp
import continuity_runner as cr
import continuity_report as report
import worker
import continuity_preflight


def fixture_baseline():
    b = {"kind": "live-calibration/v2", "status": "completed", "contract": copy.deepcopy(cp.CONTRACT), "batches": [],
         "activations": [{"elapsed_ms": 1000., "verified": True, "download_ms": 0} for _ in range(10)],
         "gpu_evidence": {n: {"node_id": p, "model_digest": cp.MODEL_DIGEST, "model_vram_mib": 1024} for n,p in cp.NODES.items()}}
    for n in cp.NODES:
        for repeat in range(3):
            for phase, rate in [("low", .25), ("load", 1), ("load", 2), ("load", 4), ("busy", 0)]:
                ms = 100 if n == "nano" else 50
                overloaded = phase == "load" and rate >= (2 if n == "nano" else 4)
                rows = [{"request_id": str(i), "status": "ok", "identity_verified": True,
                         "arrival_at": 1+i*ms/1000 if phase == "busy" else 4*(i+1),
                         "completed_at": 1+(i+1)*ms/1000 if phase == "busy" else 4*(i+1)+ms/1000,
                         "ttft_ms": ms if not overloaded else 10000, "latency_ms": ms} for i in range(30)]
                b["batches"].append({"node": n, "phase": phase, "repeat": repeat, "rps": rate,
                                     "requests": rows, "planned": 30, "method": cp.CONTRACT["calibration_busy_strategy"] if phase == "busy" else None,
                                     "duration_seconds": 120 if phase == "low" else 30,
                                     "completed_during_arrivals": 30, "outstanding": [0]*30})
    return b


def snapshots(now):
    return {n: {"node_id": p, "model_digest": cp.MODEL_DIGEST, "observed_at": now,
                "management_runtime_running": True, "inference_ready": True,
                "active_requests": 0, "queue_length": 0} for n,p in cp.NODES.items()}


class CalibrationTests(unittest.TestCase):
    def test_freeze_uses_real_node_contract_and_measured_capacity(self):
        p = cp.freeze(fixture_baseline())
        self.assertEqual(p["slo_ms"], 200)
        self.assertEqual(p["capacity_rps"], {"nano": 1, "agx": 2})
        self.assertEqual(p["activation_slo_ms"], 1200)
        self.assertEqual(cp.validate_policy(p), p)

    def test_idle_latency_does_not_replace_separately_measured_busy_service(self):
        b = fixture_baseline()
        for batch in b["batches"]:
            if batch["node"] == "agx" and batch["phase"] == "low":
                for row in batch["requests"]: row["latency_ms"] = 500
        p = cp.freeze(b)
        self.assertEqual(p["service_ms"], {"nano": 100, "agx": 50})
        self.assertGreaterEqual(p["qualification_forecast"]["gain"], .15)
        busy = next(x for x in b["batches"] if x["phase"] == "busy")
        busy["requests"][1]["arrival_at"] += 1
        with self.assertRaisesRegex(ValueError, "busy-service"):
            cp.freeze(b)

    def test_overlap_forecast_serves_source_during_activation_and_charges_delay(self):
        p = cp.freeze(fixture_baseline())
        short = cp.predict_overlap(p, 1.2)
        long = cp.predict_overlap({**p, "activation_max_ms": 60_000}, 1.2)
        self.assertGreater(short["local_during_activation"], 0)
        self.assertGreater(short["remote_after_ready"], 0)
        self.assertLess(long["gain"], short["gain"])
        slower = cp.predict_overlap({**p, "service_ms": {"nano": 100, "agx": 200}}, 1.2)
        self.assertLess(slower["gain"], 0)
        backlog = cp.predict_overlap(p, 1.2, pending=30, inflight={"nano": 1})
        self.assertGreater(backlog["local_mean_response_ms"], short["local_mean_response_ms"])
        self.assertEqual(backlog["requests"]-short["requests"], 30)

    def test_reject_substitute_cpu_missing_repeats_downloads_and_unbracketed_load(self):
        for mutate in [lambda b: b.update(status="failed"),
                       lambda b: b["contract"]["nodes"].update(agx="rtx"),
                       lambda b: b["gpu_evidence"]["agx"].update(model_vram_mib=0),
                       lambda b: b["batches"].pop(0),
                       lambda b: b["activations"].pop(),
                       lambda b: b["activations"][0].update(download_ms=100),
                       lambda b: b.update(batches=[x for x in b["batches"] if x["rps"] < 4])]:
            b = fixture_baseline()
            mutate(b)
            with self.assertRaises(ValueError):
                cp.freeze(b)

    def test_editing_frozen_policy_does_not_silently_change_run(self):
        p = cp.freeze(fixture_baseline())
        p["slo_ms"] = 999
        with self.assertRaises(ValueError):
            cp.Policy(p)

    def test_exact_admission_requires_all_three_successes_not_interpolation(self):
        b = fixture_baseline()
        # Both coarse sweeps only certify 1 rps, although AGX is faster per request.
        for batch in b["batches"]:
            if batch["node"] == "agx" and batch["phase"] == "load" and batch["rps"] == 2:
                for row in batch["requests"]: row["ttft_ms"] = 10000
        with self.assertRaisesRegex(ValueError, "120%"):
            cp.freeze(b)
        b["agx_admission"] = []
        for repeat in range(3):
            batch = copy.deepcopy(next(x for x in b["batches"] if x["node"] == "agx" and x["phase"] == "load" and x["rps"] == 1))
            batch.update(phase="admission", rps=1.2, repeat=repeat,
                         before={"node_id": cp.NODES["agx"], "model_vram_mib": 1024})
            b["agx_admission"].append(batch)
        self.assertEqual(cp.freeze(b)["capacity_rps"]["agx"], 1.2)
        b["agx_admission"][1]["requests"][0]["status"] = "unknown"
        with self.assertRaisesRegex(ValueError, "120%"):
            cp.freeze(b)

    def test_continuous_warm_calls_cannot_be_labeled_low_arrival_baseline(self):
        b = fixture_baseline()
        for i, row in enumerate(b["batches"][0]["requests"]):
            row["arrival_at"] = i*.1
        with self.assertRaisesRegex(ValueError, "low-load"):
            cp.freeze(b)

    def test_low_sampler_includes_idle_gaps_even_when_service_is_fast(self):
        class Clock:
            now = 0.
            def monotonic(self): return self.now
            def time(self): return self.now
            def sleep(self, seconds): self.now += seconds
        clock = Clock()
        class Future:
            def __init__(self, value): self.value = value
            def done(self): return True
            def result(self): return self.value
        class Pool:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def submit(self, fn, *args): return Future(fn(*args))
        class Client:
            def snapshot(self, node): return {}
            def generate(self, node, row):
                clock.sleep(.1)
                row.update(status="ok", identity_verified=True, completed_at=clock.now,
                           ttft_ms=100., latency_ms=100.)
                return row
        with patch.object(cr, "time", clock), patch.object(cr, "ThreadPoolExecutor", Pool):
            batch = cr.baseline_batch(Client(), "nano", "low", 0, .25)
        self.assertTrue(cp.valid_low_batch(batch))
        self.assertGreaterEqual(batch["finished_at"]-batch["started_at"], 120)
        self.assertEqual(batch["requests"][0]["arrival_at"], 4)

    def test_duplicate_missing_nan_and_growing_backlog_fail_qualification(self):
        b = fixture_baseline()["batches"][1]
        self.assertTrue(cp.stable(b, 200))
        b["requests"][0]["request_id"] = b["requests"][1]["request_id"]
        self.assertFalse(cp.stable(b, 200))
        b["requests"][0]["request_id"] = "unique"
        b["requests"][0]["ttft_ms"] = float("nan")
        self.assertFalse(cp.stable(b, 200))
        b["requests"][0]["ttft_ms"] = 100
        b["outstanding"] = list(range(30))
        self.assertFalse(cp.stable(b, 200))


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = cp.Policy(cp.freeze(fixture_baseline()))

    def step(self, now, rate=1.2, pending=0, **kwargs):
        return self.p.step(now, rate, pending, {"nano": 0, "agx": 0}, snapshots(now), 70, **kwargs)

    def activate(self):
        self.assertEqual(self.step(0), [])
        self.assertEqual(self.step(5), ["activate"])
        self.assertEqual(self.step(6), [])
        self.assertEqual(self.step(7, probe_result=True), ["switch_remote"])

    def test_round_trip_requires_probe_dwell_cooldown_and_drain(self):
        self.activate()
        self.assertEqual(self.p.target, "agx")
        self.assertEqual(self.step(10, .5), [])
        self.assertEqual(self.step(40, .5), [])
        self.assertEqual(self.step(67, .5), ["probe_nano"])
        self.assertEqual(self.step(68, .5, probe_result=True), ["switch_local"])
        self.assertEqual(self.p.target, "nano")
        self.assertEqual(self.step(99, .5), [])
        self.assertEqual(self.step(100, .5), ["release"])

    def test_short_burst_and_oscillation_reset_dwell(self):
        self.step(0)
        self.step(4, .1, 0)
        self.assertEqual(self.step(5), [])
        self.assertEqual(self.step(9), [])
        self.assertEqual(self.step(10), ["activate"])

    def test_activation_failure_keeps_local_and_no_retry_storm(self):
        self.step(0); self.step(5)
        self.assertEqual(self.step(6, probe_result=False), ["activation_failed"])
        self.assertEqual(self.p.target, "nano")
        self.assertEqual(self.step(500), [])

    def test_remote_error_bypasses_cooldown_but_not_replay(self):
        self.activate()
        self.assertEqual(self.step(8, remote_error=True), ["fallback"])
        self.assertEqual(self.p.target, "nano")
        self.assertTrue(self.p.faulted)

    def test_low_nano_usage_is_not_return_criterion(self):
        self.activate()
        self.assertEqual(self.step(500, 1.2), [])
        self.assertEqual(self.p.target, "agx")

    def test_failed_return_probe_keeps_remote_and_no_release(self):
        self.activate()
        self.step(10, .5)
        self.assertEqual(self.step(67, .5), ["probe_nano"])
        self.assertEqual(self.step(68, .5, probe_result=False), ["return_blocked"])
        self.assertEqual(self.p.target, "agx")
        self.assertFalse(self.p.returned)

    def test_stale_or_wrong_identity_cannot_switch(self):
        self.step(0); self.step(5)
        s = snapshots(6)
        s["agx"]["node_id"] = "rtx-substitute"
        self.assertEqual(self.p.step(6, 1.2, 20, {}, s, 0, True), [])
        self.assertEqual(self.p.target, "nano")
        self.assertEqual(self.p.step(20, 1.2, 20, {}, snapshots(6), 0, True), [])

    def test_ready_poll_can_arrive_after_probe_without_losing_switch(self):
        self.step(0); self.step(5)
        stale = snapshots(6)
        stale["agx"]["inference_ready"] = False
        self.assertEqual(self.p.step(6, 1.2, 20, {}, stale, 0, True), [])
        self.assertEqual(self.step(7), ["switch_remote"])

    def test_bounded_queue_can_reach_activation_break_even(self):
        limit = self.p.config["queue_limit"]
        self.step(0, pending=limit)
        self.assertEqual(self.step(5, pending=limit), ["activate"])

    def test_existing_source_queue_is_not_counted_as_migratable_gain(self):
        self.step(0, pending=30)
        self.assertEqual(self.step(5, pending=30), [])
        self.assertLess(self.p.last_prediction["gain"], .15)
        self.assertEqual(self.step(6, pending=0), ["activate"])

    def test_pressure_can_activate_before_queue_accumulates(self):
        self.assertEqual(self.step(0, pending=0), [])
        self.assertEqual(self.step(5, pending=0), ["activate"])
        self.assertGreaterEqual(self.p.last_prediction["gain"], .15)

    def test_offload_is_blocked_when_arrival_rate_exceeds_remote_capacity(self):
        self.step(0, rate=3)
        self.assertEqual(self.step(5, rate=3), [])
        self.assertEqual(self.p.state, "LOCAL")

    def test_pending_remote_requests_block_model_release(self):
        self.p.state = "LOCAL_DRAIN"
        self.assertEqual(self.p.step(100, .1, 1, {}, snapshots(100), 0, queued_by_node={"agx": 1}), [])

    def test_busy_worker_cannot_be_released(self):
        self.p.state = "LOCAL_DRAIN"
        s = snapshots(100)
        s["agx"]["active_requests"] = 1
        self.assertEqual(self.p.step(100, .1, 0, {}, s, 0), [])


class EvidenceTests(unittest.TestCase):
    def test_empty_and_ready_only_runs_never_pass(self):
        p = cp.freeze(fixture_baseline())
        self.assertFalse(report.report(p, [])["passed"])
        r = {"contract": cp.CONTRACT, "policy_id": p["policy_id"], "planned": 0,
             "status": "completed", "events": [{"event": "switch_remote", "at": 1}], "requests": []}
        self.assertFalse(report.evaluate(p, r)["passed"])

    def test_ten_successful_candidates_do_not_hide_invalid_control_evidence(self):
        p = cp.freeze(fixture_baseline())
        runs = [{"repeat": i, "control": control, "planned": 1, "stages": [["same", 1, 1]],
                 "passed": True, "checks": {"no_rejection_or_error": True, "same_contract_policy": True},
                 "p95_latency_ms": 100} for i in range(10) for control in (True, False)]
        with patch.object(report, "evaluate", side_effect=lambda policy, run: run):
            self.assertTrue(report.report(p, runs)["passed"])
            runs[0]["passed"] = False
            self.assertFalse(report.report(p, runs)["passed"])

    def test_journal_keeps_dispatch_intent_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = cr.Journal(tmp)
            j.save({"id": "one", "status": "running", "requests": [{"request_id": "r1", "status": "queued", "dispatch_at": 1}]})
            j.close()
            j = cr.Journal(tmp)
            self.assertEqual(j.unfinished()[0]["requests"][0]["request_id"], "r1")
            j.close()

    def test_incremental_journal_recovers_accepted_and_dispatched_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = cr.Journal(tmp)
            j.save({"id": "run", "kind": "nano-agx-roundtrip/v1", "status": "running", "requests": [], "events": [], "samples": []})
            first = {"request_id": "first", "sequence": 0, "selected_node": "nano", "status": "queued", "dispatch_at": 1.}
            second = {"request_id": "second", "sequence": 1, "selected_node": "agx", "status": "queued"}
            event = {"event": "dispatch", "request_id": "first", "at": 1.}
            j.put_entries("run", [("request", "second", 1, second)])
            j.put_entries("run", [("request", "first", 0, first), ("event", 0, 0, event)])
            j.close()
            j = cr.Journal(tmp)
            record = j.unfinished()[0]
            self.assertEqual(record["requests"], [first, second])
            self.assertEqual(record["events"], [event])
            self.assertEqual(j.latest(), record)
            record.update(status="interrupted_recovered")
            j.save(record)
            self.assertEqual(j.db.execute("SELECT count(*) FROM entries").fetchone()[0], 0)
            self.assertEqual(j.latest()["requests"], [first, second])
            self.assertEqual(j.unfinished(), [])
            j.close()

    def test_frozen_files_are_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"policy.json"
            cr.write_new(path, {"first": True})
            with self.assertRaises(FileExistsError):
                cr.write_new(path, {"first": False})
            self.assertTrue(json.loads(path.read_text())["first"])

    def test_stream_measures_first_token_before_final_response(self):
        def generate(payload, on_token=None):
            on_token("first")
            time.sleep(.08)
            return {"request_id": payload["request_id"], "node_id": cp.NODES["nano"],
                    "model_digest": cp.MODEL_DIGEST, "response": "first"}
        server = ThreadingHTTPServer(("127.0.0.1", 0), worker.Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with patch.object(worker, "generate", side_effect=generate), patch.dict(cr.URLS, nano=f"http://127.0.0.1:{server.server_port}"):
                row = {"request_id": "r1", "arrival_at": time.monotonic()}
                cr.Client().generate("nano", row)
                self.assertEqual(row["status"], "ok")
                self.assertGreater(row["latency_ms"]-row["ttft_ms"], 50)
        finally:
            server.shutdown(); server.server_close(); t.join()

    def test_actual_runner_pins_queued_requests_and_drains_source_after_switch(self):
        class FakePolicy:
            def __init__(self, config):
                self.target = "nano"; self.state = "LOCAL"; self.start = None; self.last_prediction = None
            def fresh(self, *args): return True
            def step(self, now, *args, **kwargs):
                if self.start is None: self.start = now
                if self.target == "nano" and now-self.start >= .06:
                    self.target = "agx"; self.state = "RELEASED"
                    return ["switch_remote"]
                return []
        class FakeClient:
            def prepare(self): pass
            def snapshot(self, node): return snapshots(time.monotonic())[node]
            def generate(self, node, row, emit=None):
                time.sleep(.12 if node == "nano" else .005)
                now = time.monotonic()
                row.update(status="ok", identity_verified=True, actual_node=cp.NODES[node],
                           model_digest=cp.MODEL_DIGEST, first_token_at=now, completed_at=now,
                           ttft_ms=(now-row["arrival_at"])*1000, latency_ms=(now-row["arrival_at"])*1000)
                return row
        policy = cp.freeze(fixture_baseline());policy["queue_limit"] = 100
        policy["policy_id"] = cp.digest({k:v for k,v in policy.items() if k != "policy_id"})
        with tempfile.TemporaryDirectory() as tmp, patch.object(cr, "Policy", FakePolicy), patch.object(cr, "workload_stages", return_value=[("diagnostic", .4, 30)]):
            journal = cr.Journal(tmp)
            run = cr.round_trip(FakeClient(), journal, policy)
            journal.close()
        switched = next(e["at"] for e in run["events"] if e["event"] == "switch_remote")
        self.assertTrue(any(r["selected_node"] == "agx" for r in run["requests"]))
        self.assertTrue(any(r["selected_node"] == "nano" and r["dispatch_at"] > switched for r in run["requests"]))
        self.assertTrue(all(r["status"] == "ok" and r["selected_node"] == r["admitted_node"] for r in run["requests"]))

    def test_actual_runner_records_one_dispatch_and_durable_completion(self):
        durable_before_send = []
        class FakeClient:
            def prepare(self):
                pass
            def snapshot(self, node):
                return snapshots(time.monotonic())[node]
            def generate(self, node, row, emit=None):
                stored = journal.latest()
                durable_before_send.append(any(r.get("request_id") == row["request_id"] and "dispatch_at" in r for r in stored["requests"])
                    and any(e.get("event") == "dispatch" and e.get("request_id") == row["request_id"] for e in stored["events"]))
                now = time.monotonic()
                row.update(status="ok", identity_verified=True, actual_node=cp.NODES[node],
                           model_digest=cp.MODEL_DIGEST, first_token_at=now, completed_at=now,
                           ttft_ms=(now-row["arrival_at"])*1000, latency_ms=(now-row["arrival_at"])*1000)
                return row
        with tempfile.TemporaryDirectory() as tmp, patch.object(cr, "workload_stages", return_value=[("test", .05, 20)]):
            journal = cr.Journal(tmp)
            policy = cp.freeze(fixture_baseline())
            run = cr.round_trip(FakeClient(), journal, policy, control=True)
            self.assertEqual(run["status"], "completed")
            self.assertEqual(len(run["requests"]), 1)
            self.assertEqual(run["requests"][0]["status"], "ok")
            self.assertEqual(len([e for e in run["events"] if e["event"] == "dispatch"]), 1)
            self.assertEqual(journal.unfinished(), [])
            self.assertEqual(durable_before_send, [True])
            self.assertTrue(report.evaluate(policy, run)["checks"]["no_rejection_or_error"])
            self.assertFalse(report.evaluate(policy, run)["checks"]["fixed_workload"])
            journal.close()

    def test_source_worker_cannot_unload_existing_nano_model(self):
        with patch.dict(worker.os.environ, CONTINUITY_SOURCE="1"):
            with self.assertRaisesRegex(ValueError, "release is disabled"):
                worker.deactivate({"target_state": "CACHED"})
            with self.assertRaisesRegex(ValueError, "stay ACTIVE"):
                worker.activate({"target_state": "CACHED"})

    def test_storage_gate_blocks_pressure_and_model_download_without_headroom(self):
        n = {"metadata": {"name": cp.NODES["agx"]}, "status": {"conditions": [
            {"type": k, "status": "True" if k == "Ready" else "False"}
            for k in ["Ready", "DiskPressure", "MemoryPressure", "PIDPressure"]]}}
        summary = {"node": {"fs": {"capacityBytes": 58_000_000_000, "availableBytes": 8_800_000_000}}}
        self.assertFalse(continuity_preflight.assess(n, summary)["passed"])
        summary["node"]["fs"]["availableBytes"] = 25_000_000_000
        self.assertTrue(continuity_preflight.assess(n, summary)["passed"])
        n["status"]["conditions"][1]["status"] = "True"
        self.assertFalse(continuity_preflight.assess(n, summary)["passed"])

    def test_sd_storage_gate_separates_root_image_budget_and_model_cache(self):
        node = {"metadata": {"name": cp.NODES["agx"]}, "status": {"conditions": [
            {"type": k, "status": "True" if k == "Ready" else "False"}
            for k in ["Ready", "DiskPressure", "MemoryPressure", "PIDPressure"]]}}
        summary = {"node": {"fs": {"capacityBytes": 58_000_000_000, "availableBytes": 15_000_000_000}}}
        sd = {"availableBytes": 120_000_000_000, "capacityBytes": 125_000_000_000,
              "readonly": 0, "deviceError": 0, "mountpoint": continuity_preflight.SD_MOUNT,
              "device": continuity_preflight.SD_DEVICE, "fstype": "ext4"}
        self.assertTrue(continuity_preflight.assess(node, summary, model_fs=sd)["passed"])
        for key, value in [("readonly", 1), ("deviceError", 1), ("availableBytes", 1),
                           ("fstype", "exfat"), ("device", "/dev/mmcblk0p1"),
                           ("mountpoint", "/"), ("availableBytes", float("nan"))]:
            self.assertFalse(continuity_preflight.assess(node, summary, model_fs={**sd, key: value})["passed"])
        self.assertFalse(continuity_preflight.assess(node, summary, model_fs={})["passed"])
        summary["node"]["fs"]["availableBytes"] = 12_000_000_000
        self.assertFalse(continuity_preflight.assess(node, summary, model_fs=sd)["passed"])

    def test_sd_metrics_never_substitute_root_or_other_filesystems(self):
        labels = 'device="/dev/mmcblk1p1",device_error="",fstype="ext4",mountpoint="/srv/agx-model-cache"'
        lines = [f'{name}{{{labels}}} {value}' for name, value in [
            ("node_filesystem_avail_bytes", "1.2e11"), ("node_filesystem_size_bytes", "1.25e11"),
            ("node_filesystem_readonly", "0"), ("node_filesystem_device_error", "0")]]
        parsed = continuity_preflight.parse_sd_metrics("\n".join(lines))
        self.assertEqual(parsed["availableBytes"], 120_000_000_000)
        self.assertNotIn("availableBytes", continuity_preflight.parse_sd_metrics(lines[0].replace('/srv/agx-model-cache', '/')))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            continuity_preflight.parse_sd_metrics("\n".join(lines + [lines[0]]))
        with self.assertRaisesRegex(ValueError, "invalid"):
            continuity_preflight.parse_sd_metrics(lines[0].replace("1.2e11", "NaN"))

    def test_sd_budget_rejects_manifest_pointing_to_emmc_or_another_node(self):
        import copy
        base = Path(__file__).resolve().parents[1]/"nano-agx-k8s"
        manifest = json.loads((base/"resources.yaml").read_text())
        storage = json.loads((base/"sd-storage.yaml").read_text())
        agx = next(i for i in manifest["items"] if i["kind"] == "Deployment" and i["metadata"]["name"] == "llama-agx")
        continuity_preflight.validate_sd_manifest(agx, storage)
        bad = copy.deepcopy(agx)
        next(v for v in bad["spec"]["template"]["spec"]["volumes"] if v["name"] == "model-cache")["persistentVolumeClaim"]["claimName"] = "llama-agx-cache"
        with self.assertRaises(ValueError):
            continuity_preflight.validate_sd_manifest(bad, storage)
        for field, value in [("local", {"path": "/opt/local-path-provisioner", "fsType": "ext4"}),
                             ("nodeAffinity", {})]:
            bad = copy.deepcopy(storage)
            next(i for i in bad["items"] if i["kind"] == "PersistentVolume")["spec"][field] = value
            with self.assertRaises(ValueError):
                continuity_preflight.validate_sd_manifest(agx, bad)

    def test_slim_runtime_filter_preserves_active_backend_and_base_files(self):
        import runpy
        keep = runpy.run_path(str(Path(__file__).resolve().parents[1]/"nano-agx-k8s/build-runtime.py"))["keep"]
        for path in ["usr/lib/ollama/cuda_jetpack6/libggml-cuda.so", "usr/lib/ollama/llama-server",
                     "usr/bin/ollama", "usr/lib/aarch64-linux-gnu/libc.so.6"]:
            self.assertTrue(keep(path))
        for backend in ["cuda_v12", "cuda_v13", "cuda_jetpack5"]:
            self.assertFalse(keep("./usr/lib/ollama/" + backend + "/libggml-cuda.so"))

    def test_storage_gate_credits_only_running_exact_runtime_on_actual_agx(self):
        import copy
        node = {"metadata": {"name": cp.NODES["agx"]}, "status": {"conditions": [
            {"type": k, "status": "True" if k == "Ready" else "False"}
            for k in ["Ready", "DiskPressure", "MemoryPressure", "PIDPressure"]]}}
        summary = {"node": {"fs": {"capacityBytes": 58_000_000_000, "availableBytes": 15_500_000_000}}}
        pod = {"spec": {"nodeName": cp.NODES["agx"], "containers": [
            {"name": "inference-runtime", "image": cp.AGX_RUNTIME_IMAGE}]}, "status": {"containerStatuses": [
            {"name": "inference-runtime", "ready": True, "state": {"running": {"startedAt": "2026-09-08"}}}]}}
        self.assertFalse(continuity_preflight.assess(node, summary)["passed"])
        self.assertTrue(continuity_preflight.assess(node, summary, [pod])["passed"])
        for change in ["node", "image", "ready"]:
            bad = copy.deepcopy(pod)
            if change == "node": bad["spec"]["nodeName"] = cp.NODES["nano"]
            if change == "image": bad["spec"]["containers"][0]["image"] = cp.RUNTIME_IMAGE
            if change == "ready": bad["status"]["containerStatuses"][0]["ready"] = False
            self.assertFalse(continuity_preflight.assess(node, summary, [bad])["passed"])

    def test_worker_metadata_failure_does_not_decrement_active_twice(self):
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __iter__(self): return iter([b'{"response":"token","done":true,"eval_count":1}\n'])
        state = worker.State()
        state.node_state = "ACTIVE"
        with patch.object(worker, "STATE", state), patch.object(worker, "model_loaded", return_value=True), patch.object(worker.request, "urlopen", return_value=Stream()), patch.object(worker, "model_metadata", side_effect=RuntimeError("metadata unavailable")):
            with self.assertRaisesRegex(RuntimeError, "metadata unavailable"):
                worker.generate({"prompt": "test", "request_id": "metadata-failure"})
        self.assertEqual(state.active_requests, 0)
        self.assertEqual(state.failed_requests, 1)
        self.assertEqual(state.completed_requests, 0)

    def test_manifest_uses_real_agx_shared_slot_and_no_host_mounts(self):
        manifest = json.loads((Path(__file__).resolve().parents[1]/"nano-agx-k8s/resources.yaml").read_text())
        deployments = {i["metadata"]["name"]: i for i in manifest["items"] if i["kind"] == "Deployment"}
        agx = deployments["llama-agx"]["spec"]["template"]["spec"]
        self.assertEqual(agx["nodeSelector"]["kubernetes.io/hostname"], cp.NODES["agx"])
        runtime = next(c for c in agx["containers"] if c["name"] == "inference-runtime")
        self.assertEqual(runtime["resources"]["limits"]["nvidia.com/gpu.shared"], 1)
        self.assertFalse(runtime["securityContext"].get("privileged", False))
        self.assertFalse(any("hostPath" in v for v in agx["volumes"]))


if __name__ == "__main__":
    unittest.main()
