from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, service
from app.models import (
    NodeResourceUtilization,
    NodeSchedulingResource,
    PlacementSelectionRequest,
    SchedulingResourceAmounts,
)
from app.placement import select_placement
from app.service import PlacementProfileNotFound, StateAggregatorService


GIB = 1024**3


def _amounts(
    cpu: float,
    memory: int,
    accelerators: dict[str, float] | None = None,
) -> SchedulingResourceAmounts:
    return SchedulingResourceAmounts(
        cpu_cores=cpu,
        memory_bytes=memory,
        accelerator_units=accelerators or {},
    )


def _resource(
    node: str,
    *,
    available_cpu: float = 6,
    available_memory: int = 12 * GIB,
    architecture: str = "amd64",
    accelerator: str | None = None,
    accelerator_units: dict[str, float] | None = None,
    cpu_utilization: float | None = 0.2,
    memory_utilization: float | None = 0.3,
    schedulable: bool = True,
    resource_reasons: list[str] | None = None,
) -> NodeSchedulingResource:
    utilization = (
        NodeResourceUtilization(
            cpu_ratio=cpu_utilization,
            memory_ratio=memory_utilization,
            observed_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
        if cpu_utilization is not None or memory_utilization is not None
        else None
    )
    return NodeSchedulingResource(
        node=node,
        cpu_available=available_cpu,
        memory_available_gb=round(available_memory / 1_000_000_000, 3),
        accelerator=accelerator,
        health="healthy" if schedulable else "unavailable",
        schedulable=schedulable,
        reason_codes=resource_reasons or (["ready"] if schedulable else ["node_not_ready"]),
        architecture=architecture,
        node_type="cloud_server",
        allocatable=_amounts(8, 16 * GIB, {"nvidia.com/gpu": 2}),
        requested=_amounts(
            8 - available_cpu,
            16 * GIB - available_memory,
            {"nvidia.com/gpu": 2 - (accelerator_units or {}).get("nvidia.com/gpu", 0)},
        ),
        available=_amounts(
            available_cpu,
            available_memory,
            accelerator_units,
        ),
        utilization=utilization,
    )


def _profile(
    *,
    cpu: float = 2,
    memory_mib: float = 2048,
    gpu_units: float = 0,
    coverage: float = 1,
) -> dict:
    return {
        "namespace": "factory",
        "service": "quality-ai",
        "generated_at": "2026-08-25T00:00:00Z",
        "pod_count": 1,
        "request_coverage_ratio": coverage,
        "resource_requirements": {
            "requests": {"cpu_cores": cpu, "memory_mib": memory_mib},
            "limits": {"gpu_units": gpu_units},
            "missing": {
                "cpu_request_containers": 0 if coverage == 1 else 1,
                "memory_request_containers": 0 if coverage == 1 else 1,
            },
        },
    }


def _request(**updates) -> PlacementSelectionRequest:
    values = {
        "namespace": "factory",
        "service": "quality-ai",
        "architecture": "amd64",
    }
    values.update(updates)
    return PlacementSelectionRequest(**values)


def test_placement_filters_every_constraint_and_returns_rejection_reason_codes():
    request = _request(
        accelerator="nvidia-gpu",
        accelerator_units={"nvidia.com/gpu": 1},
    )
    resources = [
        _resource(
            "eligible",
            accelerator="RTX5060Ti",
            accelerator_units={"nvidia.com/gpu": 1},
        ),
        _resource(
            "cpu-low",
            available_cpu=1,
            accelerator="nvidia-gpu",
            accelerator_units={"nvidia.com/gpu": 1},
        ),
        _resource(
            "memory-low",
            available_memory=1 * GIB,
            accelerator="nvidia-gpu",
            accelerator_units={"nvidia.com/gpu": 1},
        ),
        _resource(
            "wrong-arch",
            architecture="arm64",
            accelerator="JetsonGPU",
            accelerator_units={"nvidia.com/gpu": 1},
        ),
        _resource("no-accelerator"),
        _resource(
            "gpu-full",
            accelerator="nvidia-gpu",
            accelerator_units={"nvidia.com/gpu": 0},
        ),
        _resource(
            "not-ready",
            schedulable=False,
            accelerator="nvidia-gpu",
            accelerator_units={"nvidia.com/gpu": 1},
        ),
        _resource(
            "metrics-missing",
            accelerator="nvidia-gpu",
            accelerator_units={"nvidia.com/gpu": 1},
            cpu_utilization=None,
            memory_utilization=None,
        ),
    ]

    result = select_placement(_profile(), resources, request)
    candidates = {candidate.node: candidate for candidate in result.candidates}

    assert result.status == "selected"
    assert result.selected_node == "eligible"
    assert candidates["eligible"].reason_codes == [
        "filter_passed",
        "selected_highest_score",
    ]
    assert "insufficient_cpu" in candidates["cpu-low"].reason_codes
    assert "insufficient_memory" in candidates["memory-low"].reason_codes
    assert "architecture_mismatch" in candidates["wrong-arch"].reason_codes
    assert "accelerator_unavailable" in candidates["no-accelerator"].reason_codes
    assert "accelerator_capacity_unreported" in candidates["no-accelerator"].reason_codes
    assert "insufficient_accelerator" in candidates["gpu-full"].reason_codes
    assert "node_not_schedulable" in candidates["not-ready"].reason_codes
    assert "node_not_ready" in candidates["not-ready"].reason_codes
    assert "utilization_unavailable" in candidates["metrics-missing"].reason_codes


def test_placement_scores_post_placement_headroom_and_current_utilization():
    resources = [
        _resource(
            "low-utilization",
            available_cpu=4,
            available_memory=8 * GIB,
            cpu_utilization=0.1,
            memory_utilization=0.1,
        ),
        _resource(
            "high-headroom",
            available_cpu=7,
            available_memory=15 * GIB,
            cpu_utilization=0.8,
            memory_utilization=0.8,
        ),
    ]

    result = select_placement(
        _profile(cpu=1, memory_mib=1024),
        resources,
        _request(),
    )
    candidates = {candidate.node: candidate for candidate in result.candidates}

    assert result.selected_node == "low-utilization"
    assert candidates["low-utilization"].score == 60.375
    assert candidates["high-headroom"].score == 56.75
    breakdown = candidates["low-utilization"].score_breakdown
    assert breakdown is not None
    assert breakdown.cpu_headroom_ratio == 0.375
    assert breakdown.memory_headroom_ratio == 0.4375
    assert breakdown.cpu_idle_ratio == 0.9
    assert breakdown.memory_idle_ratio == 0.9


def test_placement_breaks_equal_scores_by_node_name():
    result = select_placement(
        _profile(cpu=1, memory_mib=1024),
        [_resource("server-b"), _resource("server-a")],
        _request(),
    )

    assert result.selected_node == "server-a"
    assert [candidate.node for candidate in result.candidates] == [
        "server-a",
        "server-b",
    ]
    assert result.candidates[0].score == result.candidates[1].score
    assert result.candidates[1].reason_codes == [
        "filter_passed",
        "eligible_lower_score",
    ]


def test_placement_can_exclude_current_runtime_node_without_hiding_it():
    result = select_placement(
        _profile(cpu=1, memory_mib=1024),
        [_resource("current-node"), _resource("alternative-node")],
        _request(),
        excluded_nodes={"current-node"},
    )
    candidates = {candidate.node: candidate for candidate in result.candidates}

    assert result.status == "selected"
    assert result.selected_node == "alternative-node"
    assert candidates["current-node"].eligible is False
    assert candidates["current-node"].reason_codes == ["current_node_excluded"]


def test_placement_returns_no_fit_and_incomplete_profile_blocking_states():
    no_fit = select_placement(
        _profile(),
        [_resource("arm-node", architecture="arm64")],
        _request(),
    )
    blocked = select_placement(
        _profile(coverage=0.5),
        [_resource("server01")],
        _request(),
    )

    assert no_fit.status == "no_fit"
    assert no_fit.selected_node is None
    assert no_fit.reason_codes == ["no_eligible_nodes"]
    assert no_fit.candidates[0].reason_codes == ["architecture_mismatch"]
    assert blocked.status == "blocked"
    assert blocked.requirements is None
    assert blocked.reason_codes == ["service_profile_requests_incomplete"]
    assert blocked.candidates == []


def test_service_select_placement_uses_exact_namespace_and_service_profile(
    monkeypatch,
    tmp_path,
):
    aggregator = StateAggregatorService(Settings(data_dir=tmp_path))
    selected_profile = _profile(cpu=1, memory_mib=512)

    async def fake_profile_state(refresh=False):
        assert refresh is True
        return {
            "service_resource_profiles": [
                {**selected_profile, "namespace": "other"},
                selected_profile,
            ]
        }

    async def fake_resources():
        return [_resource("server01")]

    monkeypatch.setattr(aggregator, "get_resource_profile_state", fake_profile_state)
    monkeypatch.setattr(aggregator, "get_scheduling_resources", fake_resources)

    result = asyncio.run(
        aggregator.select_placement(_request(refresh_profile=True))
    )

    assert result.selected_node == "server01"
    assert result.requirements is not None
    assert result.requirements.cpu_cores == 1
    assert result.requirements.memory_bytes == 512 * 1024**2


def test_placement_api_returns_camel_case_result_and_profile_not_found(monkeypatch):
    selected = select_placement(
        _profile(cpu=1, memory_mib=512),
        [_resource("server01")],
        _request(),
    )

    async def fake_selected(request):
        return selected

    monkeypatch.setattr(service, "select_placement", fake_selected)
    with TestClient(app) as client:
        response = client.post(
            "/api/placements/select",
            json={
                "namespace": "factory",
                "service": "quality-ai",
                "architecture": "amd64",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "selected"
    assert payload["selectedNode"] == "server01"
    assert payload["selectedScore"] == selected.selected_score
    assert payload["requirements"]["cpuCores"] == 1
    assert payload["candidates"][0]["scoreBreakdown"]["total"] > 0

    async def not_found(request):
        raise PlacementProfileNotFound("missing")

    monkeypatch.setattr(service, "select_placement", not_found)
    with TestClient(app) as client:
        missing_response = client.post(
            "/api/placements/select",
            json={
                "namespace": "factory",
                "service": "missing",
                "architecture": "amd64",
            },
        )

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"]["code"] == "service_resource_profile_not_found"
