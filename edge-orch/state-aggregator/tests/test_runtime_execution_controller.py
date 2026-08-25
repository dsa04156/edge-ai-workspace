from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.config import Settings
from app.kube import KubeDeploymentError
from app.models import PlacementRequirements, PlacementSelectionResult, PlacementServiceProfileRef
from app.runtime_execution_controller import RuntimeExecutionApproval, RuntimeExecutionController, RuntimeExecutionStore
from app.runtime_execution_plan import build_runtime_execution_plan
from app.runtime_recommendation_models import RuntimeRecommendationDecision, RuntimeRecommendationDwell, RuntimeRecommendationMetrics, RuntimeRecommendationTarget


NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
DIGEST = "b" * 64
IMAGE = f"192.168.0.56:5000/sensor-anomaly-demo@sha256:{DIGEST}"


def _plan(action: str = "augment"):
    state = "AUGMENT_RECOMMENDED" if action == "augment" else "REPLACE_RECOMMENDED"
    placement = PlacementSelectionResult(
        generated_at=NOW,
        status="selected",
        service_profile=PlacementServiceProfileRef(namespace="edgex-edge", service="sensor-anomaly-demo", pod_count=1, request_coverage_ratio=1),
        requirements=PlacementRequirements(cpu_cores=0.5, memory_bytes=256 * 1024**2, memory_gb=0.268, architecture="arm64"),
        selected_node="server-b",
        selected_score=90,
    )
    decision = RuntimeRecommendationDecision(
        service_id="sensor-anomaly-demo", namespace="edgex-edge", workload_kind="Deployment", workload_name="sensor-anomaly-demo",
        current_nodes=["edge-a"], state=state, reason_codes=["sustained_pressure"],
        metrics=RuntimeRecommendationMetrics(desired_replicas=1, ready_replicas=1), dwell=RuntimeRecommendationDwell(),
        recommendation=RuntimeRecommendationTarget(action=action, selected_node="server-b", selected_score=90), placement=placement,
        observation_source="container-cadvisor", observation_scope="container", observed_at=NOW,
    )
    return build_runtime_execution_plan(decision, now=NOW, candidate_namespace="edge-ai-workloads")


def _source_deployment(*, with_env: bool = False):
    container = SimpleNamespace(
        image=IMAGE, ports=[], readiness_probe=None,
        env=[SimpleNamespace(name="UNSUPPORTED")] if with_env else [],
    )
    pod_spec = SimpleNamespace(containers=[container], init_containers=[], volumes=[])
    return SimpleNamespace(spec=SimpleNamespace(template=SimpleNamespace(spec=pod_spec)))


def _ready_deployment():
    return SimpleNamespace(status=SimpleNamespace(ready_replicas=1, available_replicas=1, conditions=[]))


def _ready_pod():
    return SimpleNamespace(
        metadata=SimpleNamespace(name="candidate-pod"), spec=SimpleNamespace(node_name="server-b"),
        status=SimpleNamespace(phase="Running", reason=None, message=None, conditions=[SimpleNamespace(type="Ready", status="True")], container_statuses=[]),
    )


class FakeKube:
    def __init__(self, *, create_failure: bool = False, ready_failure: bool = False, source_env: bool = False) -> None:
        self.create_failure = create_failure
        self.ready_failure = ready_failure
        self.source_env = source_env
        self.create_calls = 0
        self.created_body = None
        self.delete_calls = 0
        self.update_calls = 0

    async def read_deployment(self, namespace, name):
        if namespace == "edgex-edge":
            return _source_deployment(with_env=self.source_env)
        if self.ready_failure:
            return SimpleNamespace(status=SimpleNamespace(ready_replicas=0, available_replicas=0, conditions=[]))
        return _ready_deployment()

    async def deployment_exists(self, namespace, name):
        return False

    async def create_deployment(self, namespace, body):
        self.create_calls += 1
        if self.create_failure:
            raise KubeDeploymentError("deployment_create_failed", "failed")
        self.created_body = body

    async def list_deployment_pods(self, namespace, name):
        if self.ready_failure:
            waiting = SimpleNamespace(reason="ImagePullBackOff", message="pull failed")
            return [SimpleNamespace(
                metadata=SimpleNamespace(name="candidate-pod"), spec=SimpleNamespace(node_name="server-b"),
                status=SimpleNamespace(
                    phase="Pending", reason=None, message=None,
                    conditions=[SimpleNamespace(type="Ready", status="False")],
                    container_statuses=[SimpleNamespace(state=SimpleNamespace(waiting=waiting, terminated=None))],
                ),
            )]
        return [_ready_pod()]


def _controller(tmp_path, kube):
    settings = Settings(
        deployment_target_namespace="edge-ai-workloads",
        deployment_allowed_image_prefixes=("192.168.0.56:5000/sensor-anomaly-demo@sha256:",),
        deployment_ready_timeout_seconds=1,
        deployment_poll_interval_seconds=0.1,
    )
    store = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    return RuntimeExecutionController(settings, kube, store), store


def _approval(plan, approved: bool = True):
    return RuntimeExecutionApproval(plan_id=plan.plan_id, approved=approved, approved_by="operator-a")


def test_dry_run_is_read_only_and_exposes_supported_boundary(tmp_path) -> None:
    kube = FakeKube()
    controller, store = _controller(tmp_path, kube)
    result = asyncio.run(controller.dry_run(_plan()))

    assert result.status == "partial"
    assert result.first_unsupported_step_id == "distribute-traffic"
    assert [step.supported for step in result.steps] == [True, True, False]
    assert result.reason_codes == ["unsupported_step"]
    assert kube.create_calls == 0
    assert store.history(service_id=None, limit=10) == []


def test_dry_run_blocks_source_configuration_that_would_be_silently_dropped(tmp_path) -> None:
    kube = FakeKube(source_env=True)
    controller, store = _controller(tmp_path, kube)

    result = asyncio.run(controller.dry_run(_plan()))

    assert result.status == "blocked"
    assert "source_workload_contract_unsupported" in result.reason_codes
    assert kube.create_calls == 0
    assert store.history(service_id=None, limit=10) == []


def test_approved_execution_creates_and_verifies_once_then_blocks_unsupported(tmp_path) -> None:
    kube = FakeKube()
    controller, _ = _controller(tmp_path, kube)
    plan = _plan()
    first = asyncio.run(controller.execute(plan, _approval(plan)))
    repeated = asyncio.run(controller.execute(plan, _approval(plan)))

    assert first.status == "BLOCKED"
    assert first.candidate_created is True and first.candidate_ready is True
    assert first.existing_workload_preserved is True
    assert [step.status for step in first.steps] == ["SUCCEEDED", "SUCCEEDED", "BLOCKED"]
    assert first.steps[-1].reason_codes == ["unsupported_step"]
    assert repeated == first
    assert kube.create_calls == 1
    assert kube.delete_calls == 0 and kube.update_calls == 0
    assert kube.created_body["metadata"]["namespace"] == "edge-ai-workloads"
    assert kube.created_body["spec"]["template"]["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "server-b"}

    reopened = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    assert reopened.get(plan.plan_id) == first
    audit = reopened.audit(plan.plan_id, limit=50)
    assert [event.event_type for event in audit] == [
        "approval_received", "execution_started", "step_started", "step_succeeded",
        "step_started", "step_succeeded", "step_blocked", "execution_blocked",
    ]
    assert audit[3].status == "SUCCEEDED"


def test_create_failure_stops_later_steps_and_preserves_current(tmp_path) -> None:
    kube = FakeKube(create_failure=True)
    controller, _ = _controller(tmp_path, kube)
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "FAILED"
    assert result.steps[0].status == "FAILED"
    assert all(step.status == "BLOCKED" for step in result.steps[1:])
    assert all(step.reason_codes == ["previous_step_failed"] for step in result.steps[1:])
    assert result.existing_workload_preserved is True
    assert kube.delete_calls == 0 and kube.update_calls == 0


def test_ready_failure_stops_before_unsupported_steps(tmp_path) -> None:
    kube = FakeKube(ready_failure=True)
    controller, _ = _controller(tmp_path, kube)
    plan = _plan()

    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "FAILED"
    assert result.steps[0].status == "SUCCEEDED"
    assert result.steps[1].status == "FAILED"
    assert result.steps[1].reason_codes == ["image_pull_failed"]
    assert result.steps[2].status == "BLOCKED"
    assert result.steps[2].reason_codes == ["previous_step_failed"]
    assert result.existing_workload_preserved is True
    assert kube.create_calls == 1
    assert kube.delete_calls == 0 and kube.update_calls == 0


def test_replace_blocks_every_unsupported_step_without_mutation(tmp_path) -> None:
    kube = FakeKube()
    controller, _ = _controller(tmp_path, kube)
    plan = _plan("replace")

    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert [step.status for step in result.steps] == [
        "SUCCEEDED", "SUCCEEDED", "BLOCKED", "BLOCKED", "BLOCKED"
    ]
    assert result.steps[2].reason_codes == ["unsupported_step"]
    assert all(step.reason_codes == ["previous_step_blocked"] for step in result.steps[3:])
    assert kube.delete_calls == 0 and kube.update_calls == 0


def test_controller_rejects_missing_explicit_approval(tmp_path) -> None:
    controller, _ = _controller(tmp_path, FakeKube())
    plan = _plan()
    try:
        asyncio.run(controller.execute(plan, _approval(plan, approved=False)))
    except PermissionError as exc:
        assert "approval" in str(exc)
    else:
        raise AssertionError("execution without approval must fail")


def test_reserved_execution_is_blocked_instead_of_replayed_after_restart(tmp_path) -> None:
    controller, store = _controller(tmp_path, FakeKube())
    plan = _plan()
    approval = _approval(plan)
    record = asyncio.run(controller.execute(plan, approval))
    record.status = "PENDING"
    record.completed_at = None
    record.updated_at = NOW
    for step in record.steps:
        step.status = "PENDING"
        step.reason_codes = []
        step.completed_at = None
    store.save(record, event_type="test_interruption", actor="test")

    recovered_store = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    recovered = recovered_store.get(plan.plan_id)

    assert recovered is not None
    assert recovered.status == "BLOCKED"
    assert recovered.reason_codes == ["execution_interrupted"]
    assert all(step.status == "BLOCKED" for step in recovered.steps)
