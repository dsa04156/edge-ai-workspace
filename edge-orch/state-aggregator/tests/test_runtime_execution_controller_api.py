from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import main
from app.candidate_validation import CandidateValidationResult
from app.models import PlacementRequirements, PlacementSelectionResult, PlacementServiceProfileRef
from app.runtime_execution_controller import RuntimeExecutionAuditEvent, RuntimeExecutionAuditLog, RuntimeExecutionDryRun, RuntimeExecutionRecord, RuntimeExecutionStepState
from app.runtime_execution_plan import build_runtime_execution_plan
from app.runtime_recommendation_models import RuntimeRecommendationDecision, RuntimeRecommendationDwell, RuntimeRecommendationMetrics, RuntimeRecommendationTarget


NOW = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)


def _decision():
    placement = PlacementSelectionResult(
        generated_at=NOW, status="selected",
        service_profile=PlacementServiceProfileRef(namespace="edgex-edge", service="sensor-anomaly-demo", pod_count=1, request_coverage_ratio=1),
        requirements=PlacementRequirements(cpu_cores=1, memory_bytes=1024**3, memory_gb=1.074, architecture="arm64"),
        selected_node="server-b", selected_score=90,
    )
    return RuntimeRecommendationDecision(
        service_id="sensor-anomaly-demo", namespace="edgex-edge", workload_kind="Deployment", workload_name="sensor-anomaly-demo",
        current_nodes=["edge-a"], state="AUGMENT_RECOMMENDED", reason_codes=["sustained_pressure"],
        metrics=RuntimeRecommendationMetrics(desired_replicas=1, ready_replicas=1), dwell=RuntimeRecommendationDwell(),
        recommendation=RuntimeRecommendationTarget(action="augment", selected_node="server-b", selected_score=90), placement=placement,
        observation_source="container-cadvisor", observation_scope="container", observed_at=NOW,
    )


class FakeController:
    def __init__(self, plan):
        self.plan = plan
        self.start_calls = 0
        self.dry_run_calls = 0

    async def dry_run(self, plan):
        self.dry_run_calls += 1
        return RuntimeExecutionDryRun(
            plan_id=plan.plan_id, service_id=plan.service_id, status="partial",
            reason_codes=["unsupported_step"], first_unsupported_step_id="distribute-traffic",
            steps=[], generated_at=NOW,
        )

    async def start(self, plan, approval):
        self.start_calls += 1
        record = RuntimeExecutionRecord(
            plan_id=plan.plan_id, service_id=plan.service_id, status="BLOCKED",
            approved_by=approval.approved_by, approved_at=NOW, started_at=NOW, completed_at=NOW,
            reason_codes=["unsupported_step"], candidate_created=True, candidate_ready=True,
            plan=plan,
            steps=[RuntimeExecutionStepState(step_id=s.step_id, action=s.action, status=("SUCCEEDED" if i < 3 else "BLOCKED")) for i, s in enumerate(plan.steps)],
            updated_at=NOW,
        )
        return record, True

    async def shutdown(self):
        return None


class FakeStore:
    def __init__(self, record):
        self.record = record

    def get(self, plan_id):
        return self.record if plan_id == self.record.plan_id else None

    def history(self, service_id, limit):
        return [self.record]

    def audit(self, plan_id, limit):
        return [RuntimeExecutionAuditEvent(sequence=1, plan_id=plan_id, event_type="approval_received", actor="operator-a", status="PENDING", recorded_at=NOW)]


def _setup(monkeypatch):
    async def no_start():
        return None
    decision = _decision()
    plan = build_runtime_execution_plan(decision, now=NOW, candidate_namespace="edge-ai-workloads")
    controller = FakeController(plan)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "start", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "stop", no_start)
    monkeypatch.setattr(main.runtime_recommendation_monitor, "latest", lambda _: decision)
    monkeypatch.setattr(main, "runtime_execution_controller", controller)
    return plan, controller


def test_execution_api_requires_enablement_token_and_explicit_approval(monkeypatch) -> None:
    plan, controller = _setup(monkeypatch)
    payload = {"planId": plan.plan_id, "approved": True, "approvedBy": "operator-a"}
    monkeypatch.setattr(main.settings, "execution_controller_enabled", False)
    with TestClient(main.app) as client:
        disabled = client.post("/api/runtime-recommendations/sensor-anomaly-demo/execution-plan/execute", json=payload)
    monkeypatch.setattr(main.settings, "execution_controller_enabled", True)
    monkeypatch.setattr(main.settings, "execution_management_token", "token")
    with TestClient(main.app) as client:
        unauthorized = client.post("/api/runtime-recommendations/sensor-anomaly-demo/execution-plan/execute", json=payload)
        unapproved = client.post(
            "/api/runtime-recommendations/sensor-anomaly-demo/execution-plan/execute",
            json={**payload, "approved": False}, headers={"X-Execution-Token": "token"},
        )
    assert disabled.status_code == 503
    assert unauthorized.status_code == 401
    assert unapproved.status_code == 403
    assert controller.start_calls == 0


def test_dry_run_and_approved_execution_api(monkeypatch) -> None:
    plan, controller = _setup(monkeypatch)
    monkeypatch.setattr(main.settings, "execution_controller_enabled", True)
    monkeypatch.setattr(main.settings, "execution_management_token", "token")
    with TestClient(main.app) as client:
        dry = client.post(
            "/api/runtime-recommendations/sensor-anomaly-demo/execution-plan/dry-run",
            json={"planId": plan.plan_id},
        )
        stale = client.post(
            "/api/runtime-recommendations/sensor-anomaly-demo/execution-plan/dry-run",
            json={"planId": "runtime-plan-0000000000000000"},
        )
        executed = client.post(
            "/api/runtime-recommendations/sensor-anomaly-demo/execution-plan/execute",
            json={"planId": plan.plan_id, "approved": True, "approvedBy": "operator-a"},
            headers={"X-Execution-Token": "token"},
        )
    assert dry.status_code == 200 and dry.json()["status"] == "partial"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "execution_plan_stale"
    assert executed.status_code == 202
    assert executed.json()["candidateReady"] is True
    assert executed.json()["existingWorkloadPreserved"] is True
    assert controller.dry_run_calls == 1 and controller.start_calls == 1


def test_execution_history_and_audit_api(monkeypatch) -> None:
    plan, controller = _setup(monkeypatch)
    record = RuntimeExecutionRecord(
        plan_id=plan.plan_id, service_id=plan.service_id, status="BLOCKED", approved_by="operator-a",
        approved_at=NOW, reason_codes=["unsupported_step"], plan=plan,
        steps=[RuntimeExecutionStepState(step_id=s.step_id, action=s.action, status="BLOCKED") for s in plan.steps], updated_at=NOW,
        validation=CandidateValidationResult(
            status="SUCCEEDED",
            reason_codes=["candidate_validation_succeeded"],
            started_at=NOW,
            completed_at=NOW,
            consecutive_successes=6,
            required_consecutive_successes=6,
            minimum_stable_seconds=30,
            observed_at=NOW,
        ),
    )
    monkeypatch.setattr(main, "runtime_execution_store", FakeStore(record))
    with TestClient(main.app) as client:
        current = client.get(f"/api/execution-plans/{plan.plan_id}")
        history = client.get("/api/executions?serviceId=sensor-anomaly-demo")
        audit = client.get(f"/api/execution-plans/{plan.plan_id}/audit")
    assert current.status_code == 200 and current.json()["planId"] == plan.plan_id
    assert current.json()["validation"]["status"] == "SUCCEEDED"
    assert history.status_code == 200 and len(history.json()["items"]) == 1
    assert audit.status_code == 200 and audit.json()["items"][0]["eventType"] == "approval_received"
