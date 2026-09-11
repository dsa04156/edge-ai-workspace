"""Recompute three-device model results from immutable request and runtime logs."""
import argparse
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import bench


def aggregate(rows):
    measured = [r for r in rows if r["phase"] == "measure"]
    good = [r for r in measured if r["status"] == "ok"]
    waves = collections.defaultdict(list)
    for r in measured:
        waves[r["block"], r["case"]].append(r)
    active_seconds = sum(max(x["completed_at"] for x in wave) - min(x["planned_at"] for x in wave)
                         for wave in waves.values())
    latency = [r["latency_ms"] for r in good]
    return {"requests": len(measured), "success": len(good), "failures": len(measured) - len(good),
            "blocks": len({r["block"] for r in measured}),
            "p50_latency_ms": bench.percentile(latency, .5), "p95_latency_ms": bench.percentile(latency, .95),
            "min_latency_ms": min(latency, default=None), "max_latency_ms": max(latency, default=None),
            "p95_ttft_ms": bench.percentile([r["ttft_ms"] for r in good if r["ttft_ms"] is not None], .95),
            "median_decode_tokens_s": bench.percentile([r["decode_tokens_per_second"] for r in good if r["decode_tokens_per_second"] is not None], .5),
            "active_wave_requests_s": len(good) / active_seconds if active_seconds > 0 else None,
            "active_wave_output_tokens_s": sum(r["actual_output_tokens"] for r in good) / active_seconds if active_seconds > 0 else None}


def report(root, supplement=None):
    supplements = supplement or []
    if isinstance(supplements, Path):
        supplements = [supplements]
    models = json.loads((root / "models.json").read_text())
    plan = json.loads((root / "plan.json").read_text())
    before = json.loads((root / "nodes-before.json").read_text())
    cells, all_rows, fixture_hashes, aborted_rows = [], [], collections.defaultdict(set), []
    interrupted_without_terminal = 0
    for node in plan["nodes"]:
        for m in models:
            for block in range(plan["blocks"]):
                folder = root / node / (m["slug"] + f"-b{block}")
                for extra in supplements:
                    candidate = extra / node / (m["slug"] + f"-b{block}")
                    if (candidate / "workload/complete.json").exists():
                        # The continuation only reruns incomplete/failed cells. Do not
                        # select between successful runs according to their latency.
                        if (folder / "workload/complete.json").exists():
                            raise ValueError("Ambiguous successful cell in both sources")
                        failure_source = folder / "failed-attempt-settled/requests.jsonl"
                        if not failure_source.exists():
                            failure_source = folder / "failed-attempt-final/requests.jsonl"
                        if not failure_source.exists():
                            failure_source = folder / "workload/requests.jsonl"
                        if failure_source.exists():
                            for line in failure_source.read_text().splitlines():
                                row = json.loads(line)
                                row["physical_node"] = row["selected_node"]
                                row.update(node=node, model=m["model"], block=block)
                                aborted_rows.append(row)
                        reconciliation = folder / "interruption-reconciliation.json"
                        if reconciliation.exists():
                            interrupted_without_terminal += json.loads(reconciliation.read_text())["in_flight_without_terminal_record"]
                        folder = candidate
                cell = {"node": node, "model": m["model"], "block": block, "complete": False,
                        "planned_requests": 18, "path": os.path.relpath(folder, root),
                        "thermal_conditioning": (folder / "workload/cooling.jsonl").exists()}
                source = folder / "workload/requests.jsonl"
                if source.exists():
                    rows = [json.loads(line) for line in source.read_text().splitlines()]
                    for r in rows:
                        r["physical_node"] = r["selected_node"]
                        r.update(node=node, model=m["model"], block=block)
                    cell["physical_node_valid"] = all(r["physical_node"] == before[node]["node"] for r in rows)
                    measured = [r for r in rows if r["phase"] == "measure"]
                    identifiers = [r["request_id"] for r in measured]
                    cell["unique_requests"] = len(set(identifiers)) == len(identifiers)
                    expected_cases = {"i512-o128-c1": 1, "i512-o128-c2": 2, "i512-o128-c4": 4,
                        "i512-o128-c8": 8, "i128-o64-c1": 1, "i2048-o128-c1": 1, "i512-o256-c1": 1}
                    cell["case_counts_valid"] = dict(collections.Counter(r["case"] for r in measured)) == expected_cases
                    cell["warmup_count"] = sum(r["phase"] == "warmup" for r in rows)
                    cell["token_cache_valid"] = all(r["status"] == "ok" and r["zero_prefix_reuse_verified"] is True
                        and r["actual_input_tokens"] == r["input_tokens_requested"]
                        and r["actual_output_tokens"] == r["output_tokens_requested"] for r in rows)
                    cell["observed_requests"] = len(measured)
                    cell["complete"] = len(measured) == 18 and (folder / "workload/complete.json").exists()
                    all_rows.extend(rows)
                    fixtures = json.loads((folder / "workload/fixtures.json").read_text())
                    fixture_hashes[m["model"]].add(hashlib.sha256(json.dumps(fixtures, sort_keys=True).encode()).hexdigest())
                cleanup = folder / "cleanup.json"
                cell["cleanup"] = json.loads(cleanup.read_text()) if cleanup.exists() else None
                if (folder / "events.jsonl").exists():
                    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
                    ready = next((e for e in events if e["event"] == "gpu_health_ready"), None)
                    cell["gpu_ready"] = ready
                if (folder / "server.log").exists():
                    log = (folder / "server.log").read_text()
                    buffers = re.findall(r"CUDA\d+\s+model buffer size\s*=\s*([\d.]+) MiB", log)
                    cell["gpu_model_buffer_mib"] = sum(map(float, buffers)) if buffers else None
                    cell["quantization_verified"] = bool(re.search(r"file type\s*=\s*Q8_0", log))
                if (folder / "resources.jsonl").exists():
                    samples = [json.loads(line) for line in (folder / "resources.jsonl").read_text().splitlines()]
                    rss = [int(match[1])/1024 for s in samples if (match := re.search(r"VmRSS:\s+(\d+)", s["sample"]))]
                    cell["peak_process_rss_mib"] = max(rss, default=None)
                cells.append(cell)
    grouped = []
    for node in plan["nodes"]:
        for m in models:
            rows = [r for r in all_rows if r["node"] == node and r["model"] == m["model"] and r["phase"] == "measure"]
            for case in sorted({r["case"] for r in rows}):
                grouped.append({"node": node, "model": m["model"], "case": case,
                                **aggregate([r for r in rows if r["case"] == case])})
    verified = {"expected_cells": len(plan["nodes"]) * len(models) * plan["blocks"], "observed_cells": len(cells),
                "complete_cells": sum(c["complete"] for c in cells),
                "planned_measured_requests": sum(c["planned_requests"] for c in cells),
                "observed_measured_requests": sum(r["phase"] == "measure" for r in all_rows),
                "successful_measured_requests": sum(r["phase"] == "measure" and r["status"] == "ok" for r in all_rows),
                "all_tokens_cache_valid": all(c.get("token_cache_valid", False) for c in cells),
                "all_unique_requests": all(c.get("unique_requests", False) for c in cells),
                "all_case_counts_valid": all(c.get("case_counts_valid", False) for c in cells),
                "all_physical_nodes_valid": all(c.get("physical_node_valid", False) for c in cells),
                "warmup_requests": sum(c.get("warmup_count", 0) for c in cells),
                "all_q8_verified": all(c.get("quantization_verified", False) for c in cells),
                "all_gpu_verified": all(c.get("gpu_ready") for c in cells),
                "all_cleanup_verified": all(c["cleanup"] and c["cleanup"].get("process_exited") and c["cleanup"].get("port_released") for c in cells),
                "same_model_fixtures_match_all_devices_blocks": {m: len(h) == 1 for m, h in fixture_hashes.items()},
                "service_restored": False, "production_policy_validated": False,
                "quality_evaluated": False}
    final_path = root / "final-state.json"
    if final_path.exists():
        final = json.loads(final_path.read_text())
        verified["service_restored"] = final.get("service_restored") is True
        verified["final_device_cleanup_verified"] = final.get("all_experiment_ports_closed") is True
        verified["final_pod_identity_preserved"] = final.get("pod_identity_preserved") is True
        verified["final_nodes_ready"] = final.get("all_nodes_ready") is True
    else:
        verified["final_device_cleanup_verified"] = False
        verified["final_pod_identity_preserved"] = False
        verified["final_nodes_ready"] = False
    aborted = [r for r in aborted_rows if r["phase"] == "measure"]
    aborted_cells = {(r["node"], r["model"], r["block"]) for r in aborted}
    aborted_planned = len(aborted_cells) * 18
    verified["additional_aborted_attempts"] = {"observed_measured": len(aborted),
        "success": sum(r["status"] == "ok" for r in aborted),
        "failed_or_timeout": sum(r["status"] != "ok" for r in aborted),
        "planned": aborted_planned, "not_sent": aborted_planned-len(aborted)-interrupted_without_terminal,
        "interrupted_without_terminal_record": interrupted_without_terminal,
        "cells": [list(c) for c in sorted(aborted_cells)],
        "reason": "Spark thermal guard and Nano management connection interruption; retained separately"}
    verified["thermal_conditioned_cells"] = sum(c["thermal_conditioning"] for c in cells)
    after_path = root / "nodes-after.json"
    if after_path.exists():
        after = json.loads(after_path.read_text())
        verified["pod_uid_preserved"] = {n: before[n]["uid"] == after[n]["uid"] for n in plan["nodes"]}
        def restarts(node):
            return {c["name"]: c["restartCount"] for c in node["before"]["status"]["containerStatuses"]}
        verified["restart_counts_preserved"] = {n: restarts(before[n]) == restarts(after[n]) for n in plan["nodes"]}
    else:
        verified["pod_uid_preserved"] = None
        verified["restart_counts_preserved"] = None
    (root / "verification.json").write_text(json.dumps(verified, indent=2))
    (root / "comparison.json").write_text(json.dumps({"conditions": grouped, "cells": cells}, indent=2))
    (root / "aborted-attempt-requests.json").write_text(json.dumps(aborted_rows, indent=2))
    fields = sorted(set().union(*(r.keys() for r in all_rows))) if all_rows else []
    with (root / "requests.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in all_rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()})
    print(json.dumps(verified, indent=2))
    return grouped, cells, verified


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--supplement", type=Path, nargs="+")
    a = p.parse_args()
    report(a.root, a.supplement)
