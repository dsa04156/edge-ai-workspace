from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.models import (
    NodeResourceUtilization,
    NodeSchedulingResource,
    PlacementSelectionRequest,
    SchedulingResourceAmounts,
)
from app.placement import select_placement
from app.runtime_recommendation import (
    RuntimeRecommendationEngine,
    RuntimeRecommendationSignals,
    RuntimeRecommendationStore,
)
from app.runtime_recommendation_models import RuntimeRecommendationPolicy


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
GIB = 1024**3


def _policy(**updates) -> RuntimeRecommendationPolicy:
    values = {
        "enabled": True,
        "architecture": "amd64",
        "cpu_high_ratio": 0.85,
        "cpu_recovery_ratio": 0.70,
        "memory_high_ratio": 0.85,
        "memory_recovery_ratio": 0.70,
        "latency_high_ms": 4000,
        "latency_recovery_ms": 2500,
        "throughput_floor_per_second": 0.8,
        "throughput_recovery_per_second": 1.0,
        "backlog_high": 1,
        "backlog_recovery": 0,
        "resource_dwell_seconds": 10,
        "service_dwell_seconds": 10,
        "replacement_dwell_seconds": 5,
        "recovery_dwell_seconds": 10,
        "cooldown_seconds": 30,
        "max_restart_count": 3,
    }
    values.update(updates)
    return RuntimeRecommendationPolicy(**values)


def _signals(**updates) -> RuntimeRecommendationSignals:
    values = {
        "service_id": "quality-ai",
        "namespace": "factory",
        "workload_name": "quality-ai",
        "current_nodes": ["edge-a"],
        "workload_observed": True,
        "workload_exists": True,
        "desired_replicas": 1,
        "ready_replicas": 1,
        "pod_restart_count": 0,
        "pod_failure": False,
        "node_failure": False,
        "input_state": "fresh",
        "input_valid": True,
        "model_state": "ready",
        "model_ready": True,
        "performance_valid": True,
        "resource_valid": True,
        "cpu_ratio": 0.90,
        "memory_ratio": 0.50,
        "latency_p95_ms": 5000,
        "backlog": 2,
        "throughput_per_second": 0.6,
        "observation_source": "container-cadvisor",
        "observation_scope": "container",
    }
    values.update(updates)
    return RuntimeRecommendationSignals(**values)


def _amounts(cpu: float, memory: int) -> SchedulingResourceAmounts:
    return SchedulingResourceAmounts(cpu_cores=cpu, memory_bytes=memory)


def _resource(node: str, *, cpu_ratio: float = 0.2) -> NodeSchedulingResource:
    available = _amounts(6, 12 * GIB)
    return NodeSchedulingResource(
        node=node,
        cpu_available=6,
        memory_available_gb=round(12 * GIB / 1_000_000_000, 3),
        health="healthy",
        schedulable=True,
        reason_codes=["ready"],
        architecture="amd64",
        node_type="cloud_server",
        allocatable=_amounts(8, 16 * GIB),
        requested=_amounts(2, 4 * GIB),
        available=available,
        utilization=NodeResourceUtilization(
            cpu_ratio=cpu_ratio,
            memory_ratio=0.2,
            observed_at=NOW,
        ),
    )


def _profile() -> dict:
    return {
        "namespace": "factory",
        "service": "quality-ai",
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
    }


async def _placement(current_nodes: set[str]):
    return select_placement(
        _profile(),
        [_resource("edge-a"), _resource("server-b", cpu_ratio=0.1)],
        PlacementSelectionRequest(
            namespace="factory",
            service="quality-ai",
            architecture="amd64",
        ),
        excluded_nodes=current_nodes,
    )


def test_engine_applies_dwell_hysteresis_and_cooldown(tmp_path) -> None:
    store = RuntimeRecommendationStore(tmp_path / "runtime.sqlite3")
    engine = RuntimeRecommendationEngine(store)
    policy = _policy()

    first = asyncio.run(engine.evaluate(_signals(), policy, _placement, now=NOW))
    recommended = asyncio.run(
        engine.evaluate(_signals(), policy, _placement, now=NOW + timedelta(seconds=10))
    )
    recovering = asyncio.run(
        engine.evaluate(
            _signals(
                cpu_ratio=0.60,
                latency_p95_ms=1000,
                backlog=0,
                throughput_per_second=1.2,
            ),
            policy,
            _placement,
            now=NOW + timedelta(seconds=11),
        )
    )
    normal = asyncio.run(
        engine.evaluate(
            _signals(
                cpu_ratio=0.60,
                latency_p95_ms=1000,
                backlog=0,
                throughput_per_second=1.2,
            ),
            policy,
            _placement,
            now=NOW + timedelta(seconds=21),
        )
    )
    cooling_down = asyncio.run(
        engine.evaluate(_signals(), policy, _placement, now=NOW + timedelta(seconds=22))
    )
    still_cooling = asyncio.run(
        engine.evaluate(_signals(), policy, _placement, now=NOW + timedelta(seconds=32))
    )
    recommended_again = asyncio.run(
        engine.evaluate(_signals(), policy, _placement, now=NOW + timedelta(seconds=41))
    )

    assert first.state == "OBSERVING"
    assert recommended.state == "AUGMENT_RECOMMENDED"
    assert recommended.recommendation.action == "augment"
    assert recommended.recommendation.selected_node == "server-b"
    assert recovering.state == "OBSERVING"
    assert "recovery_dwell_active" in recovering.reason_codes
    assert normal.state == "NORMAL"
    assert cooling_down.state == "OBSERVING"
    assert still_cooling.state == "OBSERVING"
    assert "recommendation_cooldown_active" in still_cooling.reason_codes
    assert recommended_again.state == "AUGMENT_RECOMMENDED"


def test_engine_prioritizes_runtime_failure_for_replacement(tmp_path) -> None:
    engine = RuntimeRecommendationEngine(
        RuntimeRecommendationStore(tmp_path / "runtime.sqlite3")
    )
    failed = _signals(
        ready_replicas=0,
        pod_failure=True,
        node_failure=True,
        cpu_ratio=0.2,
        latency_p95_ms=1000,
        backlog=0,
        throughput_per_second=1.2,
    )

    observing = asyncio.run(engine.evaluate(failed, _policy(), _placement, now=NOW))
    replacement = asyncio.run(
        engine.evaluate(failed, _policy(), _placement, now=NOW + timedelta(seconds=5))
    )

    assert observing.state == "OBSERVING"
    assert replacement.state == "REPLACE_RECOMMENDED"
    assert replacement.recommendation.action == "replace"
    assert replacement.recommendation.selected_node == "server-b"
    candidates = {item.node: item for item in replacement.placement.candidates}
    assert candidates["edge-a"].eligible is False
    assert candidates["edge-a"].reason_codes == ["current_node_excluded"]


def test_historical_restart_count_does_not_keep_a_ready_pod_failed(tmp_path) -> None:
    engine = RuntimeRecommendationEngine(
        RuntimeRecommendationStore(tmp_path / "runtime.sqlite3")
    )
    healthy = _signals(
        pod_restart_count=5,
        cpu_ratio=0.2,
        memory_ratio=0.2,
        latency_p95_ms=1000,
        backlog=0,
        throughput_per_second=1.2,
    )

    decision = asyncio.run(engine.evaluate(healthy, _policy(), _placement, now=NOW))

    assert decision.state == "NORMAL"
    assert decision.reason_codes == ["within_operating_envelope"]


def test_engine_blocks_input_and_model_failures_before_resource_reasoning(tmp_path) -> None:
    engine = RuntimeRecommendationEngine(
        RuntimeRecommendationStore(tmp_path / "runtime.sqlite3")
    )
    blocked = asyncio.run(
        engine.evaluate(
            _signals(
                input_state="stale",
                input_valid=False,
                model_state="warming_up",
                model_ready=False,
            ),
            _policy(),
            _placement,
            now=NOW,
        )
    )

    assert blocked.state == "BLOCKED"
    assert blocked.recommendation.action == "none"
    assert blocked.placement is None
    assert blocked.reason_codes == ["input_stale", "model_not_ready"]


def test_dwell_and_history_survive_engine_restart(tmp_path) -> None:
    database = tmp_path / "runtime.sqlite3"
    first_engine = RuntimeRecommendationEngine(RuntimeRecommendationStore(database))
    asyncio.run(first_engine.evaluate(_signals(), _policy(), _placement, now=NOW))

    restarted_engine = RuntimeRecommendationEngine(RuntimeRecommendationStore(database))
    decision = asyncio.run(
        restarted_engine.evaluate(
            _signals(),
            _policy(),
            _placement,
            now=NOW + timedelta(seconds=10),
        )
    )
    history = RuntimeRecommendationStore(database).history("quality-ai", limit=20)

    assert decision.state == "AUGMENT_RECOMMENDED"
    assert decision.dwell.resource_pressure_seconds == 10
    assert [item.state for item in history] == [
        "AUGMENT_RECOMMENDED",
        "OBSERVING",
    ]


def test_no_alternative_node_returns_blocked_with_all_candidate_reasons(tmp_path) -> None:
    engine = RuntimeRecommendationEngine(
        RuntimeRecommendationStore(tmp_path / "runtime.sqlite3")
    )

    async def no_fit(current_nodes: set[str]):
        return select_placement(
            _profile(),
            [_resource("edge-a")],
            PlacementSelectionRequest(
                namespace="factory",
                service="quality-ai",
                architecture="amd64",
            ),
            excluded_nodes=current_nodes,
        )

    asyncio.run(engine.evaluate(_signals(), _policy(), no_fit, now=NOW))
    decision = asyncio.run(
        engine.evaluate(
            _signals(),
            _policy(),
            no_fit,
            now=NOW + timedelta(seconds=10),
        )
    )

    assert decision.state == "BLOCKED"
    assert "no_eligible_alternative_node" in decision.reason_codes
    assert decision.placement is not None
    assert decision.placement.status == "no_fit"
    assert decision.placement.candidates[0].reason_codes == ["current_node_excluded"]
