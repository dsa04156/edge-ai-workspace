from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from .models import NodeState

Decision = Literal["fit", "warning", "reject"]
Pressure = Literal["low", "medium", "high"]


DEFAULT_SERVICE_PROFILES = [
    {
        "service": "sensor-preprocess",
        "stage": "preprocess",
        "description": "센서 전처리/경량 feature 추출",
        "requirements": {
            "cpu_cores": 0.5,
            "memory_mb": 512,
            "gpu_required": False,
            "gpu_memory_mb": 0,
            "gpu_fraction": 0.0,
            "network_mbps": 20,
        },
        "preferences": {"node_type": ["edge_ai_device", "edge_device", "cloud_server"]},
    },
    {
        "service": "anomaly-detection",
        "stage": "inference",
        "description": "설비 이상탐지 AI inference",
        "requirements": {
            "cpu_cores": 2.0,
            "memory_mb": 4096,
            "gpu_required": True,
            "gpu_memory_mb": 4096,
            "gpu_fraction": 0.25,
            "network_mbps": 50,
        },
        "preferences": {"node_type": ["x86-gpu", "gpu_server", "edge_ai_device", "cloud_server"]},
    },
    {
        "service": "vision-inference",
        "stage": "inference",
        "description": "GPU 중심 영상/비전 inference",
        "requirements": {
            "cpu_cores": 2.0,
            "memory_mb": 8192,
            "gpu_required": True,
            "gpu_memory_mb": 6144,
            "gpu_fraction": 0.5,
            "network_mbps": 80,
        },
        "preferences": {"node_type": ["x86-gpu", "gpu_server", "cloud_server"]},
    },
]


def build_node_resource_profiles(nodes: list[NodeState]) -> list[dict]:
    generated_at = datetime.now(timezone.utc)
    profiles: list[dict] = []
    for node in nodes:
        metrics = node.raw_metrics or {}
        gpu_total = _number(metrics.get("gpu_memory_total_mib"))
        gpu_used = _number(metrics.get("gpu_memory_used_mib"))
        gpu_free = None
        if gpu_total is not None and gpu_used is not None:
            gpu_free = max(0.0, gpu_total - gpu_used)
        gpu_util = _number(metrics.get("gpu_utilization"))
        gpu_memory_ratio = _number(metrics.get("gpu_memory_usage_ratio"))
        gpu_available = gpu_util is not None or gpu_total is not None
        gpu_pressure = _pressure(max(gpu_util or 0.0, gpu_memory_ratio or 0.0), medium=0.60, high=0.85)
        if not gpu_available:
            gpu_pressure = "low"

        profiles.append(
            {
                "node": node.hostname,
                "instance": node.instance,
                "node_type": node.node_type,
                "status": node.node_health,
                "generated_at": generated_at.isoformat(),
                "cpu": {
                    "usage_ratio": round(_number(metrics.get("cpu_utilization")) or 0.0, 3),
                    "available_ratio": round(1 - (_number(metrics.get("cpu_utilization")) or 0.0), 3),
                    "load_average": round(_number(metrics.get("load_average")) or 0.0, 3),
                    "pressure": node.compute_pressure,
                },
                "memory": {
                    "usage_ratio": round(_number(metrics.get("memory_usage_ratio")) or 0.0, 3),
                    "available_ratio": round(1 - (_number(metrics.get("memory_usage_ratio")) or 0.0), 3),
                    "pressure": node.memory_pressure,
                },
                "gpu": {
                    "available": gpu_available,
                    "utilization_ratio": gpu_util,
                    "memory_used_mib": gpu_used,
                    "memory_total_mib": gpu_total,
                    "memory_free_mib": gpu_free,
                    "memory_usage_ratio": gpu_memory_ratio,
                    "temperature_celsius": _number(metrics.get("gpu_temperature_celsius")),
                    "power_watts": _number(metrics.get("gpu_power_watts")),
                    "pressure": gpu_pressure,
                },
                "network": {
                    "rx_mbps": round((_number(metrics.get("network_rx_rate")) or 0.0) * 8 / 1_000_000, 3),
                    "tx_mbps": round((_number(metrics.get("network_tx_rate")) or 0.0) * 8 / 1_000_000, 3),
                    "pressure": node.network_pressure,
                },
                "labels": _node_labels(node, gpu_available),
            }
        )
    return profiles


def build_placement_advice(node_profiles: list[dict], service_profiles: list[dict] | None = None) -> list[dict]:
    services = service_profiles or DEFAULT_SERVICE_PROFILES
    generated_at = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []
    for profile in services:
        candidates = [_score_candidate(node, profile) for node in node_profiles]
        candidates.sort(key=lambda item: item["score"], reverse=True)
        results.append(
            {
                "service": profile["service"],
                "stage": profile["stage"],
                "description": profile.get("description"),
                "requirements": profile.get("requirements", {}),
                "generated_at": generated_at,
                "candidates": candidates,
                "best_node": candidates[0]["node"] if candidates and candidates[0]["decision"] != "reject" else None,
            }
        )
    return results


def _score_candidate(node: dict, service_profile: dict) -> dict:
    requirements = service_profile.get("requirements", {})
    preferences = service_profile.get("preferences", {})
    score = 100
    reasons: list[str] = []
    decision: Decision = "fit"

    if node.get("status") == "unavailable":
        return {
            "node": node.get("node"),
            "node_type": node.get("node_type"),
            "decision": "reject",
            "score": 0,
            "reasons": ["node is unavailable"],
        }

    if node.get("status") == "degraded":
        score -= 20
        reasons.append("node health is degraded")

    for area in ("cpu", "memory", "network"):
        pressure = (node.get(area) or {}).get("pressure")
        if pressure == "high":
            score -= 25
            reasons.append(f"{area} pressure is high")
        elif pressure == "medium":
            score -= 10
            reasons.append(f"{area} pressure is medium")

    gpu = node.get("gpu") or {}
    if requirements.get("gpu_required") and not gpu.get("available"):
        return {
            "node": node.get("node"),
            "node_type": node.get("node_type"),
            "decision": "reject",
            "score": 0,
            "reasons": ["GPU is required but not available"],
        }

    required_gpu_memory = _number(requirements.get("gpu_memory_mb")) or 0.0
    gpu_free = _number(gpu.get("memory_free_mib"))
    if required_gpu_memory > 0 and gpu_free is not None and gpu_free < required_gpu_memory:
        return {
            "node": node.get("node"),
            "node_type": node.get("node_type"),
            "decision": "reject",
            "score": 0,
            "reasons": ["GPU memory is insufficient"],
        }
    if gpu.get("pressure") == "high":
        score -= 30
        reasons.append("GPU pressure is high")
    elif gpu.get("pressure") == "medium":
        score -= 15
        reasons.append("GPU pressure is medium")

    preferred_types = set(preferences.get("node_type") or [])
    if preferred_types and node.get("node_type") not in preferred_types:
        score -= 10
        reasons.append("node type is not preferred")

    if score < 50:
        decision = "warning"
    if score < 30:
        decision = "reject"
    if not reasons:
        reasons.append("resource pressure is normal")

    return {
        "node": node.get("node"),
        "node_type": node.get("node_type"),
        "decision": decision,
        "score": max(0, min(100, int(score))),
        "reasons": reasons,
    }


def _pressure(value: float, medium: float, high: float) -> Pressure:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def _number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _node_labels(node: NodeState, gpu_available: bool) -> list[str]:
    labels: list[str] = []
    if node.node_type:
        labels.append(node.node_type)
    if gpu_available:
        labels.append("gpu")
    if node.node_health != "unavailable":
        labels.append("schedulable-candidate")
    return labels
