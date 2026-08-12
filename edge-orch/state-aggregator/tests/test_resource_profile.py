from app.placement_recorder import InfluxResourceProfileRecorder
from app.resource_profile import (
    build_service_resource_profiles,
    parse_cpu_cores,
    parse_memory_mib,
    summarize_service_resource_profiles,
)


def _pod(
    name: str,
    workload: str,
    node: str,
    requests=None,
    limits=None,
    *,
    labels=None,
    ready=True,
    endpoint_ready=False,
):
    return {
        "namespace": "default",
        "name": name,
        "workload": workload,
        "node": node,
        "phase": "Running",
        "labels": labels or {},
        "ready": ready,
        "endpoint_ready": endpoint_ready,
        "containers": [
            {
                "name": "app",
                "requests": requests or {},
                "limits": limits or {},
            }
        ],
    }


def test_service_resource_profile_preserves_runtime_identity_and_readiness_evidence():
    profiles = build_service_resource_profiles(
        [
            _pod(
                "gpu-runtime-a",
                "gpu-runtime",
                "gpu-node",
                labels={
                    "edge-ai.io/augmentation-resource": "vd-x86-gpu-inference",
                    "edge-ai.io/binding-state": "free",
                },
                ready=True,
                endpoint_ready=True,
            )
        ]
    )

    container = profiles[0]["containers"][0]
    assert container["namespace"] == "default"
    assert container["labels"]["edge-ai.io/augmentation-resource"] == "vd-x86-gpu-inference"
    assert container["pod_ready"] is True
    assert container["endpoint_ready"] is True


def test_quantity_parsers_normalize_kubernetes_units():
    assert parse_cpu_cores("250m") == 0.25
    assert parse_cpu_cores("2") == 2.0
    assert parse_memory_mib("512Mi") == 512
    assert parse_memory_mib("1Gi") == 1024


def test_service_resource_profiles_aggregate_running_service_requirements_and_usage():
    profiles = build_service_resource_profiles(
        [
            _pod(
                "analyzer-a",
                "analyzer",
                "gpu-node",
                requests={"cpu": "500m", "memory": "512Mi"},
                limits={"cpu": "1", "memory": "1Gi", "nvidia.com/gpu": "1"},
            ),
            _pod(
                "analyzer-b",
                "analyzer",
                "gpu-node",
                requests={"cpu": "250m", "memory": "256Mi"},
                limits={"cpu": "500m", "memory": "512Mi"},
            ),
        ],
        [
            {"namespace": "default", "pod": "analyzer-a", "container": "app", "cpu_usage_cores": 0.31, "memory_working_set_mib": 300},
            {"namespace": "default", "pod": "analyzer-b", "container": "app", "cpu_usage_cores": 0.12, "memory_working_set_mib": 180},
        ],
    )

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["profile_type"] == "running_service_resource_requirements"
    assert profile["service"] == "analyzer"
    assert profile["pod_count"] == 2
    assert profile["resource_requirements"]["requests"]["cpu_cores"] == 0.75
    assert profile["resource_requirements"]["requests"]["memory_mib"] == 768
    assert profile["resource_requirements"]["limits"]["gpu_units"] == 1
    assert profile["current_usage"]["cpu_cores"] == 0.43
    assert profile["current_usage"]["memory_working_set_mib"] == 480
    assert profile["current_usage"]["usage_coverage_ratio"] == 1
    assert profile["requirements_declared"] is True


def test_service_resource_profiles_aggregate_window_usage_profile():
    profiles = build_service_resource_profiles(
        [
            _pod("analyzer-a", "analyzer", "gpu-node", requests={"cpu": "500m", "memory": "512Mi"}),
            _pod("analyzer-b", "analyzer", "gpu-node", requests={"cpu": "250m", "memory": "256Mi"}),
        ],
        [
            {
                "namespace": "default",
                "pod": "analyzer-a",
                "container": "app",
                "cpu_usage_cores": 0.31,
                "memory_working_set_mib": 300,
                "avg_cpu_usage_cores": 0.20,
                "max_cpu_usage_cores": 0.55,
                "p95_cpu_usage_cores": 0.49,
                "avg_memory_working_set_mib": 210,
                "max_memory_working_set_mib": 330,
                "p95_memory_working_set_mib": 300,
            },
            {
                "namespace": "default",
                "pod": "analyzer-b",
                "container": "app",
                "cpu_usage_cores": 0.12,
                "memory_working_set_mib": 180,
                "avg_cpu_usage_cores": 0.10,
                "max_cpu_usage_cores": 0.25,
                "p95_cpu_usage_cores": 0.22,
                "avg_memory_working_set_mib": 120,
                "max_memory_working_set_mib": 210,
                "p95_memory_working_set_mib": 190,
            },
        ],
        profile_window="10m",
    )

    usage_profile = profiles[0]["usage_profile"]
    assert usage_profile["window"] == "10m"
    assert usage_profile["avg_cpu_usage_cores"] == 0.3
    assert usage_profile["max_cpu_usage_cores"] == 0.8
    assert usage_profile["p95_cpu_usage_cores"] == 0.71
    assert usage_profile["avg_memory_working_set_mib"] == 330
    assert usage_profile["max_memory_working_set_mib"] == 540
    assert usage_profile["p95_memory_working_set_mib"] == 490
    assert usage_profile["sampled_container_count"] == 2
    assert usage_profile["usage_coverage_ratio"] == 1


def test_service_resource_profiles_mark_missing_requests_limits():
    profiles = build_service_resource_profiles([_pod("reader-a", "reader", "edge-node")])

    profile = profiles[0]
    assert profile["requirements_declared"] is False
    assert profile["request_coverage_ratio"] == 0
    assert profile["limit_coverage_ratio"] == 0
    assert "요구량 프로파일 보강" in profile["interpretation"]


def test_service_resource_summary_counts_profile_declaration_state_and_current_usage():
    profiles = build_service_resource_profiles(
        [
            _pod(
                "redis-a",
                "redis",
                "server-node",
                requests={"cpu": "100m", "memory": "128Mi"},
                limits={"cpu": "200m", "memory": "256Mi"},
            ),
            _pod("reader-a", "reader", "edge-node"),
        ],
        [
            {"namespace": "default", "pod": "redis-a", "container": "app", "cpu_usage_cores": 0.03, "memory_working_set_mib": 70},
        ],
    )
    summary = summarize_service_resource_profiles(profiles)

    assert summary["profile_count"] == 2
    assert summary["running_pod_count"] == 2
    assert summary["fully_declared_profile_count"] == 1
    assert summary["partially_declared_profile_count"] == 1
    assert summary["declared_request_cpu_cores"] == 0.1
    assert summary["current_cpu_usage_cores"] == 0.03
    assert summary["current_memory_working_set_mib"] == 70
    assert summary["usage_coverage_ratio"] == 0.5


def test_influx_recorder_builds_service_resource_profile_lines():
    profiles = build_service_resource_profiles(
        [
            _pod(
                "redis-a",
                "redis",
                "server-node",
                requests={"cpu": "100m", "memory": "128Mi"},
                limits={"cpu": "200m", "memory": "256Mi"},
            )
        ],
        [{"namespace": "default", "pod": "redis-a", "container": "app", "cpu_usage_cores": 0.03, "memory_working_set_mib": 70}],
    )
    recorder = InfluxResourceProfileRecorder("http://influx", "edgeai", "device_telemetry", "token")

    lines = recorder._service_profile_lines(profiles)

    assert any(line.startswith("service_resource_profile_events,") for line in lines)
    assert any("service=redis" in line for line in lines)
    assert any("request_cpu_cores=0.1" in line for line in lines)
    assert any("current_cpu_usage_cores=0.03" in line for line in lines)


def test_influx_recorder_writes_window_profile_summary_fields():
    profiles = build_service_resource_profiles(
        [_pod("redis-a", "redis", "server-node", requests={"cpu": "100m", "memory": "128Mi"})],
        [
            {
                "namespace": "default",
                "pod": "redis-a",
                "container": "app",
                "avg_cpu_usage_cores": 0.02,
                "max_cpu_usage_cores": 0.08,
                "p95_cpu_usage_cores": 0.06,
                "avg_memory_working_set_mib": 64,
                "max_memory_working_set_mib": 96,
                "p95_memory_working_set_mib": 88,
            }
        ],
        profile_window="10m",
    )
    recorder = InfluxResourceProfileRecorder("http://influx", "edgeai", "device_telemetry", "token")

    line = recorder._service_profile_lines(profiles)[0]

    assert 'profile_window="10m"' in line
    assert "avg_cpu_usage_cores=0.02" in line
    assert "max_cpu_usage_cores=0.08" in line
    assert "p95_cpu_usage_cores=0.06" in line
    assert "avg_memory_working_set_mib=64.0" in line
    assert "max_memory_working_set_mib=96.0" in line
    assert "p95_memory_working_set_mib=88.0" in line
