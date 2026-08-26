from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.candidate_workload_template import CandidateTemplateCatalog
from app.candidate_validation import CandidateValidationResult, CandidateValidationWorkloadObservation
from app.config import Settings
from app.execution_ownership import LeaseSnapshot, RuntimeExecutionOwnership
from app.kube import KubeDeploymentError
from app.models import (
    PlacementRequirements,
    PlacementSelectionResult,
    PlacementServiceProfileRef,
    SchedulingResourceAmounts,
)
from app.resource_pool import KubernetesNodeResourceSnapshot
from app.runtime_execution_controller import (
    RuntimeExecutionApproval,
    RuntimeExecutionController,
    RuntimeExecutionStore,
)
from app.runtime_execution_plan import build_runtime_execution_plan
from app.traffic_routing import (
    RoutingContractCatalog,
    RoutingSnapshot,
    RuntimeExecutionRouting,
    TrafficRoutingContract,
    TrafficRoutingError,
)
from app.runtime_recommendation_models import (
    RuntimeRecommendationDecision,
    RuntimeRecommendationDwell,
    RuntimeRecommendationMetrics,
    RuntimeRecommendationTarget,
)


NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
CATALOG_PATH = Path(__file__).resolve().parents[1] / "app/config/candidate_workload_templates.json"
IMAGE = (
    "192.168.0.56:5000/sensor-anomaly-demo@sha256:"
    "988854fa33e86d00d7b17e36362fbc99b263b8af8956a623b579851c81a11bca"
)


def _template():
    catalog = CandidateTemplateCatalog.load(CATALOG_PATH)
    result, error = catalog.resolve("sensor-anomaly-demo")
    assert error is None and result is not None
    return result


def _plan(action: str = "augment", *, service_id: str = "sensor-anomaly-demo"):
    state = "AUGMENT_RECOMMENDED" if action == "augment" else "REPLACE_RECOMMENDED"
    placement = PlacementSelectionResult(
        generated_at=NOW,
        status="selected",
        service_profile=PlacementServiceProfileRef(
            namespace="edgex-edge",
            service=service_id,
            pod_count=1,
            request_coverage_ratio=1,
        ),
        requirements=PlacementRequirements(
            cpu_cores=0.025,
            memory_bytes=64 * 1024**2,
            memory_gb=0.067,
            architecture="arm64",
        ),
        selected_node="server-b",
        selected_score=90,
    )
    decision = RuntimeRecommendationDecision(
        service_id=service_id,
        namespace="edgex-edge",
        workload_kind="Deployment",
        workload_name=service_id,
        current_nodes=["edge-a"],
        state=state,
        reason_codes=["sustained_pressure"],
        metrics=RuntimeRecommendationMetrics(desired_replicas=1, ready_replicas=1),
        dwell=RuntimeRecommendationDwell(),
        recommendation=RuntimeRecommendationTarget(
            action=action,
            selected_node="server-b",
            selected_score=90,
        ),
        placement=placement,
        observation_source="container-cadvisor",
        observation_scope="container",
        observed_at=NOW,
    )
    return build_runtime_execution_plan(
        decision,
        now=NOW,
        candidate_namespace="edge-ai-workloads",
    )


def _source_deployment(*, mismatch: bool = False):
    approved = _template()
    container = approved.pod_template.container.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    if mismatch:
        container["env"][0]["value"] = "changed-outside-approved-template"
    pod = approved.pod_template.model_dump(by_alias=True, exclude_none=True)
    pod.pop("labels")
    pod.pop("annotations")
    pod["containers"] = [container]
    pod.pop("container")
    pod["volumes"] = [
        {"name": "tmp", "emptyDir": {}},
        {
            "name": "state",
            "persistentVolumeClaim": {"claimName": "sensor-anomaly-demo-state"},
        },
    ]
    return {
        "metadata": {"name": "sensor-anomaly-demo", "namespace": "edgex-edge"},
        "spec": {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "template": {
                "metadata": {
                    "labels": {"edge-ai.io/deployment": "sensor-anomaly-demo"}
                },
                "spec": pod,
            },
        },
    }


def _ready_deployment():
    return SimpleNamespace(
        status=SimpleNamespace(ready_replicas=1, available_replicas=1, conditions=[])
    )


def _ready_pod():
    return SimpleNamespace(
        metadata=SimpleNamespace(name="candidate-pod"),
        spec=SimpleNamespace(node_name="server-b"),
        status=SimpleNamespace(
            phase="Running",
            reason=None,
            message=None,
            conditions=[SimpleNamespace(type="Ready", status="True")],
            container_statuses=[],
        ),
    )


def _target_snapshot():
    return KubernetesNodeResourceSnapshot(
        node="server-b",
        ready=True,
        unschedulable=False,
        architecture="arm64",
        node_type="server",
        labels={"kubernetes.io/arch": "arm64"},
        allocatable=SchedulingResourceAmounts(
            cpu_cores=8,
            memory_bytes=16 * 1024**3,
            accelerator_units={},
        ),
        requested=SchedulingResourceAmounts(
            cpu_cores=1,
            memory_bytes=1024**3,
            accelerator_units={},
        ),
    )


class FakeKube:
    def __init__(
        self,
        *,
        create_failure: bool = False,
        ready_failure: bool = False,
        source_mismatch: bool = False,
        service_selector: dict[str, str] | None = None,
        storage_class_failure: bool = False,
        target_ready: bool = True,
    ) -> None:
        self.create_failure = create_failure
        self.ready_failure = ready_failure
        self.source_mismatch = source_mismatch
        self.service_selector = service_selector or {
            "app.kubernetes.io/name": "sensor-anomaly-demo"
        }
        self.storage_class_failure = storage_class_failure
        self.target_ready = target_ready
        self.create_calls = 0
        self.created_body = None
        self.delete_calls = 0
        self.update_calls = 0
        self.source = _source_deployment(mismatch=source_mismatch)
        self.source_before = deepcopy(self.source)

    async def read_deployment(self, namespace, name):
        if namespace == "edgex-edge":
            return self.source
        if self.ready_failure:
            return SimpleNamespace(
                status=SimpleNamespace(
                    ready_replicas=0,
                    available_replicas=0,
                    conditions=[],
                )
            )
        return _ready_deployment()

    async def read_service(self, namespace, name):
        return {
            "spec": {
                "selector": self.service_selector,
                "ports": [{"name": "http", "port": 8080, "targetPort": "http"}],
            }
        }

    async def read_persistent_volume_claim(self, namespace, name):
        return {
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "local-path",
            }
        }

    async def read_storage_class(self, name):
        if self.storage_class_failure:
            raise KubeDeploymentError("storage_class_unavailable", "missing")
        return {"metadata": {"name": name}}

    async def get_scheduling_resource_snapshots(self):
        snapshot = _target_snapshot()
        if not self.target_ready:
            snapshot = KubernetesNodeResourceSnapshot(
                **{**snapshot.__dict__, "ready": False}
            )
        return [snapshot]

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
            return [
                SimpleNamespace(
                    metadata=SimpleNamespace(name="candidate-pod"),
                    spec=SimpleNamespace(node_name="server-b"),
                    status=SimpleNamespace(
                        phase="Pending",
                        reason=None,
                        message=None,
                        conditions=[SimpleNamespace(type="Ready", status="False")],
                        container_statuses=[
                            SimpleNamespace(
                                state=SimpleNamespace(waiting=waiting, terminated=None)
                            )
                        ],
                    ),
                )
            ]
        return [_ready_pod()]


class FakeValidationEngine:
    def __init__(self, *, status="SUCCEEDED", reasons=None):
        self.status = status
        self.reasons = reasons or (
            ["candidate_validation_succeeded"]
            if status == "SUCCEEDED"
            else ["candidate_input_unavailable"]
        )
        self.calls = 0

    async def validate(self, **kwargs):
        self.calls += 1
        result = CandidateValidationResult(
            status=self.status,
            reason_codes=self.reasons,
            started_at=NOW,
            completed_at=NOW,
            consecutive_successes=6 if self.status == "SUCCEEDED" else 0,
            required_consecutive_successes=6,
            minimum_stable_seconds=30,
            observed_at=NOW,
        )
        observer = kwargs.get("observer")
        if observer is not None:
            await observer(result)
        return result


class BlockingValidationEngine(FakeValidationEngine):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def validate(self, **kwargs):
        self.started.set()
        await self.release.wait()
        return await super().validate(**kwargs)


class FakeOwnershipEngine:
    def __init__(self, *, handoff_failure: str | None = None, rollback_failure: str | None = None):
        self.handoff_failure = handoff_failure
        self.rollback_failure = rollback_failure
        self.handoff_calls = 0
        self.rollback_calls = 0

    async def handoff(self, *, contract, candidate_name, observer=None):
        from app.execution_ownership import ExecutionOwnershipError

        self.handoff_calls += 1
        before = LeaseSnapshot(
            namespace="edgex-edge",
            name="sensor-anomaly-demo-execution",
            holder_identity="sensor-anomaly-demo",
            lease_duration_seconds=15,
            acquire_time=NOW,
            renew_time=NOW,
            lease_transitions=1,
            resource_version="1",
            observed_at=NOW,
        )
        ownership = RuntimeExecutionOwnership(
            lease_namespace="edgex-edge",
            lease_name="sensor-anomaly-demo-execution",
            source_holder="sensor-anomaly-demo",
            candidate_holder=candidate_name,
            active_owner="source",
            before=before,
        )
        if observer is not None:
            await observer(ownership)
        if self.handoff_failure:
            ownership.active_owner = "candidate"
            ownership.after = before.model_copy(
                update={"holder_identity": candidate_name, "resource_version": "2"}
            )
            raise ExecutionOwnershipError(self.handoff_failure)
        after = before.model_copy(
            update={
                "holder_identity": candidate_name,
                "resource_version": "2",
                "lease_transitions": 2,
            }
        )
        ownership.active_owner = "candidate"
        ownership.after = after
        ownership.handed_off_at = NOW
        return ownership

    async def rollback(self, *, contract, ownership):
        from app.execution_ownership import ExecutionOwnershipError

        self.rollback_calls += 1
        if self.rollback_failure:
            raise ExecutionOwnershipError(self.rollback_failure)
        ownership.active_owner = "source"
        ownership.after = ownership.before.model_copy(update={"resource_version": "3"})
        ownership.rolled_back_at = NOW
        return ownership


def _controller(tmp_path, kube, *, catalog=None, validation_engine=None, routing_catalog=None, routing_engine=None, ownership_engine=None):
    settings = Settings(
        deployment_target_namespace="edge-ai-workloads",
        deployment_allowed_image_prefixes=(
            "192.168.0.56:5000/sensor-anomaly-demo@sha256:",
        ),
        deployment_ready_timeout_seconds=1,
        deployment_poll_interval_seconds=0.1,
        candidate_template_catalog_path=CATALOG_PATH,
    )
    store = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    return RuntimeExecutionController(
        settings,
        kube,
        store,
        catalog,
        validation_engine=validation_engine or FakeValidationEngine(),
        routing_catalog=routing_catalog,
        routing_engine=routing_engine,
        ownership_engine=ownership_engine or FakeOwnershipEngine(),
    ), store


def _approval(plan, approved: bool = True):
    return RuntimeExecutionApproval(
        plan_id=plan.plan_id,
        approved=approved,
        approved_by="operator-a",
    )


def test_approved_template_loads_with_fresh_state_contract() -> None:
    approved = _template()

    assert approved.service_id == "sensor-anomaly-demo"
    assert approved.pod_template.container.image == IMAGE
    assert approved.state_policy.type == "fresh_state"
    assert approved.state_policy.candidate_storage.type == "ephemeral"
    assert approved.state_policy.candidate_storage.reuse_source_pvc is False


def test_dry_run_is_read_only_and_exposes_supported_boundary(tmp_path) -> None:
    kube = FakeKube()
    controller, store = _controller(tmp_path, kube)
    result = asyncio.run(controller.dry_run(_plan()))

    assert result.status == "partial"
    assert result.first_unsupported_step_id == "distribute-traffic"
    assert [step.supported for step in result.steps] == [
        True,
        True,
        True,
        True,
        True,
        False,
        True,
    ]
    assert result.reason_codes == ["unsupported_step"]
    assert kube.create_calls == 0
    assert store.history(service_id=None, limit=10) == []


def test_template_missing_service_is_blocked_before_create(tmp_path) -> None:
    kube = FakeKube()
    controller, _ = _controller(
        tmp_path,
        kube,
        catalog=CandidateTemplateCatalog({}, {}),
    )
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["candidate_template_not_found"]
    assert kube.create_calls == 0


def test_invalid_template_contract_is_blocked_before_create(tmp_path) -> None:
    catalog_path = tmp_path / "invalid-catalog.json"
    catalog_path.write_text('{"templates":[{"serviceId":"sensor-anomaly-demo"}]}')
    catalog = CandidateTemplateCatalog.load(catalog_path)
    kube = FakeKube()
    controller, _ = _controller(tmp_path, kube, catalog=catalog)
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["candidate_contract_invalid"]
    assert kube.create_calls == 0


def test_source_template_mismatch_is_blocked_before_create(tmp_path) -> None:
    kube = FakeKube(source_mismatch=True)
    controller, _ = _controller(tmp_path, kube)
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["candidate_template_mismatch"]
    assert kube.create_calls == 0


def test_rwo_local_path_source_pvc_reuse_is_blocked(tmp_path) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    storage = payload["templates"][0]["statePolicy"]["candidateStorage"]
    storage["type"] = "source_pvc"
    storage["reuseSourcePvc"] = True
    catalog_path = tmp_path / "unsafe-catalog.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    catalog = CandidateTemplateCatalog.load(catalog_path)
    kube = FakeKube()
    controller, _ = _controller(tmp_path, kube, catalog=catalog)
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["source_pvc_not_migratable"]
    assert kube.create_calls == 0


def test_missing_storage_class_is_blocked_before_create(tmp_path) -> None:
    kube = FakeKube(storage_class_failure=True)
    controller, _ = _controller(tmp_path, kube)
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["storage_class_unavailable"]
    assert kube.create_calls == 0


def test_unschedulable_target_is_blocked_before_create(tmp_path) -> None:
    kube = FakeKube(target_ready=False)
    controller, _ = _controller(tmp_path, kube)
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["target_node_unschedulable"]
    assert kube.create_calls == 0


def test_service_selector_collision_is_blocked(tmp_path) -> None:
    kube = FakeKube(service_selector={"edge-ai.io/candidate": "true"})
    controller, _ = _controller(tmp_path, kube)
    plan = _plan()
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert result.reason_codes == ["candidate_service_selector_conflict"]
    assert kube.create_calls == 0


def test_approved_execution_creates_fresh_state_candidate_once(tmp_path) -> None:
    kube = FakeKube()
    validation_engine = FakeValidationEngine()
    controller, _ = _controller(
        tmp_path,
        kube,
        validation_engine=validation_engine,
    )
    plan = _plan()
    first = asyncio.run(controller.execute(plan, _approval(plan)))
    repeated = asyncio.run(controller.execute(plan, _approval(plan)))

    assert first.status == "BLOCKED"
    assert first.candidate_created is True and first.candidate_ready is True
    assert first.existing_workload_preserved is True
    assert [step.status for step in first.steps] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "BLOCKED",
        "BLOCKED",
    ]
    assert first.steps[-1].reason_codes == ["unsupported_step"]
    assert repeated == first
    assert kube.create_calls == 1
    assert validation_engine.calls == 2
    assert kube.delete_calls == 0 and kube.update_calls == 0
    assert kube.source == kube.source_before

    body = kube.created_body
    assert body["metadata"]["namespace"] == "edge-ai-workloads"
    pod = body["spec"]["template"]
    assert pod["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "server-b"}
    assert {item["name"]: item for item in pod["spec"]["volumes"]}["state"] == {
        "name": "state",
        "emptyDir": {},
    }
    assert "persistentVolumeClaim" not in json.dumps(body)
    assert first.candidate_workload is not None
    assert first.candidate_workload.state_policy == "fresh_state"
    assert first.candidate_pvcs == []

    labels = pod["metadata"]["labels"]
    assert labels["edge-ai.io/service-id"] == "sensor-anomaly-demo"
    assert labels["edge-ai.io/execution-plan-id"] == plan.plan_id
    assert labels["edge-ai.io/candidate"] == "true"
    assert labels["edge-ai.io/source-workload"] == "sensor-anomaly-demo"
    assert not all(
        labels.get(key) == value for key, value in kube.service_selector.items()
    )

    reopened = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    assert reopened.get(plan.plan_id) == first
    audit = reopened.audit(plan.plan_id, limit=50)
    event_types = [event.event_type for event in audit]
    assert event_types[0:2] == ["approval_received", "execution_started"]
    assert "candidate_validation_observed" in event_types
    assert "pre_handoff_lease_snapshot" in event_types
    assert "execution_ownership_handed_off" in event_types
    assert "active_candidate_validation_observed" in event_types
    assert event_types[-1] == "execution_blocked"


def test_create_failure_stops_later_steps_and_preserves_current(tmp_path) -> None:
    kube = FakeKube(create_failure=True)
    controller, _ = _controller(tmp_path, kube)
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "FAILED"
    assert result.steps[0].status == "FAILED"
    assert all(step.status == "BLOCKED" for step in result.steps[1:])
    assert all(
            step.reason_codes
                == (
                    ["unsupported_step"]
                    if step.action in {"rollback_traffic", "rollback_execution_ownership"}
                    else ["previous_step_blocked"]
                )
        for step in result.steps[1:]
    )
    assert result.existing_workload_preserved is True
    assert kube.source == kube.source_before
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
    assert result.steps[2].reason_codes == ["previous_step_blocked"]
    assert result.existing_workload_preserved is True
    assert kube.create_calls == 1
    assert kube.delete_calls == 0 and kube.update_calls == 0


def test_validation_failure_blocks_traffic_and_preserves_source(tmp_path) -> None:
    kube = FakeKube()
    validation_engine = FakeValidationEngine(
        status="FAILED",
        reasons=["candidate_validation_timeout", "candidate_input_unavailable"],
    )
    controller, store = _controller(
        tmp_path,
        kube,
        validation_engine=validation_engine,
    )
    plan = _plan("replace")

    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "FAILED"
    assert [step.status for step in result.steps[:3]] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "FAILED",
    ]
    assert result.steps[2].reason_codes == [
        "candidate_validation_timeout",
        "candidate_input_unavailable",
    ]
    assert result.steps[3].reason_codes == ["previous_step_blocked"]
    assert result.steps[4].reason_codes == ["previous_step_blocked"]
    assert result.steps[5].reason_codes == ["previous_step_blocked"]
    assert result.steps[8].reason_codes == ["unsupported_step"]
    assert result.steps[9].reason_codes == ["unsupported_step"]
    assert result.validation is not None
    assert kube.source == kube.source_before
    assert kube.update_calls == 0 and kube.delete_calls == 0

    reopened = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    persisted = reopened.get(plan.plan_id)
    assert persisted is not None and persisted.validation == result.validation
    validation_events = [
        item
        for item in store.audit(plan.plan_id, limit=50)
        if item.event_type == "candidate_validation_observed"
    ]
    assert len(validation_events) == 1
    assert validation_events[0].details["validation"]["status"] == "FAILED"


def test_live_contract_blocks_unproven_endpointslice_mode_without_mutation(tmp_path) -> None:
    kube = FakeKube()
    controller, _ = _controller(tmp_path, kube)
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert [step.status for step in result.steps] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "BLOCKED",
        "BLOCKED",
        "SUCCEEDED",
    ]
    assert result.steps[5].reason_codes == ["routing_mode_unsupported"]
    assert result.steps[6].reason_codes == ["previous_step_blocked"]
    assert result.steps[7].reason_codes == ["previous_step_blocked"]
    assert result.steps[8].reason_codes == ["previous_step_blocked"]
    assert result.steps[9].reason_codes == ["execution_ownership_rollback_succeeded"]
    assert result.execution_ownership.active_owner == "source"
    assert kube.delete_calls == 0 and kube.update_calls == 0


def test_missing_routing_contract_blocks_switch_without_traffic_mutation(tmp_path) -> None:
    controller, _ = _controller(
        tmp_path,
        FakeKube(),
        routing_catalog=RoutingContractCatalog({}),
    )
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))
    assert result.steps[5].status == "FAILED"
    assert result.steps[5].reason_codes == ["routing_contract_not_found"]
    assert result.routing is None


def test_controller_rejects_missing_explicit_approval(tmp_path) -> None:
    controller, _ = _controller(tmp_path, FakeKube())
    plan = _plan()
    try:
        asyncio.run(controller.execute(plan, _approval(plan, approved=False)))
    except PermissionError as exc:
        assert "approval" in str(exc)
    else:
        raise AssertionError("execution without approval must fail")


def test_async_start_returns_immediately_and_duplicate_does_not_reexecute(tmp_path) -> None:
    async def scenario():
        kube = FakeKube()
        validation_engine = BlockingValidationEngine()
        controller, store = _controller(
            tmp_path,
            kube,
            validation_engine=validation_engine,
        )
        plan = _plan()
        approval = _approval(plan)

        first, created = await controller.start(plan, approval)
        assert created is True and first.status == "PENDING"
        await validation_engine.started.wait()

        repeated, repeated_created = await controller.start(plan, approval)
        assert repeated_created is False
        assert repeated.plan_id == first.plan_id
        assert validation_engine.calls == 0

        validation_engine.release.set()
        for _ in range(20):
            await asyncio.sleep(0)
            current = store.get(plan.plan_id)
            if current is not None and current.status == "BLOCKED":
                break
        current = store.get(plan.plan_id)
        assert current is not None and current.status == "BLOCKED"
        assert current.validation is not None
        assert current.validation.status == "SUCCEEDED"
        assert validation_engine.calls == 2
        assert kube.create_calls == 1
        await controller.shutdown()

    asyncio.run(scenario())


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
    record.validation = CandidateValidationResult(
        status="RUNNING",
        started_at=NOW,
        consecutive_successes=2,
        required_consecutive_successes=6,
        minimum_stable_seconds=30,
        observed_at=NOW,
    )
    store.save(record, event_type="test_interruption", actor="test")

    recovered_store = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    recovered = recovered_store.get(plan.plan_id)

    assert recovered is not None
    assert recovered.status == "BLOCKED"
    assert recovered.reason_codes == [
        "execution_interrupted",
        "execution_ownership_recovery_required",
    ]
    assert all(step.status == "BLOCKED" for step in recovered.steps)
    assert recovered.validation is not None
    assert recovered.validation.status == "BLOCKED"
    assert recovered.validation.reason_codes == ["execution_interrupted"]


def test_existing_audit_schema_is_migrated_for_validation_details(tmp_path) -> None:
    database_path = tmp_path / "legacy-executions.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE runtime_execution_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                step_id TEXT,
                previous_status TEXT,
                status TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )

    RuntimeExecutionStore(database_path)

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(runtime_execution_audit)"
            ).fetchall()
        }
    assert "details_json" in columns


def _verified_routing_catalog():
    payload = json.loads(
        (CATALOG_PATH.parent / "traffic_routing_contracts.json").read_text(encoding="utf-8")
    )["contracts"][0]
    payload["compatibilityStatus"] = "verified"
    payload["compatibilityReasonCodes"] = []
    contract = TrafficRoutingContract.model_validate(payload)
    return RoutingContractCatalog({contract.service_id: contract}), contract


def _routing_snapshot(target, address, version):
    return RoutingSnapshot(
        endpoint_slice_name="sensor-anomaly-demo-runtime-routing",
        resource_version=version,
        active_target=target,
        address_type="IPv4",
        addresses=[address],
        endpoints=[{"addresses": [address]}],
        ports=[{"name": "http", "protocol": "TCP", "port": 8080}],
        labels={"edge-ai.io/active-target": target},
        observed_at=NOW,
    )


class FakeTrafficRoutingEngine:
    def __init__(self, *, rollback_failure=False):
        self.switch_calls = 0
        self.rollback_calls = 0
        self.rollback_failure = rollback_failure

    async def switch(self, **kwargs):
        self.switch_calls += 1
        before = _routing_snapshot("source", "10.1.0.1", "1")
        pending = RuntimeExecutionRouting(
            service_id="sensor-anomaly-demo",
            namespace="edgex-edge",
            service="sensor-anomaly-demo",
            mode="runtime-endpointslice",
            active_target="source",
            source_node="edge-a",
            candidate_node="server-b",
            rollback_available=True,
            before=before,
        )
        observer = kwargs.get("snapshot_observer")
        if observer:
            await observer(pending)
        pending.active_target = "candidate"
        pending.after = _routing_snapshot("candidate", "10.2.0.2", "2")
        pending.switched_at = NOW
        return pending

    async def rollback(self, **kwargs):
        self.rollback_calls += 1
        if self.rollback_failure:
            raise TrafficRoutingError("traffic_rollback_failed")
        routing = kwargs["routing"]
        routing.active_target = "source"
        routing.rollback = _routing_snapshot("source", "10.1.0.1", "3")
        routing.rolled_back_at = NOW
        routing.reason_codes = ["traffic_rollback_succeeded"]
        return routing


class SequencedValidationEngine:
    def __init__(self, post_status="SUCCEEDED", post_reasons=None):
        self.calls = 0
        self.post_status = post_status
        self.post_reasons = post_reasons or ["candidate_endpoint_unreachable"]

    async def validate(self, **kwargs):
        self.calls += 1
        post = kwargs.get("candidate_base_url") is not None
        status = self.post_status if post else "SUCCEEDED"
        reasons = (
            ["candidate_validation_succeeded"]
            if status == "SUCCEEDED"
            else self.post_reasons
        )
        result = CandidateValidationResult(
            status=status,
            reason_codes=reasons,
            started_at=NOW,
            completed_at=NOW,
            consecutive_successes=6 if status == "SUCCEEDED" else 0,
            required_consecutive_successes=6,
            minimum_stable_seconds=30,
            candidate=CandidateValidationWorkloadObservation(
                node="server-b",
                pod="candidate-pod",
                reachable=status == "SUCCEEDED",
                input_state="fresh",
                model_state="ready",
                latency_ms=82,
                frames_processed=11 if post else 10,
                observed_at=NOW,
            ),
            observed_at=NOW,
        )
        observer = kwargs.get("observer")
        if observer:
            await observer(result)
        return result


class ActivationValidationEngine(FakeValidationEngine):
    def __init__(self, active_status="SUCCEEDED", active_reasons=None):
        super().__init__()
        self.active_status = active_status
        self.active_reasons = active_reasons or ["candidate_not_active"]

    async def validate(self, **kwargs):
        self.calls += 1
        active = self.calls > 1
        status = self.active_status if active else "SUCCEEDED"
        result = CandidateValidationResult(
            status=status,
            reason_codes=(
                ["candidate_validation_succeeded"]
                if status == "SUCCEEDED"
                else self.active_reasons
            ),
            started_at=NOW,
            completed_at=NOW,
            consecutive_successes=6 if status == "SUCCEEDED" else 0,
            required_consecutive_successes=6,
            minimum_stable_seconds=30,
            candidate=CandidateValidationWorkloadObservation(
                node="server-b",
                pod="candidate-pod",
                reachable=status == "SUCCEEDED",
                input_state="fresh",
                model_state="ready",
                frames_processed=1 if active and status == "SUCCEEDED" else 0,
                observed_at=NOW,
            ),
            observed_at=NOW,
        )
        observer = kwargs.get("observer")
        if observer is not None:
            await observer(result)
        return result


def test_active_validation_failure_restores_source_lease_without_deleting_candidate(tmp_path) -> None:
    ownership_engine = FakeOwnershipEngine()
    controller, _ = _controller(
        tmp_path,
        FakeKube(),
        validation_engine=ActivationValidationEngine(
            active_status="FAILED",
            active_reasons=["candidate_not_active"],
        ),
        ownership_engine=ownership_engine,
    )
    plan = _plan("replace")

    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.steps[3].status == "SUCCEEDED"
    assert result.steps[4].status == "FAILED"
    assert result.steps[4].reason_codes == ["candidate_not_active"]
    assert result.steps[9].status == "SUCCEEDED"
    assert result.execution_ownership.active_owner == "source"
    assert ownership_engine.handoff_calls == 1
    assert ownership_engine.rollback_calls == 1
    assert result.existing_workload_preserved is True


def test_ambiguous_handoff_failure_uses_persisted_snapshot_to_restore_source(tmp_path) -> None:
    ownership_engine = FakeOwnershipEngine(
        handoff_failure="execution_lease_update_failed"
    )
    kube = FakeKube()
    controller, store = _controller(
        tmp_path,
        kube,
        ownership_engine=ownership_engine,
    )
    plan = _plan("replace")

    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.steps[3].status == "FAILED"
    assert result.steps[3].reason_codes == ["execution_lease_update_failed"]
    assert result.steps[9].status == "SUCCEEDED"
    assert result.execution_ownership.active_owner == "source"
    assert ownership_engine.rollback_calls == 1
    assert kube.delete_calls == 0
    events = [item.event_type for item in store.audit(plan.plan_id, limit=100)]
    assert "pre_handoff_lease_snapshot" in events
    assert "execution_ownership_rollback_succeeded" in events


def test_verified_routing_switch_and_post_validation_stop_before_termination(tmp_path) -> None:
    catalog, _ = _verified_routing_catalog()
    routing_engine = FakeTrafficRoutingEngine()
    validation_engine = SequencedValidationEngine()
    controller, store = _controller(
        tmp_path,
        FakeKube(),
        validation_engine=validation_engine,
        routing_catalog=catalog,
        routing_engine=routing_engine,
    )
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "BLOCKED"
    assert [item.status for item in result.steps] == [
        "SUCCEEDED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED",
        "SUCCEEDED", "SUCCEEDED", "BLOCKED", "BLOCKED", "BLOCKED"
    ]
    assert result.steps[7].reason_codes == ["unsupported_step"]
    assert result.routing.active_target == "candidate"
    assert result.post_switch_validation.status == "SUCCEEDED"
    assert validation_engine.calls == 3
    assert routing_engine.switch_calls == 1 and routing_engine.rollback_calls == 0
    events = [item.event_type for item in store.audit(plan.plan_id, limit=100)]
    assert "pre_switch_routing_snapshot" in events
    assert "endpoint_slice_switched" in events
    assert "post_switch_validation_observed" in events


@pytest.mark.parametrize(
    "reason",
    [
        "candidate_endpoint_unreachable",
        "candidate_input_stale",
        "candidate_model_not_ready",
        "candidate_inference_not_observed",
        "candidate_latency_slo_violated",
        "candidate_validation_timeout",
    ],
)
def test_post_switch_failure_rolls_back_exact_source_snapshot(tmp_path, reason) -> None:
    catalog, _ = _verified_routing_catalog()
    routing_engine = FakeTrafficRoutingEngine()
    controller, _ = _controller(
        tmp_path,
        FakeKube(),
        validation_engine=SequencedValidationEngine("FAILED", [reason]),
        routing_catalog=catalog,
        routing_engine=routing_engine,
    )
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.status == "FAILED"
    assert result.steps[6].status == "FAILED"
    assert result.steps[7].reason_codes == ["previous_step_blocked"]
    assert result.steps[8].status == "SUCCEEDED"
    assert result.steps[8].reason_codes == ["traffic_rollback_succeeded"]
    assert result.steps[9].status == "SUCCEEDED"
    assert result.steps[9].reason_codes == ["execution_ownership_rollback_succeeded"]
    assert result.routing.active_target == "source"
    assert result.routing.rollback.addresses == ["10.1.0.1"]
    assert routing_engine.rollback_calls == 1


def test_rollback_failure_is_persisted_and_keeps_service_lock(tmp_path) -> None:
    catalog, _ = _verified_routing_catalog()
    routing_engine = FakeTrafficRoutingEngine(rollback_failure=True)
    controller, store = _controller(
        tmp_path,
        FakeKube(),
        validation_engine=SequencedValidationEngine("FAILED"),
        routing_catalog=catalog,
        routing_engine=routing_engine,
    )
    plan = _plan("replace")
    result = asyncio.run(controller.execute(plan, _approval(plan)))

    assert result.steps[8].status == "FAILED"
    assert result.steps[9].status == "BLOCKED"
    assert "traffic_rollback_failed" in result.reason_codes
    assert store.acquire_routing_lock("sensor-anomaly-demo", "another-plan") is False


def test_service_routing_lock_blocks_concurrent_plan_and_allows_idempotent_owner(tmp_path) -> None:
    store = RuntimeExecutionStore(tmp_path / "locks.sqlite3")
    assert store.acquire_routing_lock("sensor-anomaly-demo", "plan-a") is True
    assert store.acquire_routing_lock("sensor-anomaly-demo", "plan-a") is True
    assert store.acquire_routing_lock("sensor-anomaly-demo", "plan-b") is False
    store.release_routing_lock("sensor-anomaly-demo", "plan-a")
    assert store.acquire_routing_lock("sensor-anomaly-demo", "plan-b") is True


def test_service_ownership_lock_blocks_concurrent_handoffs_and_allows_idempotency(tmp_path) -> None:
    store = RuntimeExecutionStore(tmp_path / "ownership-locks.sqlite3")
    assert store.acquire_ownership_lock("sensor-anomaly-demo", "plan-a") is True
    assert store.acquire_ownership_lock("sensor-anomaly-demo", "plan-a") is True
    assert store.acquire_ownership_lock("sensor-anomaly-demo", "plan-b") is False
    store.release_ownership_lock("sensor-anomaly-demo", "plan-a")
    assert store.acquire_ownership_lock("sensor-anomaly-demo", "plan-b") is True


def test_restart_blocks_interrupted_candidate_routing_for_manual_recovery(tmp_path) -> None:
    controller, store = _controller(tmp_path, FakeKube())
    plan = _plan("replace")
    record, _ = controller._reserve(plan, _approval(plan))
    record.status = "RUNNING"
    record.routing = RuntimeExecutionRouting(
        service_id="sensor-anomaly-demo",
        namespace="edgex-edge",
        service="sensor-anomaly-demo",
        mode="runtime-endpointslice",
        active_target="candidate",
        before=_routing_snapshot("source", "10.1.0.1", "1"),
        after=_routing_snapshot("candidate", "10.2.0.2", "2"),
        rollback_available=True,
    )
    record.steps[6].status = "RUNNING"
    store.acquire_routing_lock(record.service_id, record.plan_id)
    store.save(record, event_type="test_switch_interrupted", actor="test")

    recovered = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    value = recovered.get(record.plan_id)
    assert value.status == "BLOCKED"
    assert value.reason_codes == ["execution_interrupted", "routing_recovery_required"]
    assert recovered.acquire_routing_lock(record.service_id, "other-plan") is False


def test_restart_blocks_interrupted_candidate_ownership_for_manual_recovery(tmp_path) -> None:
    controller, store = _controller(tmp_path, FakeKube())
    plan = _plan("replace")
    record, _ = controller._reserve(plan, _approval(plan))
    record.status = "RUNNING"
    before = LeaseSnapshot(
        namespace="edgex-edge",
        name="sensor-anomaly-demo-execution",
        holder_identity="sensor-anomaly-demo",
        lease_duration_seconds=15,
        renew_time=NOW,
        resource_version="1",
        observed_at=NOW,
    )
    record.execution_ownership = RuntimeExecutionOwnership(
        lease_namespace="edgex-edge",
        lease_name="sensor-anomaly-demo-execution",
        source_holder="sensor-anomaly-demo",
        candidate_holder="candidate-a",
        active_owner="candidate",
        before=before,
        after=before.model_copy(
            update={"holder_identity": "candidate-a", "resource_version": "2"}
        ),
        handed_off_at=NOW,
    )
    record.steps[4].status = "RUNNING"
    store.acquire_ownership_lock(record.service_id, record.plan_id)
    store.save(record, event_type="test_handoff_interrupted", actor="test")

    recovered = RuntimeExecutionStore(tmp_path / "executions.sqlite3")
    value = recovered.get(record.plan_id)

    assert value.status == "BLOCKED"
    assert value.reason_codes == [
        "execution_interrupted",
        "execution_ownership_recovery_required",
    ]
    assert recovered.acquire_ownership_lock(record.service_id, "other-plan") is False
