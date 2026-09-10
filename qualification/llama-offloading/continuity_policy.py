"""Measured, versioned Nano/real-AGX qualification policy. No cluster mutations."""
from __future__ import annotations
import hashlib
import json
import math
from dataclasses import dataclass

NODES = {"nano": "etri-dev0001-jetorn", "agx": "etri-dev0005-jetagx"}
MODEL_DIGEST = "baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878"
RUNTIME_IMAGE = "docker.io/ollama/ollama@sha256:020e4134285e2ef4d8fd801234176de3b4faadc992a3eb06c8e66a2f9d4c4ba2"
AGX_RUNTIME_IMAGE = "localhost/qualification/ollama-jetson@sha256:b1e591bcd625f3ecb0abdad843ad369a637e6f99f7543dd0d7581c20aee40a28"
# Measured from this exact OCI artifact; original full image must not use this budget.
AGX_IMAGE_COMPRESSED_BYTES = 530761031
AGX_IMAGE_UNPACKED_BYTES = 1144969448
PROMPT = "In one short sentence, explain why edge computing reduces latency."
CONTRACT = {"nodes": NODES, "model_digest": MODEL_DIGEST, "runtime_image": RUNTIME_IMAGE,
            "runtime_images": {"nano": RUNTIME_IMAGE, "agx": AGX_RUNTIME_IMAGE},
            "runtime_version": "0.33.2", "gpu_backend": "cuda_jetpack6",
            "calibration_low_rps": .25,
            "calibration_busy_strategy": "30-sequential-requests-three-repeats/v1",
            "agx_model_storage": "sd-ext4:c6889d5e-37bb-4b07-8e0b-757d3de8c877",
            "prediction_model": "fcfs-overlapped-activation/v2",
            "calibration_load_strategy": "three-repeats-until-first-failing-step",
            "prompt": PROMPT, "max_tokens": 8, "temperature": 0, "seed": 42,
            "num_ctx": 2048, "worker_concurrency": 1,
            "clock": "client-monotonic", "ttft_boundary": "scheduled-arrival-to-first-stream-token"}
DEFAULTS = {"high_ratio": .85, "low_ratio": .60, "pressure_seconds": 5.,
            "return_seconds": 30., "cooldown_seconds": 60., "idle_seconds": 30.,
            "min_gain": .15, "fresh_seconds": 3., "rate_window_seconds": 10.}


def workload_stages(policy):
    cn = policy["capacity_rps"]["nano"]
    return [("low", 30., .5*cn), ("high", 120., 1.2*cn), ("low_return", 120., .5*cn)]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def p95(values):
    if not values or any(not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("missing or invalid measured samples")
    return sorted(values)[math.ceil(.95 * len(values)) - 1]


def valid_batch(batch):
    rows = batch.get("requests", [])
    ids = [r.get("request_id") for r in rows]
    return (bool(rows) and len(rows) == batch.get("planned") and all(ids)
            and len(ids) == len(set(ids)) and all(r.get("status") == "ok" and r.get("identity_verified")
            and positive(r.get("ttft_ms")) and positive(r.get("latency_ms")) for r in rows))


def stable(batch, slo):
    samples = batch.get("outstanding", [])
    if not valid_batch(batch) or batch.get("duration_seconds", 0) < 30 or len(samples) < 10:
        return False
    third = max(1, len(samples) // 3)
    early = sum(samples[:third]) / third
    late = sum(samples[-third:]) / third
    return (late <= early + .5 and p95([r["ttft_ms"] for r in batch["requests"]]) <= slo
            and batch["completed_during_arrivals"] >= batch["planned"] * .98)


def valid_low_batch(batch):
    rows = batch.get("requests", [])
    arrivals = [r.get("arrival_at") for r in rows]
    return (valid_batch(batch) and len(rows) >= 30 and batch.get("rps") == CONTRACT["calibration_low_rps"]
            and batch.get("duration_seconds", 0) >= 30/CONTRACT["calibration_low_rps"]
            and all(isinstance(t, (int, float)) and math.isfinite(t) for t in arrivals)
            and all(abs(b-a-1/CONTRACT["calibration_low_rps"]) < .001 for a,b in zip(arrivals, arrivals[1:])))


def valid_busy_batch(batch):
    rows = batch.get("requests", [])
    return (valid_batch(batch) and len(rows) == 30
            and batch.get("method") == CONTRACT["calibration_busy_strategy"]
            and all(positive(r.get("completed_at")) and positive(r.get("arrival_at")) for r in rows)
            and all(0 <= b["arrival_at"]-a["completed_at"] <= .05 for a, b in zip(rows, rows[1:])))


def predict_overlap(config, rate, pending=0, inflight=None):
    """Compare the same FCFS arrivals; Nano serves while AGX activates.

    The observed rate is assumed to persist for activation + existing cooldown.
    Sum of per-request response times includes the preparation interval and backlog.
    This is a development forecast, not a promise about future arrivals.
    """
    if not positive(rate) or pending < 0:
        raise ValueError("forecast requires a positive rate and nonnegative backlog")
    inflight = inflight or {}
    activation = config["activation_max_ms"]/1000
    horizon = activation + config["settings"]["cooldown_seconds"]
    count = math.floor(horizon*rate)
    if count < 1 or pending+count > 100_000:
        raise ValueError("forecast arrival count outside bounded simulation")
    sn, sa = (config["service_ms"][n]/1000 for n in ("nano", "agx"))
    original = source = inflight.get("nano", 0)*sn
    remote = max(activation, inflight.get("agx", 0)*sa)
    local_total = candidate_total = 0.
    local_count = remote_count = 0
    for i in range(pending+count):
        arrival = 0. if i < pending else (i-pending+1)/rate
        original = max(original, arrival)+sn
        local_total += original-arrival
        if arrival < activation:
            source = max(source, arrival)+sn
            complete = source
            local_count += 1
        else:
            remote = max(remote, arrival)+sa
            complete = remote
            remote_count += 1
        candidate_total += complete-arrival
    return {"model": CONTRACT["prediction_model"], "horizon_seconds": horizon,
            "rate_rps": rate, "pending": pending, "requests": pending+count,
            "local_during_activation": local_count, "remote_after_ready": remote_count,
            "local_mean_response_ms": 1000*local_total/(pending+count),
            "candidate_mean_response_ms": 1000*candidate_total/(pending+count),
            "gain": 1-candidate_total/local_total}


def freeze(baseline):
    """Reject substitutes, missing repetitions, CPU fallback, and incomplete evidence."""
    if (baseline.get("contract") != CONTRACT or baseline.get("kind") != "live-calibration/v2"
            or baseline.get("status") != "completed"):
        raise ValueError("baseline must be the fixed real Nano/AGX live calibration contract")
    batches = baseline.get("batches", [])
    low, profiles = {}, {}
    for node in NODES:
        health = baseline.get("gpu_evidence", {}).get(node, {})
        if (health.get("node_id") != NODES[node] or health.get("model_digest") != MODEL_DIGEST
                or not positive(health.get("model_vram_mib"))):
            raise ValueError(f"{node}: actual node/model/GPU residency evidence required")
        runs = [b for b in batches if b.get("node") == node and b.get("phase") == "low"]
        if len(runs) != 3 or {b.get("repeat") for b in runs} != {0, 1, 2} or not all(valid_low_batch(b) for b in runs):
            raise ValueError(f"{node}: three valid 30-request low-load repeats required")
        low[node] = max(p95([r["ttft_ms"] for r in b["requests"]]) for b in runs)
        busy = [b for b in batches if b.get("node") == node and b.get("phase") == "busy"]
        if len(busy) != 3 or {b.get("repeat") for b in busy} != {0, 1, 2} or not all(valid_busy_batch(b) for b in busy):
            raise ValueError(f"{node}: three valid sequential busy-service repeats required")
        profiles[node] = max(p95([r["latency_ms"] for r in b["requests"]]) for b in busy)
    slo = 2 * max(low.values())
    capacity = {}
    for node in NODES:
        runs = [b for b in batches if b.get("node") == node and b.get("phase") == "load"]
        rates = sorted({b["rps"] for b in runs})
        passed, bracketed = [], False
        for rate in rates:
            if not positive(rate):
                raise ValueError("invalid arrival rate")
            group = [b for b in runs if b["rps"] == rate]
            if len(group) != 3 or {b.get("repeat") for b in group} != {0, 1, 2}:
                raise ValueError("three repeats required at each offered rate")
            if all(stable(b, slo) for b in group):
                if not bracketed:
                    passed.append(rate)
            else:
                bracketed = True
        if not passed or not bracketed:
            raise ValueError(f"{node}: sustainable capacity must be bracketed by a failing load step")
        capacity[node] = max(passed)
    # A coarse 4 -> 8 step cannot establish whether AGX can carry exactly 4.8.
    # Accept only a separately measured three-repeat admission check, never interpolate.
    required = 1.2 * capacity["nano"]
    admission = baseline.get("agx_admission", [])
    if capacity["agx"] < required and admission:
        if (len(admission) == 3 and {b.get("repeat") for b in admission} == {0, 1, 2}
                and all(b.get("node") == "agx" and b.get("phase") == "admission"
                        and b.get("rps") == required and stable(b, slo)
                        and b.get("before", {}).get("node_id") == NODES["agx"]
                        and positive(b.get("before", {}).get("model_vram_mib")) for b in admission)):
            capacity["agx"] = required
    activations = baseline.get("activations", [])
    if len(activations) != 10 or not all(a.get("verified") and a.get("download_ms") == 0
            and positive(a.get("elapsed_ms")) for a in activations):
        raise ValueError("ten cache-only activation-to-probe measurements required")
    activation = max(a["elapsed_ms"] for a in activations)
    if capacity["agx"] < 1.2 * capacity["nano"]:
        raise ValueError("AGX_NOT_QUALIFIED: cannot independently handle 120% of Nano capacity")
    policy = {"schema": "nano-agx-continuity/v2", "contract": CONTRACT,
              "baseline_digest": digest(baseline), "slo_ms": slo, "capacity_rps": capacity,
              "service_ms": profiles, "low_ttft_ms": low, "activation_max_ms": activation,
              "activation_slo_ms": activation + slo,
              "queue_limit": max(1, math.ceil(required * activation / 1000)
                                 + math.ceil(capacity["nano"] * slo / 1000)),
              "settings": DEFAULTS.copy(), "routing_semantics": "pin-at-admission-drain-existing/v2"}
    policy["qualification_forecast"] = predict_overlap(policy, required)
    if policy["qualification_forecast"]["gain"] < DEFAULTS["min_gain"]:
        raise ValueError("AGX_NOT_QUALIFIED: overlapped forecast at qualification load cannot reach 15%")
    policy["policy_id"] = digest(policy)
    return policy


def validate_policy(policy):
    body = {k: v for k, v in policy.items() if k != "policy_id"}
    if (policy.get("policy_id") != digest(body) or policy.get("schema") != "nano-agx-continuity/v2"
            or policy.get("contract") != CONTRACT or policy.get("settings") != DEFAULTS
            or not policy.get("baseline_digest")
            or policy.get("routing_semantics") != "pin-at-admission-drain-existing/v2"):
        raise ValueError("policy contract/digest mismatch; recalibrate instead of editing thresholds")
    for v in [policy.get("slo_ms"), policy.get("activation_max_ms"), policy.get("activation_slo_ms"),
              policy.get("queue_limit"), *policy.get("capacity_rps", {}).values(),
              *policy.get("service_ms", {}).values(), *policy.get("low_ttft_ms", {}).values()]:
        if not positive(v):
            raise ValueError("policy requires positive finite measured values")
    if set(policy["capacity_rps"]) != set(NODES) or set(policy["service_ms"]) != set(NODES):
        raise ValueError("missing measured nodes")
    return policy


@dataclass
class Policy:
    config: dict
    state: str = "LOCAL"
    target: str = "nano"
    high_since: float | None = None
    low_since: float | None = None
    changed_at: float = -1e9
    remote_used: bool = False
    returned: bool = False
    faulted: bool = False
    prepared_verified: bool = False
    last_prediction: dict | None = None

    def __post_init__(self):
        validate_policy(self.config)

    def fresh(self, node, snapshots, now, ready=True):
        s = snapshots.get(node, {})
        return (s.get("node_id") == NODES[node] and s.get("model_digest") == MODEL_DIGEST
                and 0 <= now - s.get("observed_at", -1e9) <= self.config["settings"]["fresh_seconds"]
                and s.get("management_runtime_running") is True
                and (not ready or s.get("inference_ready") is True))

    def step(self, now, rate, pending, inflight, snapshots, last_remote, probe_result=None, remote_error=False, queued_by_node=None):
        c, s = self.config, self.config["settings"]
        actions = []
        nano = self.fresh("nano", snapshots, now)
        agx = self.fresh("agx", snapshots, now)
        if self.target == "agx" and (not agx or remote_error):
            self.target, self.state, self.faulted = "nano", "FAULT_LOCAL", True
            self.changed_at = now
            self.high_since = self.low_since = None
            return ["fallback"]
        if self.state == "PREPARING":
            self.prepared_verified = self.prepared_verified or probe_result is True
            if self.prepared_verified and agx and rate <= c["capacity_rps"]["agx"]:
                self.target, self.state, self.remote_used = "agx", "REMOTE", True
                self.changed_at = now
                return ["switch_remote"]
            if probe_result is False:
                self.state, self.faulted = "FAULT_LOCAL", True
                return ["activation_failed"]
            return []
        if self.state == "RETURNING":
            if probe_result is True and nano and rate <= s["low_ratio"] * c["capacity_rps"]["nano"]:
                self.target, self.state, self.returned = "nano", "LOCAL_DRAIN", True
                self.changed_at = now
                return ["switch_local"]
            if probe_result is not None:
                self.state, self.low_since = "REMOTE", None
                return ["return_blocked"]
            return []
        if self.state == "LOCAL_DRAIN":
            if (nano and self.fresh("agx", snapshots, now, ready=False)
                    and inflight.get("agx", 0) == 0 and (queued_by_node or {}).get("agx", 0) == 0 and now-last_remote >= s["idle_seconds"]
                    and snapshots["agx"].get("active_requests") == 0
                    and snapshots["agx"].get("queue_length") == 0):
                self.state = "RELEASING"
                return ["release"]
            return []
        if not nano or not self.fresh("agx", snapshots, now, ready=False):
            self.high_since = self.low_since = None
            return []
        if not positive(rate) and rate != 0:
            self.high_since = self.low_since = None
            return []
        if self.state == "REMOTE":
            low = rate <= s["low_ratio"] * c["capacity_rps"]["nano"]
            self.low_since = (now if self.low_since is None else self.low_since) if low else None
            if low and now-self.low_since >= s["return_seconds"] and now-self.changed_at >= s["cooldown_seconds"]:
                self.state = "RETURNING"
                return ["probe_nano"]
        if self.state == "LOCAL" and not self.faulted:
            predicted = (pending + inflight.get("nano", 0)) * c["service_ms"]["nano"] + c["low_ttft_ms"]["nano"]
            pressure = rate >= s["high_ratio"] * c["capacity_rps"]["nano"] or predicted > c["slo_ms"]
            self.high_since = (now if self.high_since is None else self.high_since) if pressure else None
            if (pressure and now-self.high_since >= s["pressure_seconds"] and now-self.changed_at >= s["cooldown_seconds"]
                    and positive(rate) and rate <= c["capacity_rps"]["agx"]):
                self.last_prediction = predict_overlap(c, rate, pending, inflight)
                if self.last_prediction["gain"] >= s["min_gain"]:
                    self.state = "PREPARING"
                    return ["activate"]
        return actions
