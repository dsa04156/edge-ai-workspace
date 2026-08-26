from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.models import (
    NodeResourceUtilization,
    NodeSchedulingResource,
    SchedulingResourceAmounts,
)
from app.runtime_recommendation import RuntimeWorkloadSnapshot
from app.runtime_recommendation_monitor import (
    RuntimeRecommendationMonitor,
    RuntimeServiceObservation,
    _fresh,
)
from app.service_catalog import ServiceCatalog


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
CATALOG_PATH = Path(__file__).resolve().parents[1] / "app/config/service_catalog.json"


class StubKube:
    async def get_runtime_workload(self, **_: object) -> RuntimeWorkloadSnapshot:
        return RuntimeWorkloadSnapshot(
            namespace="edgex-edge",
            kind="Deployment",
            name="sensor-anomaly-demo",
            observed=True,
            exists=True,
            desired_replicas=1,
            ready_replicas=1,
            current_nodes=("edge-a",),
            placement_profile={
                "namespace": "edgex-edge",
                "service": "sensor-anomaly-demo",
                "generated_at": NOW.isoformat(),
                "pod_count": 1,
                "request_coverage_ratio": 1,
                "resource_requirements": {
                    "requests": {"cpu_cores": 1, "memory_mib": 512},
                    "limits": {"gpu_units": 0},
                    "missing": {
                        "cpu_request_containers": 0,
                        "memory_request_containers": 0,
                    },
                },
            },
        )


class StubAggregator:
    def __init__(self) -> None:
        self.kube = StubKube()

    async def get_resource_profile_state(self, refresh: bool = False) -> dict:
        assert refresh is True
        return {"service_resource_profiles": []}

    async def get_scheduling_resources(self) -> list[NodeSchedulingResource]:
        return [_resource("edge-a", 0.4), _resource("server-b", 0.1)]


class StubAdapter:
    def __init__(self, *, stale: bool = False) -> None:
        self.stale = stale

    async def observe(self, *_: object, **__: object) -> RuntimeServiceObservation:
        return RuntimeServiceObservation(
            input_state="stale" if self.stale else "fresh",
            input_valid=not self.stale,
            model_state="ready",
            model_ready=True,
            performance_valid=True,
            resource_valid=True,
            cpu_ratio=0.9,
            memory_ratio=0.5,
            latency_p95_ms=5000,
            backlog=2,
            throughput_per_second=0.6,
            source="container-cadvisor",
            scope="container",
        )


def _resource(node: str, cpu_ratio: float) -> NodeSchedulingResource:
    gib = 1024**3
    available = SchedulingResourceAmounts(cpu_cores=6, memory_bytes=12 * gib)
    return NodeSchedulingResource(
        node=node,
        cpu_available=6,
        memory_available_gb=round(12 * gib / 1_000_000_000, 3),
        health="healthy",
        schedulable=True,
        reason_codes=["ready"],
        architecture="arm64",
        node_type="edge_ai_device",
        allocatable=SchedulingResourceAmounts(cpu_cores=8, memory_bytes=16 * gib),
        requested=SchedulingResourceAmounts(cpu_cores=2, memory_bytes=4 * gib),
        available=available,
        utilization=NodeResourceUtilization(
            cpu_ratio=cpu_ratio,
            memory_ratio=0.2,
            observed_at=NOW,
        ),
    )


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path,
        runtime_recommendation_database_path=None,
        runtime_recommendation_history_limit=100,
        runtime_recommendation_enabled=True,
        runtime_recommendation_poll_interval_seconds=15,
    )


def _catalog_with_zero_dwell() -> ServiceCatalog:
    catalog = ServiceCatalog.load(CATALOG_PATH)
    descriptor = catalog.require("sensor-anomaly-demo")
    descriptor.runtime_recommendation = descriptor.runtime_recommendation.model_copy(
        update={
            "resource_dwell_seconds": 0,
            "service_dwell_seconds": 0,
            "replacement_dwell_seconds": 0,
            "cooldown_seconds": 0,
        }
    )
    return catalog


def test_monitor_combines_runtime_signals_and_reuses_placement_engine(tmp_path) -> None:
    monitor = RuntimeRecommendationMonitor(
        _settings(tmp_path),
        StubAggregator(),
        _catalog_with_zero_dwell(),
        {"sensor-anomaly-v1": StubAdapter()},
    )

    decisions = asyncio.run(monitor.evaluate_all(now=NOW))

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.state == "AUGMENT_RECOMMENDED"
    assert decision.recommendation.selected_node == "server-b"
    candidates = {candidate.node: candidate for candidate in decision.placement.candidates}
    assert candidates["edge-a"].reason_codes == ["current_node_excluded"]
    assert monitor.latest("sensor-anomaly-demo") == decision


def test_monitor_blocks_stale_input_without_calling_it_resource_pressure(tmp_path) -> None:
    monitor = RuntimeRecommendationMonitor(
        _settings(tmp_path),
        StubAggregator(),
        _catalog_with_zero_dwell(),
        {"sensor-anomaly-v1": StubAdapter(stale=True)},
    )

    decision = asyncio.run(monitor.evaluate_all(now=NOW))[0]

    assert decision.state == "BLOCKED"
    assert decision.reason_codes == ["input_stale"]
    assert decision.placement is None


def test_freshness_tolerates_bounded_observation_clock_skew() -> None:
    assert _fresh("2026-08-25T00:00:04Z", NOW, 60) is True
    assert _fresh("2026-08-25T00:00:06Z", NOW, 60) is False
