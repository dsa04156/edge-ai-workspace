from datetime import datetime, timezone

from app.models import NodeState
from app.placement_recorder import InfluxResourceProfileRecorder
from app.resource_profile import build_node_resource_profiles, build_placement_advice


def _node(hostname: str, gpu: bool = False, unavailable: bool = False) -> NodeState:
    metrics = {
        "up": 0.0 if unavailable else 1.0,
        "cpu_utilization": 0.25,
        "memory_usage_ratio": 0.40,
        "load_average": 0.8,
        "network_rx_rate": 1_000_000.0,
        "network_tx_rate": 1_000_000.0,
    }
    if gpu:
        metrics.update(
            {
                "gpu_utilization": 0.35,
                "gpu_memory_used_mib": 2048.0,
                "gpu_memory_total_mib": 8192.0,
                "gpu_memory_usage_ratio": 0.25,
            }
        )
    return NodeState(
        hostname=hostname,
        instance=f"{hostname}:9100",
        node_type="x86-gpu" if gpu else "edge_device",
        collected_at=datetime.now(timezone.utc),
        raw_metrics=metrics,
        compute_pressure="low",
        memory_pressure="low",
        network_pressure="low",
        node_health="unavailable" if unavailable else "healthy",
    )


def test_resource_profiles_turn_node_metrics_into_readable_profiles():
    profiles = build_node_resource_profiles([_node("gpu-node", gpu=True), _node("rpi-node")])

    gpu_profile = profiles[0]
    assert gpu_profile["node"] == "gpu-node"
    assert gpu_profile["gpu"]["available"] is True
    assert gpu_profile["gpu"]["memory_free_mib"] == 6144.0
    assert gpu_profile["network"]["rx_mbps"] == 8.0


def test_placement_advice_rejects_gpu_service_on_non_gpu_node():
    profiles = build_node_resource_profiles([_node("gpu-node", gpu=True), _node("rpi-node")])
    advice = build_placement_advice(profiles)
    anomaly = next(item for item in advice if item["service"] == "anomaly-detection")

    decisions = {candidate["node"]: candidate["decision"] for candidate in anomaly["candidates"]}
    assert decisions["gpu-node"] == "fit"
    assert decisions["rpi-node"] == "reject"
    assert anomaly["best_node"] == "gpu-node"


def test_influx_recorder_builds_resource_and_placement_lines():
    profiles = build_node_resource_profiles([_node("gpu-node", gpu=True)])
    advice = build_placement_advice(profiles)
    recorder = InfluxResourceProfileRecorder("http://influx", "edgeai", "device_telemetry", "token")

    lines = recorder._node_profile_lines(profiles) + recorder._placement_advice_lines(advice)

    assert any(line.startswith("resource_profile_events,") for line in lines)
    assert any(line.startswith("placement_advice_events,") for line in lines)
    assert any("node=gpu-node" in line for line in lines)
    assert any("decision=fit" in line for line in lines)
