from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import main
from app.models import PlacementSelectionResult, PlacementServiceProfileRef
from app.runtime_recommendation_models import (
    RuntimeRecommendationDecision,
    RuntimeRecommendationDwell,
    RuntimeRecommendationMetrics,
    RuntimeRecommendationTarget,
)


NOW = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)


def _decision() -> RuntimeRecommendationDecision:
    return RuntimeRecommendationDecision(
        service_id="sensor-anomaly-demo",
        namespace="edgex-edge",
        workload_kind="Deployment",
        workload_name="sensor-anomaly-demo",
        current_nodes=["edge-a"],
        state="AUGMENT_RECOMMENDED",
        reason_codes=["sustained_resource_and_service_pressure"],
        metrics=RuntimeRecommendationMetrics(desired_replicas=1, ready_replicas=1),
        dwell=RuntimeRecommendationDwell(),
        recommendation=RuntimeRecommendationTarget(
            action="augment",
            selected_node="server-b",
            selected_score=91,
        ),
        placement=PlacementSelectionResult(
            generated_at=NOW,
            status="selected",
            service_profile=PlacementServiceProfileRef(
                namespace="edgex-edge",
                service="sensor-anomaly-demo",
                pod_count=1,
                request_coverage_ratio=1,
            ),
            selected_node="server-b",
            selected_score=91,
        ),
        observation_source="container-cadvisor",
        observation_scope="container",
        observed_at=NOW,
    )


def test_execution_plan_api_is_read_only_and_uses_latest_decision(monkeypatch) -> None:
    decision = _decision()
    deploy_calls = []

    async def no_start() -> None:
        return None

    async def forbidden_deploy(*args, **kwargs):
        deploy_calls.append((args, kwargs))
        raise AssertionError("read-only execution plan must not deploy")

    monkeypatch.setattr(main.runtime_recommendation_monitor, "start", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "stop", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "latest", lambda _: decision)
    monkeypatch.setattr(main.service, "deploy_workload", forbidden_deploy)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/runtime-recommendations/sensor-anomaly-demo/execution-plan"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "planned"
    assert payload["mode"] == "read_only"
    assert payload["selectedNode"] == "server-b"
    assert [step["action"] for step in payload["steps"]] == [
        "create_candidate",
        "verify_ready",
        "distribute_traffic",
    ]
    assert deploy_calls == []


def test_execution_plan_api_preserves_service_and_observation_errors(monkeypatch) -> None:
    async def no_start() -> None:
        return None

    monkeypatch.setattr(main.runtime_recommendation_monitor, "start", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "stop", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "latest", lambda _: None)

    with TestClient(main.app) as client:
        unknown = client.get("/api/runtime-recommendations/unknown/execution-plan")
        unobserved = client.get(
            "/api/runtime-recommendations/sensor-anomaly-demo/execution-plan"
        )

    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "service_not_found"
    assert unobserved.status_code == 503
    assert unobserved.json()["detail"]["code"] == "runtime_recommendation_not_observed"
