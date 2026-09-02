from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.kube import KubeClient


def _container(
    name: str,
    *,
    requests: dict[str, str],
    limits: dict[str, str],
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        resources=SimpleNamespace(requests=requests, limits=limits),
    )


def test_runtime_workload_snapshot_reads_template_pods_and_failure_state() -> None:
    pod_spec = SimpleNamespace(
        containers=[
            _container(
                "inference",
                requests={"cpu": "500m", "memory": "256Mi"},
                limits={"cpu": "1", "memory": "512Mi"},
            )
        ],
        init_containers=[],
        overhead=None,
    )
    deployment = SimpleNamespace(
        spec=SimpleNamespace(
            replicas=1,
            template=SimpleNamespace(spec=pod_spec),
        ),
        status=SimpleNamespace(ready_replicas=0),
    )
    waiting = SimpleNamespace(reason="CrashLoopBackOff")
    container_status = SimpleNamespace(
        restart_count=3,
        state=SimpleNamespace(waiting=waiting, terminated=None),
    )
    pod = SimpleNamespace(
        spec=SimpleNamespace(node_name="edge-a"),
        status=SimpleNamespace(
            phase="Running",
            container_statuses=[container_status],
        ),
    )

    kube = object.__new__(KubeClient)
    kube.enabled = True
    kube.apps = SimpleNamespace(
        read_namespaced_deployment=lambda **_: deployment,
    )
    kube.v1 = SimpleNamespace(
        list_namespaced_pod=lambda **_: SimpleNamespace(items=[pod]),
    )

    snapshot = asyncio.run(
        kube.get_runtime_workload(
            namespace="factory",
            kind="Deployment",
            name="quality-ai",
            selector={"app": "quality-ai"},
        )
    )

    assert snapshot.observed is True
    assert snapshot.exists is True
    assert snapshot.current_nodes == ("edge-a",)
    assert snapshot.ready_replicas == 0
    assert snapshot.pod_restart_count == 3
    assert snapshot.pod_failure is True
    assert snapshot.reason_codes == (
        "workload_ready_replicas_insufficient",
        "pod_runtime_failure",
    )
    profile = snapshot.placement_profile
    assert profile["pod_count"] == 1
    assert profile["request_coverage_ratio"] == 1
    assert profile["resource_requirements"]["requests"] == {
        "cpu_cores": 0.5,
        "memory_mib": 256.0,
    }
    assert profile["resource_requirements"]["limits"] == {
        "cpu_cores": 1.0,
        "memory_mib": 512.0,
        "gpu_units": 0.0,
    }
