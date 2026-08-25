from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .deployment_controller import DeploymentController, build_deployment_manifest
from .kube import KubeDeploymentError
from .models import (
    DeploymentCreateRequest,
    PlacementSelectionRequest,
    SchedulingModel,
)
from .runtime_execution_plan import RuntimeExecutionPlan


ExecutionStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED"]
_PLAN_ID = re.compile(r"^runtime-plan-[0-9a-f]{16}$")


class RuntimeExecutionPlanReference(SchedulingModel):
    plan_id: str = Field(pattern=_PLAN_ID.pattern)


class RuntimeExecutionApproval(RuntimeExecutionPlanReference):
    approved: bool
    approved_by: str = Field(min_length=1, max_length=128)


class RuntimeExecutionDryRunStep(SchedulingModel):
    step_id: str
    action: str
    supported: bool
    reason_codes: list[str] = Field(default_factory=list)


class RuntimeExecutionDryRun(SchedulingModel):
    plan_id: str
    service_id: str
    status: Literal["ready", "partial", "blocked"]
    reason_codes: list[str] = Field(default_factory=list)
    first_unsupported_step_id: str | None = None
    steps: list[RuntimeExecutionDryRunStep] = Field(default_factory=list)
    mode: Literal["dry_run"] = "dry_run"
    generated_at: datetime


class RuntimeExecutionStepState(SchedulingModel):
    step_id: str
    action: str
    status: ExecutionStatus = "PENDING"
    reason_codes: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RuntimeExecutionRecord(SchedulingModel):
    plan_id: str
    service_id: str
    status: ExecutionStatus
    approved_by: str
    approved_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    reason_codes: list[str] = Field(default_factory=list)
    candidate_created: bool = False
    candidate_ready: bool = False
    existing_workload_preserved: Literal[True] = True
    plan: RuntimeExecutionPlan
    steps: list[RuntimeExecutionStepState]
    updated_at: datetime


class RuntimeExecutionHistory(SchedulingModel):
    generated_at: datetime
    items: list[RuntimeExecutionRecord] = Field(default_factory=list)


class RuntimeExecutionAuditEvent(SchedulingModel):
    sequence: int = Field(ge=1)
    plan_id: str
    event_type: str
    actor: str
    step_id: str | None = None
    previous_status: ExecutionStatus | None = None
    status: ExecutionStatus
    reason_codes: list[str] = Field(default_factory=list)
    recorded_at: datetime


class RuntimeExecutionAuditLog(SchedulingModel):
    plan_id: str
    generated_at: datetime
    items: list[RuntimeExecutionAuditEvent] = Field(default_factory=list)


class RuntimeExecutionStore:
    def __init__(self, database_path: Path, *, history_limit: int = 1000) -> None:
        self.database_path = database_path
        self.history_limit = history_limit
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._recover_interrupted()

    def reserve(
        self,
        record: RuntimeExecutionRecord,
    ) -> tuple[RuntimeExecutionRecord, bool]:
        payload = record.model_dump_json(by_alias=False)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json FROM runtime_execution WHERE plan_id = ?",
                (record.plan_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return RuntimeExecutionRecord.model_validate_json(existing[0]), False
            connection.execute(
                """
                INSERT INTO runtime_execution(plan_id, service_id, updated_at, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (record.plan_id, record.service_id, record.updated_at.isoformat(), payload),
            )
            self._insert_audit(
                connection,
                record,
                event_type="approval_received",
                actor=record.approved_by,
            )
            connection.commit()
        return record, True

    def save(
        self,
        record: RuntimeExecutionRecord,
        *,
        event_type: str,
        actor: str,
        step_id: str | None = None,
        previous_status: ExecutionStatus | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE runtime_execution
                SET service_id = ?, updated_at = ?, payload_json = ?
                WHERE plan_id = ?
                """,
                (
                    record.service_id,
                    record.updated_at.isoformat(),
                    record.model_dump_json(by_alias=False),
                    record.plan_id,
                ),
            )
            self._insert_audit(
                connection,
                record,
                event_type=event_type,
                actor=actor,
                step_id=step_id,
                previous_status=previous_status,
            )
            connection.commit()

    def get(self, plan_id: str) -> RuntimeExecutionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM runtime_execution WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        return RuntimeExecutionRecord.model_validate_json(row[0]) if row else None

    def history(
        self,
        *,
        service_id: str | None,
        limit: int,
    ) -> list[RuntimeExecutionRecord]:
        limit = min(limit, self.history_limit)
        query = "SELECT payload_json FROM runtime_execution"
        parameters: list[Any] = []
        if service_id:
            query += " WHERE service_id = ?"
            parameters.append(service_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [RuntimeExecutionRecord.model_validate_json(row[0]) for row in rows]

    def audit(self, plan_id: str, *, limit: int) -> list[RuntimeExecutionAuditEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, event_type, actor, step_id, previous_status, status,
                       reason_codes_json, recorded_at
                FROM runtime_execution_audit
                WHERE plan_id = ? ORDER BY id ASC LIMIT ?
                """,
                (plan_id, min(limit, self.history_limit)),
            ).fetchall()
        return [
            RuntimeExecutionAuditEvent(
                sequence=row[0],
                plan_id=plan_id,
                event_type=row[1],
                actor=row[2],
                step_id=row[3],
                previous_status=row[4],
                status=row[5],
                reason_codes=json.loads(row[6]),
                recorded_at=datetime.fromisoformat(row[7]),
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_execution (
                    plan_id TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_execution_audit (
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
            connection.commit()

    def _recover_interrupted(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM runtime_execution"
            ).fetchall()
        for row in rows:
            record = RuntimeExecutionRecord.model_validate_json(row[0])
            if record.status not in {"PENDING", "RUNNING"}:
                continue
            now = datetime.now(timezone.utc)
            for step in record.steps:
                if step.status in {"RUNNING", "PENDING"}:
                    step.status = "BLOCKED"
                    step.reason_codes = ["execution_interrupted"]
                    step.completed_at = now
            record.status = "BLOCKED"
            record.reason_codes = ["execution_interrupted"]
            record.completed_at = now
            record.updated_at = now
            self.save(record, event_type="execution_recovered_blocked", actor="system")

    def _insert_audit(
        self,
        connection: sqlite3.Connection,
        record: RuntimeExecutionRecord,
        *,
        event_type: str,
        actor: str,
        step_id: str | None = None,
        previous_status: ExecutionStatus | None = None,
    ) -> None:
        step = next(
            (item for item in record.steps if item.step_id == step_id),
            None,
        )
        event_status = step.status if step is not None else record.status
        event_reasons = step.reason_codes if step is not None else record.reason_codes
        connection.execute(
            """
            INSERT INTO runtime_execution_audit(
                plan_id, event_type, actor, step_id, previous_status, status,
                reason_codes_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.plan_id,
                event_type,
                actor,
                step_id,
                previous_status,
                event_status,
                json.dumps(event_reasons),
                record.updated_at.isoformat(),
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection


class RuntimeExecutionController:
    SUPPORTED_ACTIONS = {"create_candidate", "verify_ready"}

    def __init__(self, settings: Any, kube: Any, store: RuntimeExecutionStore) -> None:
        self.settings = settings
        self.kube = kube
        self.store = store
        self.deployment_controller = DeploymentController(settings, kube)

    async def dry_run(self, plan: RuntimeExecutionPlan) -> RuntimeExecutionDryRun:
        errors, _ = await self._prepare_request(plan)
        first_unsupported = next(
            (step.step_id for step in plan.steps if step.action not in self.SUPPORTED_ACTIONS),
            None,
        )
        steps = [
            RuntimeExecutionDryRunStep(
                step_id=step.step_id,
                action=step.action,
                supported=step.action in self.SUPPORTED_ACTIONS,
                reason_codes=(
                    [] if step.action in self.SUPPORTED_ACTIONS else ["unsupported_step"]
                ),
            )
            for step in plan.steps
        ]
        if plan.status != "planned":
            errors = ["execution_plan_not_planned", *plan.reason_codes]
        status = "blocked" if errors else ("partial" if first_unsupported else "ready")
        reasons = _unique(
            [*errors, *( ["unsupported_step"] if first_unsupported else [])]
        )
        return RuntimeExecutionDryRun(
            plan_id=plan.plan_id,
            service_id=plan.service_id,
            status=status,
            reason_codes=reasons,
            first_unsupported_step_id=first_unsupported,
            steps=steps,
            generated_at=datetime.now(timezone.utc),
        )

    async def execute(
        self,
        plan: RuntimeExecutionPlan,
        approval: RuntimeExecutionApproval,
    ) -> RuntimeExecutionRecord:
        if not approval.approved:
            raise PermissionError("explicit execution approval is required")
        now = datetime.now(timezone.utc)
        record = RuntimeExecutionRecord(
            plan_id=plan.plan_id,
            service_id=plan.service_id,
            status="PENDING",
            approved_by=approval.approved_by,
            approved_at=now,
            plan=plan,
            steps=[
                RuntimeExecutionStepState(step_id=s.step_id, action=s.action)
                for s in plan.steps
            ],
            updated_at=now,
        )
        record, created = self.store.reserve(record)
        if not created:
            return record
        errors, request = await self._prepare_request(plan)
        if plan.status != "planned":
            errors = ["execution_plan_not_planned", *plan.reason_codes]
        if errors or request is None:
            return self._finish_blocked(record, approval.approved_by, errors)

        record.status = "RUNNING"
        record.started_at = datetime.now(timezone.utc)
        record.updated_at = record.started_at
        self.store.save(record, event_type="execution_started", actor=approval.approved_by)

        for index, planned_step in enumerate(plan.steps):
            step = record.steps[index]
            if planned_step.action not in self.SUPPORTED_ACTIONS:
                self._block_remaining(record, index, "unsupported_step")
                record.status = "BLOCKED"
                record.reason_codes = ["unsupported_step"]
                record.completed_at = datetime.now(timezone.utc)
                record.updated_at = record.completed_at
                for blocked_step in record.steps[index:]:
                    self.store.save(
                        record,
                        event_type="step_blocked",
                        actor=approval.approved_by,
                        step_id=blocked_step.step_id,
                        previous_status="PENDING",
                    )
                self.store.save(
                    record,
                    event_type="execution_blocked",
                    actor=approval.approved_by,
                )
                return record
            previous = step.status
            step.status = "RUNNING"
            step.started_at = datetime.now(timezone.utc)
            record.updated_at = step.started_at
            self.store.save(
                record,
                event_type="step_started",
                actor=approval.approved_by,
                step_id=step.step_id,
                previous_status=previous,
            )
            if planned_step.action == "create_candidate":
                failure = await self._create_candidate(plan, request)
                if failure is None:
                    record.candidate_created = True
            else:
                failure = await self._verify_ready(plan, request)
                if failure is None:
                    record.candidate_ready = True
            if failure is not None:
                return self._fail_step(record, index, failure, approval.approved_by)
            step.status = "SUCCEEDED"
            step.completed_at = datetime.now(timezone.utc)
            record.updated_at = step.completed_at
            self.store.save(
                record,
                event_type="step_succeeded",
                actor=approval.approved_by,
                step_id=step.step_id,
                previous_status="RUNNING",
            )

        record.status = "SUCCEEDED"
        record.reason_codes = ["execution_completed"]
        record.completed_at = datetime.now(timezone.utc)
        record.updated_at = record.completed_at
        self.store.save(record, event_type="execution_succeeded", actor=approval.approved_by)
        return record

    async def _prepare_request(
        self,
        plan: RuntimeExecutionPlan,
    ) -> tuple[list[str], DeploymentCreateRequest | None]:
        errors: list[str] = []
        if plan.status != "planned" or plan.placement is None:
            return ["execution_plan_not_planned"], None
        if plan.placement.requirements is None:
            return ["placement_requirements_missing"], None
        if plan.plan_id == "" or not _PLAN_ID.fullmatch(plan.plan_id):
            return ["invalid_plan_id"], None
        source = next(
            (
                target.workload
                for step in plan.steps
                for target in step.targets
                if target.workload.role == "current"
            ),
            None,
        )
        candidate = next(
            (
                target.workload
                for step in plan.steps
                for target in step.targets
                if target.workload.role == "candidate"
            ),
            None,
        )
        if source is None or candidate is None:
            return ["execution_targets_missing"], None
        if source.kind != "Deployment" or candidate.kind != "Deployment":
            return ["source_workload_kind_unsupported"], None
        if candidate.namespace != self.settings.deployment_target_namespace:
            return ["candidate_namespace_not_allowed"], None
        try:
            deployment = await self.kube.read_deployment(source.namespace, source.name)
        except KubeDeploymentError as exc:
            return [exc.reason_code], None
        template = getattr(getattr(deployment, "spec", None), "template", None)
        pod_spec = getattr(template, "spec", None)
        containers = list(getattr(pod_spec, "containers", None) or [])
        if len(containers) != 1:
            return ["source_container_count_unsupported"], None
        container = containers[0]
        if (
            getattr(pod_spec, "init_containers", None)
            or getattr(pod_spec, "volumes", None)
            or getattr(container, "env", None)
            or getattr(container, "env_from", None)
            or getattr(container, "command", None)
            or getattr(container, "args", None)
            or getattr(container, "volume_mounts", None)
        ):
            return ["source_workload_contract_unsupported"], None
        image = getattr(container, "image", None) or ""
        ports = getattr(container, "ports", None) or []
        container_port = getattr(ports[0], "container_port", None) if ports else None
        readiness = getattr(container, "readiness_probe", None)
        http_get = getattr(readiness, "http_get", None) if readiness else None
        readiness_path = getattr(http_get, "path", None) if http_get else None
        try:
            request = DeploymentCreateRequest(
                deployment_name=candidate.name,
                image=image,
                placement=PlacementSelectionRequest(
                    namespace=plan.placement.service_profile.namespace,
                    service=plan.placement.service_profile.service,
                    architecture=plan.placement.requirements.architecture,
                    accelerator=plan.placement.requirements.accelerator,
                    accelerator_units=plan.placement.requirements.accelerator_units,
                ),
                container_port=container_port,
                readiness_path=readiness_path,
            )
        except Exception:
            return ["source_workload_contract_invalid"], None
        rejected = self.deployment_controller.validate_request(
            request,
            plan.placement,
            plan.plan_id,
        )
        if rejected is not None:
            errors.extend(rejected.reason_codes)
        return _unique(errors), request

    async def _create_candidate(
        self,
        plan: RuntimeExecutionPlan,
        request: DeploymentCreateRequest,
    ) -> str | None:
        namespace = self.settings.deployment_target_namespace
        try:
            if await self.kube.deployment_exists(namespace, request.deployment_name):
                return "candidate_workload_already_exists"
            manifest = build_deployment_manifest(
                namespace,
                request,
                plan.placement,
                plan.plan_id,
                self.settings.deployment_ready_timeout_seconds,
            )
            await self.kube.create_deployment(namespace, manifest)
            return None
        except KubeDeploymentError as exc:
            return exc.reason_code

    async def _verify_ready(
        self,
        plan: RuntimeExecutionPlan,
        request: DeploymentCreateRequest,
    ) -> str | None:
        result = await self.deployment_controller.wait_until_ready(
            request,
            plan.placement,
            plan.plan_id,
        )
        return None if result.status == "ready" else (result.reason_codes[0] if result.reason_codes else "candidate_not_ready")

    def _fail_step(
        self,
        record: RuntimeExecutionRecord,
        index: int,
        reason: str,
        actor: str,
    ) -> RuntimeExecutionRecord:
        now = datetime.now(timezone.utc)
        step = record.steps[index]
        step.status = "FAILED"
        step.reason_codes = [reason]
        step.completed_at = now
        for later in record.steps[index + 1 :]:
            later.status = "BLOCKED"
            later.reason_codes = ["previous_step_failed"]
            later.completed_at = now
        record.status = "FAILED"
        record.reason_codes = [reason]
        record.completed_at = now
        record.updated_at = now
        self.store.save(
            record,
            event_type="step_failed",
            actor=actor,
            step_id=step.step_id,
            previous_status="RUNNING",
        )
        for later in record.steps[index + 1 :]:
            self.store.save(
                record,
                event_type="step_blocked",
                actor=actor,
                step_id=later.step_id,
                previous_status="PENDING",
            )
        self.store.save(record, event_type="execution_failed", actor=actor)
        return record

    def _finish_blocked(
        self,
        record: RuntimeExecutionRecord,
        actor: str,
        reasons: list[str],
    ) -> RuntimeExecutionRecord:
        now = datetime.now(timezone.utc)
        for step in record.steps:
            step.status = "BLOCKED"
            step.reason_codes = ["execution_preflight_blocked"]
            step.completed_at = now
        record.status = "BLOCKED"
        record.reason_codes = _unique(reasons or ["execution_preflight_blocked"])
        record.completed_at = now
        record.updated_at = now
        self.store.save(record, event_type="execution_blocked", actor=actor)
        return record

    @staticmethod
    def _block_remaining(
        record: RuntimeExecutionRecord,
        index: int,
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        current = record.steps[index]
        current.status = "BLOCKED"
        current.reason_codes = [reason]
        current.completed_at = now
        for later in record.steps[index + 1 :]:
            later.status = "BLOCKED"
            later.reason_codes = ["previous_step_blocked"]
            later.completed_at = now


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
