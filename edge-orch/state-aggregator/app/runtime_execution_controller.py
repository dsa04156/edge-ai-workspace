from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .candidate_workload_template import (
    CandidateTemplateCatalog,
    CandidateWorkloadTemplate,
    build_candidate_deployment_manifest,
    quantity_matches,
)
from .candidate_validation import (
    CandidateValidationContract,
    CandidateValidationEngine,
    CandidateValidationResult,
    ValidationContractCatalog,
)
from .deployment_controller import DeploymentController
from .execution_ownership import (
    ExecutionOwnershipContract,
    ExecutionOwnershipEngine,
    ExecutionOwnershipError,
    OwnershipContractCatalog,
    RuntimeExecutionOwnership,
)
from .kube import KubeDeploymentError, KubeResourceReadError
from .models import (
    DeploymentCreateRequest,
    PlacementSelectionRequest,
    SchedulingModel,
)
from .runtime_execution_plan import RuntimeExecutionPlan
from .traffic_routing import (
    RoutingContractCatalog,
    RuntimeExecutionRouting,
    TrafficRoutingContract,
    TrafficRoutingEngine,
    TrafficRoutingError,
)


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


class RuntimeExecutionCandidateWorkload(SchedulingModel):
    namespace: str
    kind: Literal["Deployment"] = "Deployment"
    name: str
    target_node: str
    template_version: str
    state_policy: str


class RuntimeExecutionCandidatePVC(SchedulingModel):
    namespace: str
    name: str
    storage_class_name: str | None = None
    access_modes: list[str] = Field(default_factory=list)


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
    candidate_workload: RuntimeExecutionCandidateWorkload | None = None
    candidate_pvcs: list[RuntimeExecutionCandidatePVC] = Field(default_factory=list)
    validation: CandidateValidationResult | None = None
    active_candidate_validation: CandidateValidationResult | None = None
    post_switch_validation: CandidateValidationResult | None = None
    execution_ownership: RuntimeExecutionOwnership | None = None
    routing: RuntimeExecutionRouting | None = None
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
    details: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime


class RuntimeExecutionAuditLog(SchedulingModel):
    plan_id: str
    generated_at: datetime
    items: list[RuntimeExecutionAuditEvent] = Field(default_factory=list)


@dataclass(frozen=True)
class PreparedCandidate:
    request: DeploymentCreateRequest
    template: CandidateWorkloadTemplate
    validation_contract: CandidateValidationContract
    ownership_contract: ExecutionOwnershipContract
    manifest: dict[str, Any]
    source_namespace: str
    source_selector: dict[str, str]
    source_node: str | None
    candidate_port: int


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
        details: dict[str, Any] | None = None,
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
                details=details,
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
                       reason_codes_json, details_json, recorded_at
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
                details=json.loads(row[7]) if row[7] else {},
                recorded_at=datetime.fromisoformat(row[8]),
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
                CREATE TABLE IF NOT EXISTS runtime_routing_lock (
                    service_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_execution_ownership_lock (
                    service_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
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
                    details_json TEXT,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(runtime_execution_audit)"
                ).fetchall()
            }
            if "details_json" not in columns:
                connection.execute(
                    "ALTER TABLE runtime_execution_audit ADD COLUMN details_json TEXT"
                )
            connection.commit()

    def acquire_routing_lock(self, service_id: str, plan_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT plan_id FROM runtime_routing_lock WHERE service_id = ?",
                (service_id,),
            ).fetchone()
            if row is not None and row[0] != plan_id:
                connection.commit()
                return False
            connection.execute(
                "INSERT OR IGNORE INTO runtime_routing_lock(service_id, plan_id, acquired_at) VALUES (?, ?, ?)",
                (service_id, plan_id, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
            return True

    def release_routing_lock(self, service_id: str, plan_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM runtime_routing_lock WHERE service_id = ? AND plan_id = ?",
                (service_id, plan_id),
            )
            connection.commit()

    def acquire_ownership_lock(self, service_id: str, plan_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT plan_id FROM runtime_execution_ownership_lock WHERE service_id = ?",
                (service_id,),
            ).fetchone()
            if row is not None and row[0] != plan_id:
                connection.commit()
                return False
            connection.execute(
                "INSERT OR IGNORE INTO runtime_execution_ownership_lock(service_id, plan_id, acquired_at) VALUES (?, ?, ?)",
                (service_id, plan_id, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
            return True

    def release_ownership_lock(self, service_id: str, plan_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM runtime_execution_ownership_lock WHERE service_id = ? AND plan_id = ?",
                (service_id, plan_id),
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
            routing_interrupted = record.routing is not None and (
                record.routing.active_target == "candidate"
                or any(
                    step.action in {"switch_traffic", "verify_switched_traffic", "rollback_traffic"}
                    and step.status == "RUNNING"
                    for step in record.steps
                )
            )
            ownership_interrupted = record.execution_ownership is not None and (
                record.execution_ownership.active_owner == "candidate"
                or any(
                    step.action
                    in {
                        "handoff_execution_ownership",
                        "verify_active_candidate",
                        "rollback_execution_ownership",
                    }
                    and step.status == "RUNNING"
                    for step in record.steps
                )
            )
            for step in record.steps:
                if step.status in {"RUNNING", "PENDING"}:
                    step.status = "BLOCKED"
                    step.reason_codes = ["execution_interrupted"]
                    step.completed_at = now
            if record.validation is not None and record.validation.status == "RUNNING":
                record.validation.status = "BLOCKED"
                record.validation.reason_codes = ["execution_interrupted"]
                record.validation.completed_at = now
                record.validation.observed_at = now
            if record.post_switch_validation is not None and record.post_switch_validation.status == "RUNNING":
                record.post_switch_validation.status = "BLOCKED"
                record.post_switch_validation.reason_codes = ["execution_interrupted"]
                record.post_switch_validation.completed_at = now
                record.post_switch_validation.observed_at = now
            if record.active_candidate_validation is not None and record.active_candidate_validation.status == "RUNNING":
                record.active_candidate_validation.status = "BLOCKED"
                record.active_candidate_validation.reason_codes = ["execution_interrupted"]
                record.active_candidate_validation.completed_at = now
                record.active_candidate_validation.observed_at = now
            record.status = "BLOCKED"
            record.reason_codes = [
                "execution_interrupted",
                *(["routing_recovery_required"] if routing_interrupted else []),
                *(
                    ["execution_ownership_recovery_required"]
                    if ownership_interrupted
                    else []
                ),
            ]
            record.completed_at = now
            record.updated_at = now
            self.save(
                record,
                event_type="execution_recovered_blocked",
                actor="system",
                details={
                    "validation": (
                        record.validation.model_dump(mode="json", by_alias=True)
                        if record.validation is not None
                        else None
                    )
                },
            )

    def _insert_audit(
        self,
        connection: sqlite3.Connection,
        record: RuntimeExecutionRecord,
        *,
        event_type: str,
        actor: str,
        step_id: str | None = None,
        previous_status: ExecutionStatus | None = None,
        details: dict[str, Any] | None = None,
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
                reason_codes_json, details_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.plan_id,
                event_type,
                actor,
                step_id,
                previous_status,
                event_status,
                json.dumps(event_reasons),
                json.dumps(details or {}, separators=(",", ":")),
                record.updated_at.isoformat(),
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection


class RuntimeExecutionController:
    SUPPORTED_ACTIONS = {
        "create_candidate",
        "verify_ready",
        "validate_candidate_pre_activation",
        "handoff_execution_ownership",
        "verify_active_candidate",
        "switch_traffic",
        "verify_switched_traffic",
        "rollback_traffic",
        "rollback_execution_ownership",
    }

    def __init__(
        self,
        settings: Any,
        kube: Any,
        store: RuntimeExecutionStore,
        candidate_catalog: CandidateTemplateCatalog | None = None,
        validation_catalog: ValidationContractCatalog | None = None,
        validation_engine: CandidateValidationEngine | None = None,
        routing_catalog: RoutingContractCatalog | None = None,
        routing_engine: TrafficRoutingEngine | None = None,
        ownership_catalog: OwnershipContractCatalog | None = None,
        ownership_engine: ExecutionOwnershipEngine | None = None,
    ) -> None:
        self.settings = settings
        self.kube = kube
        self.store = store
        self.deployment_controller = DeploymentController(settings, kube)
        self.candidate_catalog = candidate_catalog or CandidateTemplateCatalog.load(
            settings.candidate_template_catalog_path
        )
        self.validation_catalog = validation_catalog or ValidationContractCatalog.load(
            settings.candidate_validation_contract_path
        )
        self.validation_engine = validation_engine or CandidateValidationEngine(kube)
        self.routing_catalog = routing_catalog or RoutingContractCatalog.load(
            settings.traffic_routing_contract_path
        )
        self.routing_engine = routing_engine or TrafficRoutingEngine(kube)
        self.ownership_catalog = ownership_catalog or OwnershipContractCatalog.load(
            settings.execution_ownership_contract_path
        )
        self.ownership_engine = ownership_engine or ExecutionOwnershipEngine(kube)
        self._tasks: dict[str, asyncio.Task[RuntimeExecutionRecord]] = {}
        self._task_lock = asyncio.Lock()

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
        record, created = self._reserve(plan, approval)
        if not created:
            return record
        return await self._run_safely(record, plan, approval)

    async def start(
        self,
        plan: RuntimeExecutionPlan,
        approval: RuntimeExecutionApproval,
    ) -> tuple[RuntimeExecutionRecord, bool]:
        record, created = self._reserve(plan, approval)
        if not created:
            return record, False
        async with self._task_lock:
            task = asyncio.create_task(
                self._run_safely(record, plan, approval),
                name=f"runtime-execution:{plan.plan_id}",
            )
            self._tasks[plan.plan_id] = task
            task.add_done_callback(
                lambda completed, plan_id=plan.plan_id: self._task_done(
                    plan_id,
                    completed,
                )
            )
        return record.model_copy(deep=True), True

    async def shutdown(self) -> None:
        async with self._task_lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reconcile_interrupted_routing(self) -> None:
        records = self.store.history(service_id=None, limit=self.store.history_limit)
        for record in records:
            if "routing_recovery_required" not in record.reason_codes or record.routing is None:
                continue
            try:
                contract = self._routing_contract(record.service_id)
                current = await self.routing_engine.observe(contract)
            except Exception:
                continue
            details = {
                "persisted": record.routing.model_dump(mode="json", by_alias=True),
                "observed": current.model_dump(mode="json", by_alias=True),
            }
            if (
                record.routing.before is not None
                and current.active_target == "source"
                and current.addresses == record.routing.before.addresses
            ):
                record.reason_codes = [item for item in record.reason_codes if item != "routing_recovery_required"]
                record.routing.active_target = "source"
                record.routing.rollback = current
                record.routing.reason_codes = ["traffic_rollback_succeeded"]
                self.store.release_routing_lock(record.service_id, record.plan_id)
                event_type = "routing_recovery_observed_source"
            else:
                event_type = "routing_recovery_required"
            record.updated_at = datetime.now(timezone.utc)
            self.store.save(record, event_type=event_type, actor="system", details=details)

    def _reserve(
        self,
        plan: RuntimeExecutionPlan,
        approval: RuntimeExecutionApproval,
    ) -> tuple[RuntimeExecutionRecord, bool]:
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
        return self.store.reserve(record)

    async def _run_safely(
        self,
        record: RuntimeExecutionRecord,
        plan: RuntimeExecutionPlan,
        approval: RuntimeExecutionApproval,
    ) -> RuntimeExecutionRecord:
        try:
            return await self._run_reserved(record, plan, approval)
        except asyncio.CancelledError:
            return self._interrupt_record(record, approval.approved_by)
        except Exception:
            current = next(
                (index for index, step in enumerate(record.steps) if step.status == "RUNNING"),
                None,
            )
            if current is not None:
                return self._fail_step(
                    record,
                    current,
                    ["execution_internal_error"],
                    approval.approved_by,
                )
            return self._finish_blocked(
                record,
                approval.approved_by,
                ["execution_internal_error"],
            )

    async def _run_reserved(
        self,
        record: RuntimeExecutionRecord,
        plan: RuntimeExecutionPlan,
        approval: RuntimeExecutionApproval,
    ) -> RuntimeExecutionRecord:
        errors, prepared = await self._prepare_request(plan)
        if plan.status != "planned":
            errors = ["execution_plan_not_planned", *plan.reason_codes]
        if errors or prepared is None:
            return self._finish_blocked(record, approval.approved_by, errors)

        record.candidate_workload = RuntimeExecutionCandidateWorkload(
            namespace=prepared.manifest["metadata"]["namespace"],
            name=prepared.manifest["metadata"]["name"],
            target_node=plan.placement.selected_node,
            template_version=prepared.template.template_version,
            state_policy=prepared.template.state_policy.type,
        )
        record.candidate_pvcs = []

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
                if record.routing is not None and record.routing.active_target == "candidate":
                    self.store.release_routing_lock(record.service_id, record.plan_id)
                if (
                    record.execution_ownership is not None
                    and record.execution_ownership.active_owner == "candidate"
                ):
                    self.store.release_ownership_lock(
                        record.service_id, record.plan_id
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
                failure = await self._create_candidate(prepared)
                if failure is None:
                    record.candidate_created = True
            elif planned_step.action == "verify_ready":
                failure = await self._verify_ready(plan, prepared.request)
                if failure is None:
                    record.candidate_ready = True
            elif planned_step.action == "validate_candidate_pre_activation":
                validation = await self._validate_candidate_pre_activation(
                    record,
                    prepared,
                    approval.approved_by,
                    plan.plan_id,
                )
                record.validation = validation
                failure = (
                    None
                    if validation.status == "SUCCEEDED"
                    else validation.reason_codes
                )
            elif planned_step.action == "handoff_execution_ownership":
                failure = await self._handoff_execution_ownership(
                    record,
                    prepared,
                    approval.approved_by,
                )
            elif planned_step.action == "verify_active_candidate":
                validation = await self._verify_active_candidate(
                    record,
                    prepared,
                    approval.approved_by,
                    plan.plan_id,
                )
                record.active_candidate_validation = validation
                failure = (
                    None
                    if validation.status == "SUCCEEDED"
                    else validation.reason_codes
                )
            elif planned_step.action == "switch_traffic":
                failure = await self._switch_traffic(
                    record,
                    prepared,
                    approval.approved_by,
                )
            elif planned_step.action == "verify_switched_traffic":
                validation = await self._verify_switched_traffic(
                    record,
                    prepared,
                    approval.approved_by,
                )
                record.post_switch_validation = validation
                failure = None if validation.status == "SUCCEEDED" else validation.reason_codes
            else:
                failure = "unsupported_step"
            if failure is not None:
                if planned_step.action in {
                    "handoff_execution_ownership",
                    "verify_active_candidate",
                }:
                    return await self._fail_with_ownership_rollback(
                        record,
                        index,
                        failure,
                        approval.approved_by,
                        prepared,
                    )
                if planned_step.action in {"switch_traffic", "verify_switched_traffic"} and record.routing is not None:
                    return await self._fail_with_traffic_rollback(
                        record,
                        index,
                        failure,
                        approval.approved_by,
                        prepared,
                    )
                if planned_step.action in {"switch_traffic", "verify_switched_traffic"}:
                    return await self._fail_with_ownership_rollback(
                        record,
                        index,
                        failure,
                        approval.approved_by,
                        prepared,
                    )
                if planned_step.action == "switch_traffic":
                    self.store.release_routing_lock(record.service_id, record.plan_id)
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

    def _task_done(
        self,
        plan_id: str,
        completed: asyncio.Task[RuntimeExecutionRecord],
    ) -> None:
        current = self._tasks.get(plan_id)
        if current is completed:
            self._tasks.pop(plan_id, None)

    async def _prepare_request(
        self,
        plan: RuntimeExecutionPlan,
    ) -> tuple[list[str], PreparedCandidate | None]:
        errors: list[str] = []
        if plan.status != "planned" or plan.placement is None:
            return ["execution_plan_not_planned"], None
        if plan.placement.requirements is None:
            return ["placement_requirements_missing"], None
        if plan.plan_id == "" or not _PLAN_ID.fullmatch(plan.plan_id):
            return ["invalid_plan_id"], None
        source_target = next(
            (
                target
                for step in plan.steps
                for target in step.targets
                if target.workload.role == "current"
            ),
            None,
        )
        candidate_target = next(
            (
                target
                for step in plan.steps
                for target in step.targets
                if target.workload.role == "candidate"
            ),
            None,
        )
        if source_target is None or candidate_target is None:
            return ["execution_targets_missing"], None
        source = source_target.workload
        candidate = candidate_target.workload
        if source.kind != "Deployment" or candidate.kind != "Deployment":
            return ["source_workload_kind_unsupported"], None

        approved, catalog_error = self.candidate_catalog.resolve(plan.service_id)
        if approved is None:
            return [catalog_error or "candidate_template_not_found"], None
        validation_contract, validation_error = self.validation_catalog.resolve(
            plan.service_id
        )
        if validation_contract is None:
            return [
                validation_error or "candidate_validation_contract_unsupported"
            ], None
        ownership_contract, ownership_error = self.ownership_catalog.resolve(
            plan.service_id
        )
        if ownership_contract is None:
            return [
                ownership_error or "execution_ownership_contract_not_found"
            ], None
        if (
            ownership_contract.source.namespace != source.namespace
            or ownership_contract.source.workload != source.name
            or ownership_contract.source.holder_identity != source.name
        ):
            return ["execution_ownership_contract_invalid"], None
        candidate_port = next(
            (
                item.get("containerPort")
                for item in approved.pod_template.container.ports
                if item.get("name") == validation_contract.candidate_port_name
            ),
            None,
        )
        if not isinstance(candidate_port, int) or isinstance(candidate_port, bool):
            return ["candidate_validation_contract_unsupported"], None
        source_contract = approved.source_contract
        if (
            source.namespace != source_contract.namespace
            or source.kind != source_contract.kind
            or source.name != source_contract.name
        ):
            return ["candidate_template_mismatch"], None
        if (
            candidate.namespace != self.settings.deployment_target_namespace
            or candidate.namespace not in approved.allowed_namespaces
        ):
            return ["candidate_namespace_not_allowed"], None
        try:
            expected_name = approved.candidate_name(
                source=source.name,
                action=plan.action,
                plan_id=plan.plan_id,
            )
        except ValueError:
            return ["candidate_contract_invalid"], None
        if candidate.name != expected_name:
            return ["candidate_template_mismatch"], None
        if (
            plan.placement.selected_node is None
            or candidate_target.node != plan.placement.selected_node
            or plan.placement.service_profile.namespace != source_contract.namespace
            or plan.placement.service_profile.service != plan.service_id
        ):
            return ["candidate_template_mismatch"], None

        try:
            deployment = await self.kube.read_deployment(source.namespace, source.name)
        except KubeDeploymentError as exc:
            return [exc.reason_code], None
        source_data = _object_dict(deployment)
        errors.extend(_validate_source_contract(source_data, approved))

        errors.extend(await self._validate_source_storage(source.namespace, approved))
        errors.extend(await self._validate_target_node(plan, approved))

        manifest = build_candidate_deployment_manifest(
            approved,
            plan.placement,
            namespace=candidate.namespace,
            name=candidate.name,
            plan_id=plan.plan_id,
        )
        container = approved.pod_template.container
        source_selector: dict[str, str] = {}
        try:
            service = await self.kube.read_service(
                source_contract.namespace,
                source_contract.service_name,
            )
        except KubeDeploymentError as exc:
            errors.append(exc.reason_code)
        else:
            selector = _get(_object_dict(service), "spec", "selector") or {}
            source_selector = {
                str(key): str(value) for key, value in selector.items()
            }
            service_ports = _get(_object_dict(service), "spec", "ports") or []
            candidate_labels = _get(manifest, "spec", "template", "metadata", "labels") or {}
            if not selector or all(
                candidate_labels.get(key) == value for key, value in selector.items()
            ):
                errors.append("candidate_service_selector_conflict")
            if not _service_ports_compatible(service_ports, container.ports):
                errors.append("candidate_template_mismatch")
        ports = container.ports
        http_get = (container.readiness_probe or {}).get("httpGet", {})
        try:
            request = DeploymentCreateRequest(
                deployment_name=candidate.name,
                image=container.image,
                placement=PlacementSelectionRequest(
                    namespace=plan.placement.service_profile.namespace,
                    service=plan.placement.service_profile.service,
                    architecture=plan.placement.requirements.architecture,
                    accelerator=plan.placement.requirements.accelerator,
                    accelerator_units=plan.placement.requirements.accelerator_units,
                ),
                container_port=ports[0].get("containerPort") if ports else None,
                readiness_path=http_get.get("path"),
            )
        except Exception:
            return ["candidate_contract_invalid"], None
        rejected = self.deployment_controller.validate_request(
            request,
            plan.placement,
            plan.plan_id,
        )
        if rejected is not None:
            errors.extend(rejected.reason_codes)
        errors = _unique(errors)
        if errors:
            return errors, None
        return [], PreparedCandidate(
            request=request,
            template=approved,
            validation_contract=validation_contract,
            ownership_contract=ownership_contract,
            manifest=manifest,
            source_namespace=source.namespace,
            source_selector=source_selector,
            source_node=source_target.node,
            candidate_port=candidate_port,
        )

    async def _validate_source_storage(
        self,
        namespace: str,
        approved: CandidateWorkloadTemplate,
    ) -> list[str]:
        source_volume = approved.source_contract.source_state_volume
        storage = approved.state_policy.candidate_storage
        if approved.state_policy.type not in {"stateless", "fresh_state"}:
            return ["state_policy_unsupported"]
        if storage.type == "new_pvc":
            return ["state_policy_unsupported"]
        if source_volume is None:
            return (
                ["source_pvc_not_migratable"]
                if storage.type == "source_pvc"
                or storage.reuse_source_pvc
                or storage.copy_existing_data
                else []
            )
        try:
            pvc = await self.kube.read_persistent_volume_claim(
                namespace,
                source_volume.claim_name,
            )
        except KubeDeploymentError as exc:
            return [exc.reason_code]
        pvc_data = _object_dict(pvc)
        access_modes = _get(pvc_data, "spec", "accessModes") or []
        storage_class = _get(pvc_data, "spec", "storageClassName")
        errors: list[str] = []
        if (
            sorted(access_modes) != sorted(source_volume.required_access_modes)
            or storage_class != source_volume.storage_class_name
        ):
            errors.append("candidate_template_mismatch")
        try:
            await self.kube.read_storage_class(source_volume.storage_class_name)
        except KubeDeploymentError:
            errors.append("storage_class_unavailable")
        if (
            storage.type == "source_pvc"
            or storage.reuse_source_pvc
            or storage.copy_existing_data
        ):
            errors.append("source_pvc_not_migratable")
        return errors

    async def _validate_target_node(
        self,
        plan: RuntimeExecutionPlan,
        approved: CandidateWorkloadTemplate,
    ) -> list[str]:
        assert plan.placement is not None
        assert plan.placement.requirements is not None
        requirements = plan.placement.requirements
        selected_node = plan.placement.selected_node
        if selected_node is None:
            return ["target_node_unschedulable"]
        constraints = approved.constraints
        errors: list[str] = []
        if requirements.architecture not in constraints.architectures:
            errors.append("candidate_template_mismatch")
        if requirements.accelerator != constraints.accelerator:
            errors.append("candidate_template_mismatch")
        if requirements.accelerator_units != constraints.accelerator_units:
            errors.append("candidate_template_mismatch")

        requests = approved.pod_template.container.resources.get("requests", {})
        if not quantity_matches(requests.get("cpu"), requirements.cpu_cores):
            errors.append("candidate_template_mismatch")
        if not quantity_matches(requests.get("memory"), requirements.memory_bytes):
            errors.append("candidate_template_mismatch")
        try:
            snapshots = await self.kube.get_scheduling_resource_snapshots()
        except (KubeResourceReadError, KubeDeploymentError):
            return _unique([*errors, "target_node_state_unavailable"])
        snapshot = next((item for item in snapshots if item.node == selected_node), None)
        if snapshot is None or not snapshot.ready or snapshot.unschedulable:
            errors.append("target_node_unschedulable")
            return _unique(errors)
        if snapshot.architecture not in constraints.architectures:
            errors.append("architecture_mismatch")
        if constraints.accelerator is not None:
            observed_accelerator = _node_accelerator(snapshot)
            if observed_accelerator != constraints.accelerator:
                errors.append("accelerator_mismatch")
        available_cpu = snapshot.allocatable.cpu_cores - snapshot.requested.cpu_cores
        available_memory = snapshot.allocatable.memory_bytes - snapshot.requested.memory_bytes
        if (
            available_cpu < requirements.cpu_cores
            or available_memory < requirements.memory_bytes
        ):
            errors.append("target_node_resource_insufficient")
        for name, amount in constraints.accelerator_units.items():
            available = (
                snapshot.allocatable.accelerator_units.get(name, 0)
                - snapshot.requested.accelerator_units.get(name, 0)
            )
            if available < amount:
                errors.append("accelerator_mismatch")
        return _unique(errors)

    async def _create_candidate(
        self,
        prepared: PreparedCandidate,
    ) -> str | None:
        request = prepared.request
        namespace = prepared.manifest["metadata"]["namespace"]
        try:
            if await self.kube.deployment_exists(namespace, request.deployment_name):
                return "candidate_workload_already_exists"
            await self.kube.create_deployment(namespace, prepared.manifest)
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

    async def _validate_candidate_pre_activation(
        self,
        record: RuntimeExecutionRecord,
        prepared: PreparedCandidate,
        actor: str,
        plan_id: str,
    ) -> CandidateValidationResult:
        async def persist(snapshot: CandidateValidationResult) -> None:
            record.validation = snapshot
            record.updated_at = snapshot.observed_at
            self.store.save(
                record,
                event_type="candidate_validation_observed",
                actor=actor,
                step_id="validate-candidate-pre-activation",
                previous_status="RUNNING",
                details={
                    "validation": snapshot.model_dump(
                        mode="json",
                        by_alias=True,
                    )
                },
            )

        try:
            contract = prepared.validation_contract.for_phase("pre_activation")
        except ValueError:
            return CandidateValidationResult(
                status="BLOCKED",
                reason_codes=["candidate_validation_contract_unsupported"],
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                required_consecutive_successes=1,
                minimum_stable_seconds=0,
                observed_at=datetime.now(timezone.utc),
            )
        return await self.validation_engine.validate(
            contract=contract,
            candidate_namespace=prepared.manifest["metadata"]["namespace"],
            candidate_name=prepared.manifest["metadata"]["name"],
            candidate_node=prepared.manifest["spec"]["template"]["spec"]["nodeSelector"][
                "kubernetes.io/hostname"
            ],
            candidate_port=prepared.candidate_port,
            plan_id=plan_id,
            source_namespace=prepared.source_namespace,
            source_selector=prepared.source_selector,
            source_node=prepared.source_node,
            observer=persist,
            frames_processed_pointer="/counters/shadowFramesProcessed",
        )

    async def _handoff_execution_ownership(
        self,
        record: RuntimeExecutionRecord,
        prepared: PreparedCandidate,
        actor: str,
    ) -> str | None:
        if record.validation is None or record.validation.status != "SUCCEEDED":
            return "candidate_pre_activation_not_validated"
        if not self.store.acquire_ownership_lock(record.service_id, record.plan_id):
            return "execution_ownership_state_conflict"

        async def snapshot_observer(
            ownership: RuntimeExecutionOwnership,
        ) -> None:
            record.execution_ownership = ownership
            record.updated_at = datetime.now(timezone.utc)
            self.store.save(
                record,
                event_type="pre_handoff_lease_snapshot",
                actor=actor,
                step_id="handoff-execution-ownership",
                previous_status="RUNNING",
                details={
                    "executionOwnership": ownership.model_dump(
                        mode="json", by_alias=True
                    )
                },
            )

        try:
            record.execution_ownership = await self.ownership_engine.handoff(
                contract=prepared.ownership_contract,
                candidate_name=prepared.manifest["metadata"]["name"],
                observer=snapshot_observer,
            )
        except ExecutionOwnershipError as exc:
            return exc.reason_code
        record.updated_at = datetime.now(timezone.utc)
        self.store.save(
            record,
            event_type="execution_ownership_handed_off",
            actor=actor,
            step_id="handoff-execution-ownership",
            previous_status="RUNNING",
            details={
                "executionOwnership": record.execution_ownership.model_dump(
                    mode="json", by_alias=True
                )
            },
        )
        return None

    async def _verify_active_candidate(
        self,
        record: RuntimeExecutionRecord,
        prepared: PreparedCandidate,
        actor: str,
        plan_id: str,
    ) -> CandidateValidationResult:
        if (
            record.execution_ownership is None
            or record.execution_ownership.active_owner != "candidate"
        ):
            now = datetime.now(timezone.utc)
            return CandidateValidationResult(
                status="BLOCKED",
                reason_codes=["candidate_not_active"],
                started_at=now,
                completed_at=now,
                required_consecutive_successes=1,
                minimum_stable_seconds=0,
                observed_at=now,
            )
        contract = prepared.validation_contract.for_phase("active")

        async def persist(snapshot: CandidateValidationResult) -> None:
            record.active_candidate_validation = snapshot
            record.updated_at = snapshot.observed_at
            self.store.save(
                record,
                event_type="active_candidate_validation_observed",
                actor=actor,
                step_id="verify-active-candidate",
                previous_status="RUNNING",
                details={
                    "executionOwnership": record.execution_ownership.model_dump(
                        mode="json", by_alias=True
                    ),
                    "validation": snapshot.model_dump(mode="json", by_alias=True),
                },
            )

        return await self.validation_engine.validate(
            contract=contract,
            candidate_namespace=prepared.manifest["metadata"]["namespace"],
            candidate_name=prepared.manifest["metadata"]["name"],
            candidate_node=prepared.manifest["spec"]["template"]["spec"][
                "nodeSelector"
            ]["kubernetes.io/hostname"],
            candidate_port=prepared.candidate_port,
            plan_id=plan_id,
            source_namespace=prepared.source_namespace,
            source_selector=prepared.source_selector,
            source_node=prepared.source_node,
            observer=persist,
            minimum_frames_processed_exclusive=0,
            frames_processed_pointer="/counters/framesProcessed",
        )

    def _routing_contract(self, service_id: str) -> TrafficRoutingContract:
        contract, error = self.routing_catalog.resolve(service_id)
        if contract is None:
            raise TrafficRoutingError(error or "routing_contract_not_found")
        return contract

    async def _switch_traffic(
        self,
        record: RuntimeExecutionRecord,
        prepared: PreparedCandidate,
        actor: str,
    ) -> str | list[str] | None:
        if record.validation is None or record.validation.status != "SUCCEEDED":
            return "candidate_not_validated"
        try:
            contract = self._routing_contract(record.service_id)
        except TrafficRoutingError as exc:
            return exc.reason_code
        if not self.store.acquire_routing_lock(record.service_id, record.plan_id):
            return "routing_state_conflict"

        async def snapshot_observer(routing: RuntimeExecutionRouting) -> None:
            record.routing = routing
            record.updated_at = datetime.now(timezone.utc)
            self.store.save(
                record,
                event_type="pre_switch_routing_snapshot",
                actor=actor,
                step_id="switch-traffic",
                previous_status="RUNNING",
                details={"routing": routing.model_dump(mode="json", by_alias=True)},
            )

        try:
            record.routing = await self.routing_engine.switch(
                contract=contract,
                plan_id=record.plan_id,
                candidate_namespace=prepared.manifest["metadata"]["namespace"],
                candidate_name=prepared.manifest["metadata"]["name"],
                candidate_node=prepared.manifest["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/hostname"],
                snapshot_observer=snapshot_observer,
            )
        except TrafficRoutingError as exc:
            return exc.reason_code
        except KubeDeploymentError as exc:
            return exc.reason_code
        record.updated_at = datetime.now(timezone.utc)
        self.store.save(
            record,
            event_type="endpoint_slice_switched",
            actor=actor,
            step_id="switch-traffic",
            previous_status="RUNNING",
            details={"routing": record.routing.model_dump(mode="json", by_alias=True)},
        )
        return None

    async def _verify_switched_traffic(
        self,
        record: RuntimeExecutionRecord,
        prepared: PreparedCandidate,
        actor: str,
    ) -> CandidateValidationResult:
        contract = self._routing_contract(record.service_id)
        post_contract = prepared.validation_contract.model_copy(deep=True)
        post_contract.stabilization.minimum_stable_seconds = contract.switch_policy.post_switch_observation_seconds
        post_contract.stabilization.poll_interval_seconds = contract.switch_policy.poll_interval_seconds
        post_contract.stabilization.timeout_seconds = contract.switch_policy.timeout_seconds
        post_contract.stabilization.required_consecutive_successes = contract.switch_policy.required_consecutive_successes
        baseline = (
            record.active_candidate_validation.candidate.frames_processed
            if record.active_candidate_validation is not None
            and record.active_candidate_validation.candidate is not None
            else None
        )

        async def persist(snapshot: CandidateValidationResult) -> None:
            mapped = _post_switch_result(snapshot)
            record.post_switch_validation = mapped
            record.updated_at = mapped.observed_at
            self.store.save(
                record,
                event_type="post_switch_validation_observed",
                actor=actor,
                step_id="verify-switched-traffic",
                previous_status="RUNNING",
                details={
                    "routing": record.routing.model_dump(mode="json", by_alias=True) if record.routing else None,
                    "validation": mapped.model_dump(mode="json", by_alias=True),
                },
            )

        result = await self.validation_engine.validate(
            contract=post_contract,
            candidate_namespace=prepared.manifest["metadata"]["namespace"],
            candidate_name=prepared.manifest["metadata"]["name"],
            candidate_node=prepared.manifest["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/hostname"],
            candidate_port=prepared.candidate_port,
            plan_id=record.plan_id,
            source_namespace=prepared.source_namespace,
            source_selector=prepared.source_selector,
            source_node=prepared.source_node,
            observer=persist,
            candidate_base_url=f"http://{contract.service_name}.{contract.namespace}.svc.cluster.local:{contract.port}",
            minimum_frames_processed_exclusive=baseline,
            frames_processed_pointer=(
                contract.switch_policy.counter_pointer
                or "/counters/framesProcessed"
            ),
        )
        return _post_switch_result(result)

    async def _fail_with_ownership_rollback(
        self,
        record: RuntimeExecutionRecord,
        failed_index: int,
        reason: str | list[str],
        actor: str,
        prepared: PreparedCandidate,
    ) -> RuntimeExecutionRecord:
        reasons = _unique([reason] if isinstance(reason, str) else reason)
        now = datetime.now(timezone.utc)
        failed = record.steps[failed_index]
        failed.status = "FAILED"
        failed.reason_codes = reasons
        failed.completed_at = now
        self.store.save(
            record,
            event_type="step_failed",
            actor=actor,
            step_id=failed.step_id,
            previous_status="RUNNING",
        )
        rollback_index = next(
            (
                index
                for index, item in enumerate(record.steps)
                if item.action == "rollback_execution_ownership"
            ),
            None,
        )
        if rollback_index is None:
            self.store.release_ownership_lock(record.service_id, record.plan_id)
            return self._fail_step(record, failed_index, reasons, actor)
        for later in record.steps[failed_index + 1 : rollback_index]:
            later.status = "BLOCKED"
            later.reason_codes = ["previous_step_blocked"]
            later.completed_at = now
        rollback_step = record.steps[rollback_index]
        rollback_step.status = "RUNNING"
        rollback_step.started_at = now
        rollback_step.reason_codes = ["execution_ownership_rollback_started"]
        self.store.save(
            record,
            event_type="execution_ownership_rollback_started",
            actor=actor,
            step_id=rollback_step.step_id,
            previous_status="PENDING",
            details={
                "executionOwnership": (
                    record.execution_ownership.model_dump(mode="json", by_alias=True)
                    if record.execution_ownership is not None
                    else None
                )
            },
        )
        rollback_failure = await self._rollback_execution_ownership(
            record,
            prepared,
            actor,
        )
        completed = datetime.now(timezone.utc)
        if rollback_failure is None:
            rollback_step.status = "SUCCEEDED"
            rollback_step.reason_codes = ["execution_ownership_rollback_succeeded"]
            event_type = "execution_ownership_rollback_succeeded"
            record.reason_codes = reasons
        else:
            rollback_step.status = "FAILED"
            rollback_step.reason_codes = _unique(
                [rollback_failure, "execution_ownership_rollback_failed"]
            )
            event_type = "execution_ownership_rollback_failed"
            record.reason_codes = _unique(
                [*reasons, "execution_ownership_rollback_failed"]
            )
        rollback_step.completed_at = completed
        record.status = "FAILED"
        record.completed_at = completed
        record.updated_at = completed
        self.store.save(
            record,
            event_type=event_type,
            actor=actor,
            step_id=rollback_step.step_id,
            previous_status="RUNNING",
            details={
                "executionOwnership": (
                    record.execution_ownership.model_dump(mode="json", by_alias=True)
                    if record.execution_ownership is not None
                    else None
                )
            },
        )
        self.store.save(record, event_type="execution_failed", actor=actor)
        return record

    async def _rollback_execution_ownership(
        self,
        record: RuntimeExecutionRecord,
        prepared: PreparedCandidate,
        actor: str,
    ) -> str | None:
        ownership = record.execution_ownership
        if ownership is None:
            self.store.release_ownership_lock(record.service_id, record.plan_id)
            return None
        try:
            record.execution_ownership = await self.ownership_engine.rollback(
                contract=prepared.ownership_contract,
                ownership=ownership,
            )
        except ExecutionOwnershipError as exc:
            return exc.reason_code
        finally:
            self.store.release_ownership_lock(record.service_id, record.plan_id)
        record.updated_at = datetime.now(timezone.utc)
        self.store.save(
            record,
            event_type="execution_ownership_restored_to_source",
            actor=actor,
            details={
                "executionOwnership": record.execution_ownership.model_dump(
                    mode="json", by_alias=True
                )
            },
        )
        return None

    async def _fail_with_traffic_rollback(
        self,
        record: RuntimeExecutionRecord,
        failed_index: int,
        reason: str | list[str],
        actor: str,
        prepared: PreparedCandidate,
    ) -> RuntimeExecutionRecord:
        reasons = _unique([reason] if isinstance(reason, str) else reason)
        now = datetime.now(timezone.utc)
        failed = record.steps[failed_index]
        failed.status = "FAILED"
        failed.reason_codes = reasons
        failed.completed_at = now
        self.store.save(record, event_type="step_failed", actor=actor, step_id=failed.step_id, previous_status="RUNNING")

        rollback_index = next((i for i, item in enumerate(record.steps) if item.action == "rollback_traffic"), None)
        if rollback_index is None or record.routing is None:
            self.store.release_routing_lock(record.service_id, record.plan_id)
            return self._fail_step(record, failed_index, reasons, actor)
        for later in record.steps[failed_index + 1:rollback_index]:
            later.status = "BLOCKED"
            later.reason_codes = ["previous_step_blocked"]
            later.completed_at = now
        rollback_step = record.steps[rollback_index]
        rollback_step.status = "RUNNING"
        rollback_step.started_at = now
        rollback_step.reason_codes = ["traffic_rollback_started"]
        self.store.save(record, event_type="traffic_rollback_started", actor=actor, step_id=rollback_step.step_id, previous_status="PENDING", details={"routing": record.routing.model_dump(mode="json", by_alias=True)})
        try:
            contract = self._routing_contract(record.service_id)
            record.routing = await self.routing_engine.rollback(contract=contract, plan_id=record.plan_id, routing=record.routing)
        except (TrafficRoutingError, KubeDeploymentError) as exc:
            rollback_step.status = "FAILED"
            rollback_step.reason_codes = [getattr(exc, "reason_code", "traffic_rollback_failed"), "traffic_rollback_failed"]
            rollback_step.completed_at = datetime.now(timezone.utc)
            record.reason_codes = _unique([*reasons, "traffic_rollback_failed"])
            event_type = "traffic_rollback_failed"
        else:
            rollback_step.status = "SUCCEEDED"
            rollback_step.reason_codes = ["traffic_rollback_succeeded"]
            rollback_step.completed_at = datetime.now(timezone.utc)
            record.reason_codes = reasons
            self.store.release_routing_lock(record.service_id, record.plan_id)
            event_type = "traffic_rollback_succeeded"
        record.status = "FAILED"
        record.completed_at = rollback_step.completed_at
        record.updated_at = rollback_step.completed_at
        self.store.save(record, event_type=event_type, actor=actor, step_id=rollback_step.step_id, previous_status="RUNNING", details={"routing": record.routing.model_dump(mode="json", by_alias=True)})
        ownership_rollback_index = next(
            (
                index
                for index, item in enumerate(record.steps)
                if item.action == "rollback_execution_ownership"
            ),
            None,
        )
        if ownership_rollback_index is not None:
            ownership_step = record.steps[ownership_rollback_index]
            if event_type == "traffic_rollback_succeeded":
                ownership_step.status = "RUNNING"
                ownership_step.started_at = datetime.now(timezone.utc)
                ownership_step.reason_codes = ["execution_ownership_rollback_started"]
                self.store.save(
                    record,
                    event_type="execution_ownership_rollback_started",
                    actor=actor,
                    step_id=ownership_step.step_id,
                    previous_status="PENDING",
                )
                ownership_failure = await self._rollback_execution_ownership(
                    record, prepared, actor
                )
                ownership_step.completed_at = datetime.now(timezone.utc)
                if ownership_failure is None:
                    ownership_step.status = "SUCCEEDED"
                    ownership_step.reason_codes = [
                        "execution_ownership_rollback_succeeded"
                    ]
                    ownership_event = "execution_ownership_rollback_succeeded"
                else:
                    ownership_step.status = "FAILED"
                    ownership_step.reason_codes = _unique(
                        [ownership_failure, "execution_ownership_rollback_failed"]
                    )
                    record.reason_codes = _unique(
                        [*record.reason_codes, "execution_ownership_rollback_failed"]
                    )
                    ownership_event = "execution_ownership_rollback_failed"
                record.completed_at = ownership_step.completed_at
                record.updated_at = ownership_step.completed_at
                self.store.save(
                    record,
                    event_type=ownership_event,
                    actor=actor,
                    step_id=ownership_step.step_id,
                    previous_status="RUNNING",
                )
            else:
                ownership_step.status = "BLOCKED"
                ownership_step.reason_codes = ["traffic_rollback_failed"]
                ownership_step.completed_at = datetime.now(timezone.utc)
                self.store.save(
                    record,
                    event_type="step_blocked",
                    actor=actor,
                    step_id=ownership_step.step_id,
                    previous_status="PENDING",
                )
        self.store.save(record, event_type="execution_failed", actor=actor)
        return record

    def _fail_step(
        self,
        record: RuntimeExecutionRecord,
        index: int,
        reason: str | list[str],
        actor: str,
    ) -> RuntimeExecutionRecord:
        now = datetime.now(timezone.utc)
        reasons = _unique([reason] if isinstance(reason, str) else reason)
        step = record.steps[index]
        step.status = "FAILED"
        step.reason_codes = reasons
        step.completed_at = now
        for planned, later in zip(
            record.plan.steps[index + 1 :],
            record.steps[index + 1 :],
            strict=True,
        ):
            later.status = "BLOCKED"
            later.reason_codes = [
                "unsupported_step"
                if planned.execution_mode == "on_failure"
                else "previous_step_blocked"
            ]
            later.completed_at = now
        record.status = "FAILED"
        record.reason_codes = reasons
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

    def _interrupt_record(
        self,
        record: RuntimeExecutionRecord,
        actor: str,
    ) -> RuntimeExecutionRecord:
        now = datetime.now(timezone.utc)
        for step in record.steps:
            if step.status in {"PENDING", "RUNNING"}:
                step.status = "BLOCKED"
                step.reason_codes = ["execution_interrupted"]
                step.completed_at = now
        if record.validation is not None and record.validation.status == "RUNNING":
            record.validation.status = "BLOCKED"
            record.validation.reason_codes = ["execution_interrupted"]
            record.validation.completed_at = now
            record.validation.observed_at = now
        if record.post_switch_validation is not None and record.post_switch_validation.status == "RUNNING":
            record.post_switch_validation.status = "BLOCKED"
            record.post_switch_validation.reason_codes = ["execution_interrupted"]
            record.post_switch_validation.completed_at = now
            record.post_switch_validation.observed_at = now
        if record.active_candidate_validation is not None and record.active_candidate_validation.status == "RUNNING":
            record.active_candidate_validation.status = "BLOCKED"
            record.active_candidate_validation.reason_codes = ["execution_interrupted"]
            record.active_candidate_validation.completed_at = now
            record.active_candidate_validation.observed_at = now
        record.status = "BLOCKED"
        record.reason_codes = [
            "execution_interrupted",
            *(["routing_recovery_required"] if record.routing is not None else []),
            *(
                ["execution_ownership_recovery_required"]
                if record.execution_ownership is not None
                else []
            ),
        ]
        record.completed_at = now
        record.updated_at = now
        self.store.save(
            record,
            event_type="execution_interrupted",
            actor=actor,
            details={
                "validation": (
                    record.validation.model_dump(mode="json", by_alias=True)
                    if record.validation is not None
                    else None
                )
            },
        )
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
        for planned, later in zip(
            record.plan.steps[index + 1 :],
            record.steps[index + 1 :],
            strict=True,
        ):
            later.status = "BLOCKED"
            later.reason_codes = [
                "unsupported_step"
                if planned.execution_mode == "on_failure"
                else "previous_step_blocked"
            ]
            later.completed_at = now


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _post_switch_result(value: CandidateValidationResult) -> CandidateValidationResult:
    result = value.model_copy(deep=True)
    mapping = {
        "candidate_validation_succeeded": "post_switch_validation_succeeded",
        "candidate_validation_timeout": "post_switch_validation_timeout",
        "candidate_endpoint_unreachable": "post_switch_health_failed",
        "candidate_input_unavailable": "post_switch_input_unavailable",
        "candidate_input_stale": "post_switch_input_stale",
        "candidate_model_not_ready": "post_switch_model_not_ready",
        "candidate_inference_not_observed": "post_switch_inference_not_observed",
        "candidate_latency_slo_violated": "post_switch_latency_slo_violated",
        "candidate_not_ready": "post_switch_health_failed",
    }
    result.reason_codes = _unique([mapping.get(item, item) for item in result.reason_codes])
    for check in result.checks:
        check.reason_codes = _unique([mapping.get(item, item) for item in check.reason_codes])
    return result


def _object_dict(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {_camel_key(str(key)): _object_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_object_dict(item) for item in value]
    if hasattr(value, "to_dict"):
        return _object_dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            _camel_key(key): _object_dict(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _camel_key(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


def _get(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


def _validate_source_contract(
    deployment: dict[str, Any],
    approved: CandidateWorkloadTemplate,
) -> list[str]:
    deployment_spec = _get(deployment, "spec") or {}
    if (
        deployment_spec.get("replicas") != 1
        or _get(deployment_spec, "strategy", "type") != "Recreate"
    ):
        return ["candidate_template_mismatch"]
    pod_spec = _get(deployment, "spec", "template", "spec") or {}
    pod_labels = _get(deployment, "spec", "template", "metadata", "labels") or {}
    containers = pod_spec.get("containers") or []
    if len(containers) != 1 or pod_spec.get("initContainers"):
        return ["candidate_template_mismatch"]
    source = approved.source_contract
    if pod_labels.get("edge-ai.io/deployment") != source.name:
        return ["candidate_template_mismatch"]
    actual = _compact(containers[0])
    expected = _compact(
        approved.pod_template.container.model_dump(by_alias=True, exclude_none=True)
    )
    if actual.get("name") != source.container_name:
        return ["candidate_template_mismatch"]
    if actual.get("image") not in source.compatible_images:
        return ["candidate_template_mismatch"]

    exact_fields = (
        "name",
        "imagePullPolicy",
        "env",
        "ports",
        "startupProbe",
        "readinessProbe",
        "livenessProbe",
        "securityContext",
        "volumeMounts",
    )
    if any(actual.get(field) != expected.get(field) for field in exact_fields):
        return ["candidate_template_mismatch"]
    if any(actual.get(field) for field in ("envFrom", "command", "args")):
        return ["candidate_template_mismatch"]
    actual_resources = actual.get("resources") or {}
    expected_resources = expected.get("resources") or {}
    if set(actual_resources) != set(expected_resources):
        return ["candidate_template_mismatch"]
    for category in ("requests", "limits"):
        actual_quantities = actual_resources.get(category) or {}
        expected_quantities = expected_resources.get(category) or {}
        if set(actual_quantities) != set(expected_quantities):
            return ["candidate_template_mismatch"]
        if any(
            not quantity_matches(actual_quantities[name], expected_quantities[name])
            for name in expected_quantities
        ):
            return ["candidate_template_mismatch"]

    pod_expected = approved.pod_template
    if (
        pod_spec.get("automountServiceAccountToken")
        != pod_expected.automount_service_account_token
        or pod_spec.get("serviceAccountName")
        != pod_expected.service_account_name
        or pod_spec.get("terminationGracePeriodSeconds")
        != pod_expected.termination_grace_period_seconds
        or _compact(pod_spec.get("securityContext") or {})
        != _compact(pod_expected.security_context)
    ):
        return ["candidate_template_mismatch"]

    source_state = source.source_state_volume
    actual_volumes = {
        item.get("name"): item for item in (pod_spec.get("volumes") or [])
    }
    candidate_volumes = {
        item.get("name"): item for item in pod_expected.volumes
    }
    if source_state is not None:
        actual_state = actual_volumes.pop(source_state.volume_name, None)
        candidate_volumes.pop(source_state.volume_name, None)
        claim_name = _get(actual_state, "persistentVolumeClaim", "claimName")
        if claim_name != source_state.claim_name:
            return ["candidate_template_mismatch"]
    if _compact(actual_volumes) != _compact(candidate_volumes):
        return ["candidate_template_mismatch"]
    return []


def _service_ports_compatible(
    service_ports: list[dict[str, Any]],
    container_ports: list[dict[str, Any]],
) -> bool:
    if not service_ports or not container_ports:
        return False
    names = {item.get("name") for item in container_ports if item.get("name")}
    numbers = {
        item.get("containerPort")
        for item in container_ports
        if item.get("containerPort") is not None
    }
    for item in service_ports:
        target = item.get("targetPort", item.get("port"))
        if target not in names and target not in numbers:
            return False
    return True


def _node_accelerator(snapshot: Any) -> str | None:
    for key in (
        "nvidia.com/gpu.product",
        "accelerator",
        "accelerator-type",
        "gpu.product",
    ):
        if snapshot.labels.get(key):
            return snapshot.labels[key]
    if snapshot.labels.get("edge.device/class") == "jetson":
        return "JetsonGPU"
    if any(
        amount > 0 and "nvidia" in name.lower()
        for name, amount in snapshot.allocatable.accelerator_units.items()
    ):
        return "nvidia-gpu"
    return None
