"""Fail-closed acceptance and paired performance reporting from request evidence."""
import math
from continuity_policy import CONTRACT, MODEL_DIGEST, NODES, p95, validate_policy, workload_stages


def evaluate(policy, run):
    rows, events = run.get("requests", []), run.get("events", [])
    ok = [r for r in rows if r.get("status") == "ok"]
    ids = [r.get("request_id") for r in rows]
    dispatches = [e for e in events if e.get("event") == "dispatch"]
    def named(name):
        return [e for e in events if e.get("event") == name]
    remote, local, release = named("switch_remote"), named("switch_local"), named("release_verified")
    stages = workload_stages(policy)
    scheduled = []
    offset = 0.
    for phase, seconds, rate in stages:
        scheduled.extend((offset+i/rate, phase) for i in range(math.floor(seconds*rate)))
        offset += seconds
    remote_response = bool(remote) and any(r.get("selected_node") == "agx" and r.get("actual_node") == NODES["agx"]
            and r.get("dispatch_at", -1) >= remote[0]["at"] and r.get("identity_verified") for r in ok)
    local_response = bool(local) and any(r.get("selected_node") == "nano" and r.get("actual_node") == NODES["nano"]
            and r.get("dispatch_at", -1) >= local[0]["at"] and r.get("identity_verified") for r in ok)
    checks = {
        "same_contract_policy": run.get("contract") == CONTRACT and run.get("policy_id") == policy["policy_id"],
        "run_completed": run.get("status") == "completed",
        "all_offered_accounted": bool(rows) and len(rows) == run.get("planned"),
        "fixed_workload": ([list(s) for s in run.get("stages", [])] == [list(s) for s in stages]
                           and len(rows) == len(scheduled)
                           and all(r.get("phase") == phase and abs(r.get("arrival_at", math.inf)-run.get("workload_started", 0)-due) < .01
                                   for r, (due, phase) in zip(rows, scheduled))),
        "no_missing_or_duplicate_ids": bool(ids) and all(ids) and len(ids) == len(set(ids)),
        "no_rejection_or_error": bool(rows) and len(ok) == len(rows) and all(r.get("accepted") for r in rows),
        "identity": bool(ok) and all(r.get("identity_verified") and r.get("actual_node") == NODES.get(r.get("selected_node"))
                                     and r.get("model_digest") == MODEL_DIGEST for r in ok),
        "single_dispatch": len(dispatches) == len(rows) and {e.get("request_id") for e in dispatches} == set(ids),
        "fresh_ready_dispatch": bool(dispatches) and all(0 <= e["at"]-e.get("ready_observed_at", -1e9) <= policy["settings"]["fresh_seconds"] for e in dispatches),
        "request_timestamps": bool(ok) and all(r.get("arrival_at", math.inf) <= r.get("dispatch_at", -1) <= r.get("first_token_at", -1) <= r.get("completed_at", -1)
                                    and math.isfinite(r.get("ttft_ms", math.inf)) and r.get("ttft_ms", 0) > 0
                                    and abs(r["ttft_ms"]-(r["first_token_at"]-r["arrival_at"])*1000) < .1
                                    and math.isfinite(r.get("latency_ms", math.inf))
                                    and abs(r["latency_ms"]-(r["completed_at"]-r["arrival_at"])*1000) < .1 for r in ok),
    }
    if not run.get("control"):
        def expected_admission(row):
            received = row.get("received_at", -math.inf)
            return "agx" if remote and received >= remote[0]["at"] and (not local or received < local[0]["at"]) else "nano"
        checks["admission_route_and_drain"] = bool(rows) and all(
            r.get("admitted_node") == expected_admission(r)
            and r.get("selected_node") == r.get("admitted_node") for r in rows)
        checks.update(remote_response=remote_response, nano_return_response=local_response,
                      ordered_roundtrip=bool(remote and local and release) and remote[0]["at"] < local[0]["at"] < release[0]["at"],
                      model_release=bool(release) and release[-1].get("evidence", {}).get("model_loaded") is False
                          and release[-1].get("evidence", {}).get("model_vram_mib") == 0
                          and release[-1].get("evidence", {}).get("node_state") == "CACHED",
                      no_failure_events=not any(e.get("event") in {"fallback", "activation_failed", "activate_failed", "return_blocked", "release_failed", "cleanup_blocked"} for e in events))
    activation = named("activate")
    ready = named("activate_verified")
    activation_rows = [r for r in ok if activation and ready and r.get("arrival_at", math.inf) <= ready[0]["at"]
                       and r.get("first_token_at", -1) >= activation[0]["at"]]
    warm_rows = [r for r in ok if r not in activation_rows]
    warm_p95 = p95([r["ttft_ms"] for r in warm_rows]) if warm_rows else None
    activation_max = max([r["ttft_ms"] for r in activation_rows], default=None)
    latency_ok = (warm_p95 is not None and warm_p95 <= policy["slo_ms"]
                  and (activation_max is None or activation_max <= policy["activation_slo_ms"]))
    if not run.get("control"):
        checks["latency_budget"] = latency_ok
    completed = sorted(r["completed_at"] for r in ok)
    anchors = ([min(r["arrival_at"] for r in rows)] if rows else []) + completed
    duration = completed[-1]-anchors[0] if completed else None
    return {"id": run.get("id"), "repeat": run.get("repeat"), "control": run.get("control"),
            "passed": all(checks.values()), "checks": checks, "offered": len(rows), "completed": len(ok),
            "rejected": sum(r.get("status") == "rejected" for r in rows),
            "unknown": sum(r.get("status") == "unknown" for r in rows),
            "p95_ttft_ms": p95([r["ttft_ms"] for r in ok]) if ok else None,
            "p95_latency_ms": p95([r["latency_ms"] for r in ok]) if ok else None,
            "warm_p95_ttft_ms": warm_p95, "activation_max_ttft_ms": activation_max,
            "throughput_rps": len(ok)/duration if duration and duration > 0 else None,
            "max_completion_gap_ms": max([(b-a)*1000 for a,b in zip(anchors, anchors[1:])], default=None)}


def report(policy, runs):
    validate_policy(policy)
    results = [evaluate(policy, r) for r in runs]
    candidates = [r for r in results if not r["control"]]
    controls = [r for r in results if r["control"]]
    unique_repeats = len(candidates) == 10 and {r["repeat"] for r in candidates} == set(range(10))
    pairs = []
    for candidate in candidates:
        control = [c for c in controls if c["repeat"] == candidate["repeat"]]
        originals = [r for r in runs if r.get("repeat") == candidate["repeat"]]
        same_schedule = len(originals) == 2 and originals[0].get("stages") == originals[1].get("stages") and originals[0].get("planned") == originals[1].get("planned")
        comparable = (same_schedule and len(control) == 1 and control[0]["checks"]["no_rejection_or_error"]
                      and candidate["checks"]["no_rejection_or_error"]
                      and control[0]["checks"]["same_contract_policy"] and candidate["checks"]["same_contract_policy"])
        pairs.append({"repeat": candidate["repeat"], "comparable": comparable,
                      "p95_latency_improvement_percent": 100*(1-candidate["p95_latency_ms"]/control[0]["p95_latency_ms"]) if comparable else None})
    return {"policy_id": policy["policy_id"], "passed": unique_repeats and all(r["passed"] for r in candidates)
            and len(controls) == 10 and {r["repeat"] for r in controls} == set(range(10))
            and all(r["passed"] for r in controls) and all(p["comparable"] for p in pairs),
            "scope": "development qualification; not an uninterrupted-service guarantee",
            "normal_roundtrips_required": 10, "normal_roundtrips_present": len(candidates),
            "runs": results, "performance_pairs": pairs}
