from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import main
from app.runtime_recommendation_models import (
    RuntimeRecommendationDecision,
    RuntimeRecommendationDwell,
    RuntimeRecommendationHistoryEntry,
    RuntimeRecommendationMetrics,
    RuntimeRecommendationTarget,
)


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)


def _decision() -> RuntimeRecommendationDecision:
    return RuntimeRecommendationDecision(
        service_id="sensor-anomaly-demo",
        namespace="edgex-edge",
        workload_kind="Deployment",
        workload_name="sensor-anomaly-demo",
        current_nodes=["edge-a"],
        state="AUGMENT_RECOMMENDED",
        previous_state="OBSERVING",
        reason_codes=["sustained_resource_and_service_pressure"],
        metrics=RuntimeRecommendationMetrics(
            cpu_ratio=0.9,
            memory_ratio=0.5,
            latency_p95_ms=5000,
            backlog=2,
            throughput_per_second=0.6,
            desired_replicas=1,
            ready_replicas=1,
        ),
        dwell=RuntimeRecommendationDwell(
            resource_pressure_seconds=300,
            resource_required_seconds=300,
            service_pressure_seconds=180,
            service_required_seconds=180,
        ),
        recommendation=RuntimeRecommendationTarget(
            action="augment",
            selected_node="server-b",
            selected_score=91.0,
        ),
        observation_source="container-cadvisor",
        observation_scope="container",
        observed_at=NOW,
    )


def test_runtime_recommendation_current_list_and_history_api(monkeypatch) -> None:
    decision = _decision()

    async def no_start() -> None:
        return None

    monkeypatch.setattr(main.runtime_recommendation_monitor, "start", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "stop", no_start)
    monkeypatch.setattr(
        main.runtime_recommendation_monitor,
        "latest",
        lambda service_id: decision if service_id == "sensor-anomaly-demo" else None,
    )
    monkeypatch.setattr(
        main.runtime_recommendation_monitor,
        "latest_all",
        lambda: [decision],
    )
    monkeypatch.setattr(
        main.runtime_recommendation_monitor,
        "history",
        lambda service_id, limit: [
            RuntimeRecommendationHistoryEntry(
                sequence=1,
                recorded_at=NOW,
                previous_state="OBSERVING",
                state="AUGMENT_RECOMMENDED",
                decision=decision,
            )
        ],
    )

    with TestClient(main.app) as client:
        current = client.get("/api/runtime-recommendations/sensor-anomaly-demo")
        listing = client.get("/api/runtime-recommendations")
        history = client.get(
            "/api/runtime-recommendations/sensor-anomaly-demo/history?limit=10"
        )

    assert current.status_code == 200
    assert current.json()["state"] == "AUGMENT_RECOMMENDED"
    assert current.json()["recommendation"]["selectedNode"] == "server-b"
    assert listing.status_code == 200
    assert listing.json()["items"][0]["serviceId"] == "sensor-anomaly-demo"
    assert history.status_code == 200
    assert history.json()["items"][0]["previousState"] == "OBSERVING"


def test_runtime_recommendation_unknown_service_returns_404(monkeypatch) -> None:
    async def no_start() -> None:
        return None

    monkeypatch.setattr(main.runtime_recommendation_monitor, "start", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "stop", no_start)

    with TestClient(main.app) as client:
        response = client.get("/api/runtime-recommendations/not-registered")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "service_not_found"
