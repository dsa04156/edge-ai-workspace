from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXECUTOR_URL = os.getenv("EXECUTOR_URL", "http://10.98.117.212:8002")
PLACEMENT_URL = os.getenv("PLACEMENT_URL", "http://10.105.1.14:8001")
AGGREGATOR_URL = os.getenv("AGGREGATOR_URL", "http://10.101.227.71:8000")
HTTP_TIMEOUT_SECONDS = int(os.getenv("EXPERIMENT_HTTP_TIMEOUT_SECONDS", "180"))

RPI = "etri-dev0002-raspi5"
JETSON = "etri-dev0001-jetorn"
X86 = "etri-ser0001-cg0msb"
IMAGE = "192.168.0.56:5000/vision-stage-runner:latest"


RPI_PROFILE = {
    "hostname": RPI,
    "node_type": "edge_light_device",
    "arch": "aarch64",
    "compute_class": "low",
    "memory_class": "low",
    "accelerator_type": "none",
    "preferred_workload": ["capture"],
    "risky_workload": ["inference"],
}

JETSON_PROFILE = {
    "hostname": JETSON,
    "node_type": "edge_ai_device",
    "arch": "aarch64",
    "compute_class": "medium",
    "memory_class": "low",
    "accelerator_type": "gpu_embedded",
    "preferred_workload": ["preprocess"],
    "risky_workload": ["large_model_serving"],
}

X86_PROFILE = {
    "hostname": X86,
    "node_type": "cloud_server",
    "arch": "x86_64",
    "compute_class": "high",
    "memory_class": "high",
    "accelerator_type": "gpu_server",
    "preferred_workload": ["inference"],
    "risky_workload": ["sensor_ingest"],
}


SCENARIO_CONFIGS: dict[str, dict[str, Any]] = {
    "normal": {
        "stress_workers": 0,
        "stress_seconds": 0,
        "pressure_override": None,
        "mode": "none",
        "per_workflow_stress": False,
        "description": "no additional load",
    },
    "mild-burst": {
        "stress_workers": 3,
        "stress_seconds": 20,
        "pressure_override": "medium",
        "mode": "burst",
        "per_workflow_stress": True,
        "description": "3 CPU spin workers for 20s on Jetson",
    },
    "heavy-burst": {
        "stress_workers": 6,
        "stress_seconds": 20,
        "pressure_override": "high",
        "mode": "burst",
        "per_workflow_stress": True,
        "description": "6 CPU spin workers for 20s on Jetson",
    },
    "sustained-overload": {
        "stress_workers": 6,
        "stress_seconds": 180,
        "pressure_override": "high",
        "mode": "sustained",
        "per_workflow_stress": False,
        "description": "6 CPU spin workers for 180s on Jetson",
    },
}


def utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def parse_time_ms(value: str | None) -> int | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def http_json(
    method: str,
    url: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    encoded = None
    headers = {}
    if data is not None:
        encoded = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=encoded, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc


def kubectl(*args: str) -> str:
    result = subprocess.run(
        ["kubectl", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def capture_stage() -> dict[str, Any]:
    return {
        "stage_id": "capture",
        "stage_metadata": {
            "stage_type": "capture",
            "requires_accelerator": False,
            "compute_intensity": "low",
            "memory_intensity": "low",
            "latency_sensitivity": "high",
            "input_size_kb": 128,
            "output_size_kb": 512,
        },
        "image": IMAGE,
        "command": ["python", "-m", "vision_stage_runner.main"],
        "args": ["--stage", "capture"],
    }


def preprocess_stage() -> dict[str, Any]:
    return {
        "stage_id": "preprocess",
        "stage_metadata": {
            "stage_type": "preprocess",
            "requires_accelerator": False,
            "compute_intensity": "medium",
            "memory_intensity": "low",
            "latency_sensitivity": "high",
            "input_size_kb": 512,
            "output_size_kb": 1024,
        },
        "image": IMAGE,
        "command": ["python", "-m", "vision_stage_runner.main"],
        "args": ["--stage", "preprocess"],
    }


def inference_stage() -> dict[str, Any]:
    return {
        "stage_id": "inference",
        "stage_metadata": {
            "stage_type": "inference",
            "requires_accelerator": True,
            "compute_intensity": "high",
            "memory_intensity": "medium",
            "latency_sensitivity": "medium",
            "input_size_kb": 1024,
            "output_size_kb": 256,
        },
        "image": IMAGE,
        "command": ["python", "-m", "vision_stage_runner.main"],
        "args": ["--stage", "inference"],
    }


def execute_stage(
    workflow_id: str,
    workflow_type: str,
    stage: dict[str, Any],
    profiles: list[dict[str, Any]],
    current_placement: str | None = None,
) -> dict[str, Any]:
    payload = {
        "workflow_id": workflow_id,
        "workflow_type": workflow_type,
        "stage": stage,
        "node_profiles": profiles,
        "current_placement": current_placement,
    }
    return http_json("POST", f"{EXECUTOR_URL}/execute/stage", payload)["result"]


def decide_preprocess_target(
    workflow_id: str,
    node_states: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cost_model = http_json("GET", f"{AGGREGATOR_URL}/state/cost-model")
    payload = {
        "workflow_id": workflow_id,
        "workflow_type": "vision_pipeline",
        "stage_id": "preprocess",
        "stage_metadata": preprocess_stage()["stage_metadata"],
        "current_placement": JETSON,
        "node_profiles": [JETSON_PROFILE, X86_PROFILE],
        "node_states": node_states,
        "stage_cost_stats": cost_model.get("stage_cost_stats", []),
        "migration_cost_stats": cost_model.get("migration_cost_stats", []),
    }
    return http_json("POST", f"{PLACEMENT_URL}/placement/decide", payload)["decision"]


def get_workflow_state(workflow_id: str) -> dict[str, Any]:
    return http_json("GET", f"{EXECUTOR_URL}/workflow/{workflow_id}")["workflow"]


def get_node_state(hostname: str) -> dict[str, Any]:
    return http_json("GET", f"{AGGREGATOR_URL}/state/node/{hostname}")


def get_all_node_states() -> list[dict[str, Any]]:
    return http_json("GET", f"{AGGREGATOR_URL}/state/nodes")


def refresh_nodes() -> None:
    http_json("POST", f"{AGGREGATOR_URL}/internal/refresh")


def get_node_cpu_percent(hostname: str) -> int:
    output = kubectl("top", "node", hostname, "--no-headers")
    parts = output.split()
    if len(parts) < 3:
        raise RuntimeError(f"Unexpected kubectl top output: {output}")
    return int(parts[2].rstrip("%"))


def create_jetson_stress_pod(workers: int, duration_seconds: int | None = None) -> None:
    name = "jetson-burst-stress"
    delete_jetson_stress_pod()
    if duration_seconds and duration_seconds > 0:
        loop_cmd = (
            "end=$(( $(date +%s) + {duration_seconds} )); "
            "i=0; "
            "while [ \"$i\" -lt {workers} ]; do "
            "sh -c 'while [ $(date +%s) -lt '\"'$end'\"' ]; do :; done' & "
            "i=$((i+1)); "
            "done; "
            "wait"
        ).format(workers=workers, duration_seconds=duration_seconds)
    else:
        loop_cmd = (
            "i=0; while [ \"$i\" -lt {workers} ]; do "
            "sh -c 'while :; do :; done' & i=$((i+1)); "
            "done; wait"
        ).format(workers=workers)
    overrides = {
        "apiVersion": "v1",
        "spec": {
            "nodeSelector": {"kubernetes.io/hostname": JETSON},
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": name,
                    "image": "busybox:1.36",
                    "command": ["sh", "-c", loop_cmd],
                }
            ],
        },
    }
    kubectl(
        "run",
        name,
        "--image=busybox:1.36",
        "--restart=Never",
        f"--overrides={json.dumps(overrides, separators=(',', ':'))}",
    )


def delete_jetson_stress_pod() -> None:
    subprocess.run(
        [
            "kubectl",
            "delete",
            "pod",
            "jetson-burst-stress",
            "--ignore-not-found=true",
            "--wait=false",
            "--force",
            "--grace-period=0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def wait_for_jetson_cpu_percent(target_cpu_percent: int, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_state: dict[str, Any] | None = None
    while time.time() < deadline:
        refresh_nodes()
        state = get_node_state(JETSON)
        last_state = state
        if get_node_cpu_percent(JETSON) >= target_cpu_percent:
            return state
        time.sleep(5)
    raise RuntimeError(
        f"Jetson target CPU {target_cpu_percent}% not reached in time. Last state: {last_state}"
    )


def safe_get_node_cpu_percent(hostname: str) -> int | None:
    try:
        return get_node_cpu_percent(hostname)
    except Exception:
        return None


def current_node_states_with_pressure_override(
    pressure_override: str | None,
) -> list[dict[str, Any]]:
    states = get_all_node_states()
    compact_states: list[dict[str, Any]] = []
    for item in states:
        compact = {
            "hostname": item["hostname"],
            "compute_pressure": item["compute_pressure"],
            "memory_pressure": item["memory_pressure"],
            "network_pressure": item["network_pressure"],
            "node_health": item["node_health"],
        }
        if item["hostname"] == JETSON and pressure_override:
            compact["compute_pressure"] = pressure_override
            if pressure_override in {"medium", "high"}:
                compact["node_health"] = "degraded"
        compact_states.append(compact)
    return compact_states


@dataclass
class RunStressInfo:
    workers: int
    duration_seconds: int
    cpu_percent_before_capture: int | None
    cpu_percent_before_preprocess: int | None
    pressure_override: str | None
    mode: str


@dataclass
class WorkflowMetrics:
    workflow_id: str
    method: str
    scenario: str
    preprocess_target: str
    preprocess_action: str
    workflow_start_ms: int
    workflow_end_ms: int
    capture_latency_ms: int
    preprocess_latency_ms: int
    inference_latency_ms: int
    e2e_latency_ms: int
    migration_time_ms: int | None
    net_gain_ms: float | None
    decision_reason: str | None
    decision_timestamp_ms: int | None
    score_breakdown: dict[str, Any]
    stress: RunStressInfo


def collect_metrics(
    workflow_id: str,
    method: str,
    scenario: str,
    preprocess_target: str,
    preprocess_action: str,
    decision_reason: str | None,
    decision_timestamp_ms: int | None,
    score_breakdown: dict[str, Any],
    stress: RunStressInfo,
) -> WorkflowMetrics:
    workflow = get_workflow_state(workflow_id)
    stages = {item["stage_id"]: item for item in workflow["stages"]}

    capture_start = parse_time_ms(stages["capture"]["started_at"])
    capture_end = parse_time_ms(stages["capture"]["completed_at"])
    preprocess_start = parse_time_ms(stages["preprocess"]["started_at"])
    preprocess_end = parse_time_ms(stages["preprocess"]["completed_at"])
    inference_start = parse_time_ms(stages["inference"]["started_at"])
    inference_end = parse_time_ms(stages["inference"]["completed_at"])

    if None in {
        capture_start,
        capture_end,
        preprocess_start,
        preprocess_end,
        inference_start,
        inference_end,
    }:
        raise RuntimeError(f"Incomplete timestamps for workflow {workflow_id}: {workflow}")

    migration_time_ms = None
    if decision_timestamp_ms is not None and preprocess_target == X86:
        migration_time_ms = preprocess_start - decision_timestamp_ms

    return WorkflowMetrics(
        workflow_id=workflow_id,
        method=method,
        scenario=scenario,
        preprocess_target=preprocess_target,
        preprocess_action=preprocess_action,
        workflow_start_ms=capture_start,
        workflow_end_ms=inference_end,
        capture_latency_ms=capture_end - capture_start,
        preprocess_latency_ms=preprocess_end - preprocess_start,
        inference_latency_ms=inference_end - inference_start,
        e2e_latency_ms=inference_end - capture_start,
        migration_time_ms=migration_time_ms,
        net_gain_ms=score_breakdown.get("net_gain_ms"),
        decision_reason=decision_reason,
        decision_timestamp_ms=decision_timestamp_ms,
        score_breakdown=score_breakdown,
        stress=stress,
    )


def run_single_workflow(
    method: str,
    scenario: str,
    workflow_id: str,
    scenario_config: dict[str, Any],
) -> WorkflowMetrics:
    workflow_type = "vision_pipeline"
    cpu_before_capture = None
    cpu_before_preprocess = None

    if scenario_config["per_workflow_stress"]:
        create_jetson_stress_pod(
            scenario_config["stress_workers"],
            scenario_config["stress_seconds"],
        )
        time.sleep(3)
        refresh_nodes()
        cpu_before_capture = safe_get_node_cpu_percent(JETSON)

    execute_stage(workflow_id, workflow_type, capture_stage(), [RPI_PROFILE], RPI)

    decision_reason = None
    decision_timestamp_ms = None
    score_breakdown: dict[str, Any] = {}
    preprocess_action = "keep"
    if method == "static":
        preprocess_target = JETSON
        preprocess_profiles = [JETSON_PROFILE]
        cpu_before_preprocess = safe_get_node_cpu_percent(JETSON)
    elif method == "always-offload":
        preprocess_target = X86
        preprocess_profiles = [X86_PROFILE]
        preprocess_action = "offload_to_cloud"
        decision_reason = "always offload preprocess baseline"
        cpu_before_preprocess = safe_get_node_cpu_percent(JETSON)
        score_breakdown = {"selected_policy": "always_offload_baseline"}
    elif method == "threshold":
        cpu_before_preprocess = safe_get_node_cpu_percent(JETSON)
        if scenario_config["pressure_override"] == "high":
            preprocess_target = X86
            preprocess_profiles = [X86_PROFILE]
            preprocess_action = "offload_to_cloud"
            decision_reason = "threshold baseline offloaded preprocess on high pressure"
        else:
            preprocess_target = JETSON
            preprocess_profiles = [JETSON_PROFILE]
            preprocess_action = "keep"
            decision_reason = "threshold baseline kept preprocess on non-high pressure"
        score_breakdown = {
            "selected_policy": "threshold_baseline",
            "decision_margin_ms": 0,
            "net_gain_ms": None,
        }
    elif method in {"selective", "runtime"}:
        decision_timestamp_ms = utc_now_ms()
        cpu_before_preprocess = safe_get_node_cpu_percent(JETSON)
        node_states = (
            current_node_states_with_pressure_override(scenario_config["pressure_override"])
            if scenario_config["pressure_override"]
            else None
        )
        decision = decide_preprocess_target(workflow_id, node_states=node_states)
        preprocess_target = decision["target_node"]
        preprocess_action = decision["action_type"]
        decision_reason = decision["decision_reason"]
        score_breakdown = decision.get("score_breakdown", {})
        if preprocess_target == JETSON:
            preprocess_profiles = [JETSON_PROFILE]
        elif preprocess_target == X86:
            preprocess_profiles = [X86_PROFILE]
        else:
            raise RuntimeError(f"Unexpected runtime target: {decision}")
    else:
        raise RuntimeError(f"Unsupported method: {method}")

    execute_stage(
        workflow_id,
        workflow_type,
        preprocess_stage(),
        preprocess_profiles,
        JETSON,
    )
    execute_stage(workflow_id, workflow_type, inference_stage(), [X86_PROFILE], X86)

    if scenario_config["per_workflow_stress"]:
        delete_jetson_stress_pod()

    return collect_metrics(
        workflow_id=workflow_id,
        method=method,
        scenario=scenario,
        preprocess_target=preprocess_target,
        preprocess_action=preprocess_action,
        decision_reason=decision_reason,
        decision_timestamp_ms=decision_timestamp_ms,
        score_breakdown=score_breakdown,
        stress=RunStressInfo(
            workers=scenario_config["stress_workers"],
            duration_seconds=scenario_config["stress_seconds"],
            cpu_percent_before_capture=cpu_before_capture,
            cpu_percent_before_preprocess=cpu_before_preprocess,
            pressure_override=scenario_config["pressure_override"],
            mode=scenario_config["mode"],
        ),
    )


def summarize(metrics: list[WorkflowMetrics]) -> dict[str, Any]:
    if not metrics:
        return {}
    start_ms = min(item.workflow_start_ms for item in metrics)
    end_ms = max(item.workflow_end_ms for item in metrics)
    sorted_preprocess = sorted(item.preprocess_latency_ms for item in metrics)
    sorted_e2e = sorted(item.e2e_latency_ms for item in metrics)
    p95_index = max(0, int(len(sorted_e2e) * 0.95) - 1)
    measurement_window_ms = max(
        end_ms - start_ms,
        1,
    )
    migration_count = sum(1 for item in metrics if item.preprocess_target == X86)
    keep_count = sum(1 for item in metrics if item.preprocess_target == JETSON)
    unnecessary_migration_count = sum(
        1
        for item in metrics
        if item.preprocess_target == X86 and item.scenario in {"normal", "mild-burst"}
    )
    net_gain_values = [item.net_gain_ms for item in metrics if item.net_gain_ms is not None]
    return {
        "workflow_count": len(metrics),
        "capture_latency_mean_ms": round(
            sum(item.capture_latency_ms for item in metrics) / len(metrics), 3
        ),
        "preprocess_latency_mean_ms": round(
            sum(item.preprocess_latency_ms for item in metrics) / len(metrics), 3
        ),
        "inference_latency_mean_ms": round(
            sum(item.inference_latency_ms for item in metrics) / len(metrics), 3
        ),
        "e2e_latency_mean_ms": round(
            sum(item.e2e_latency_ms for item in metrics) / len(metrics), 3
        ),
        "preprocess_latency_p95_ms": sorted_preprocess[p95_index],
        "e2e_latency_p95_ms": sorted_e2e[p95_index],
        "throughput_jobs_per_s": round(len(metrics) / (measurement_window_ms / 1000.0), 6),
        "migration_time_mean_ms": round(
            sum(item.migration_time_ms for item in metrics if item.migration_time_ms is not None)
            / max(1, sum(1 for item in metrics if item.migration_time_ms is not None)),
            3,
        ),
        "migration_count": migration_count,
        "keep_count": keep_count,
        "unnecessary_migration_count": unnecessary_migration_count,
        "net_gain_mean_ms": round(sum(net_gain_values) / len(net_gain_values), 3)
        if net_gain_values
        else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run minimal mixed-device latency experiment")
    parser.add_argument(
        "--method",
        choices=["static", "always-offload", "threshold", "selective", "runtime"],
        required=True,
    )
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_CONFIGS),
        required=True,
    )
    parser.add_argument("--workflows", type=int, default=1)
    parser.add_argument("--results-dir", default="edge-orch/experiments/results")
    parser.add_argument("--stress-timeout", type=int, default=90)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    scenario_config = SCENARIO_CONFIGS[args.scenario]
    results_dir = Path(args.results_dir) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ensure_dir(results_dir)

    delete_jetson_stress_pod()
    refresh_nodes()
    stress_state = None
    if scenario_config["mode"] == "sustained":
        create_jetson_stress_pod(
            scenario_config["stress_workers"],
            scenario_config["stress_seconds"],
        )
        time.sleep(5)
        refresh_nodes()
        stress_state = get_node_state(JETSON)

    metrics: list[WorkflowMetrics] = []
    for index in range(args.workflows):
        workflow_id = f"wf-{args.method}-{args.scenario}-{int(time.time())}-{index:03d}"
        metrics.append(
            run_single_workflow(
                args.method,
                args.scenario,
                workflow_id,
                scenario_config,
            )
        )

    if scenario_config["mode"] in {"burst", "sustained"}:
        delete_jetson_stress_pod()

    summary = summarize(metrics)
    payload = {
        "method": args.method,
        "scenario": args.scenario,
        "scenario_config": scenario_config,
        "stress_state": stress_state,
        "summary": summary,
        "workflows": [
            {
                **item.__dict__,
                "stress": item.stress.__dict__,
            }
            for item in metrics
        ],
    }
    output_path = results_dir / f"{args.method}-{args.scenario}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
    print(json.dumps({"results_file": str(output_path), "summary": summary}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
