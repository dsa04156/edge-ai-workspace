from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from fastapi import HTTPException

import httpx
from kubernetes import client

from .config import Settings
from .kube import build_batch_api
from .models import (
    ExecuteStageRequest,
    ExecuteWorkflowRequest,
    PlacementDecision,
    StageExecutionResult,
    StageExecutionSpec,
    WorkflowEvent,
    WorkflowRunState,
    WorkflowExecutionResult,
)
from .storage import WorkflowStateStore


def _sanitize_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return name[:50] or "stage"


class WorkflowExecutorService:
    def __init__(self, settings: Settings, batch_api: client.BatchV1Api | None = None) -> None:
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.batch_api = batch_api or build_batch_api()
        self.store = WorkflowStateStore(settings.state_db_path)
        self.current_placement: dict[tuple[str, str], str] = {}

    async def execute_stage(self, request: ExecuteStageRequest) -> StageExecutionResult:
        previous_node = request.current_placement or await asyncio.to_thread(
            self.store.get_stage_assignment,
            request.workflow_id,
            request.stage.stage_id,
        )
        await self._mark_stage_running(
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stage_id=request.stage.stage_id,
        )
        decision = await self._decide_stage(
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stage=request.stage,
            node_profiles=[profile.model_dump() for profile in request.node_profiles],
            current_placement=previous_node,
        )
        return await self._execute_stage_with_decision(
            request=request,
            decision=decision,
            previous_node=previous_node,
        )

    async def _execute_stage_with_decision(
        self,
        *,
        request: ExecuteStageRequest,
        decision: PlacementDecision,
        previous_node: str | None,
    ) -> StageExecutionResult:
        if not decision.target_node or decision.action_type == "reject":
            await asyncio.to_thread(
                self.store.upsert_stage,
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                stage_id=request.stage.stage_id,
                stage_type=request.stage.stage_metadata.stage_type,
                status="failed",
                assigned_node=previous_node,
                decision_reason=decision.decision_reason,
            )
            await asyncio.to_thread(
                self.store.append_transition,
                request.workflow_id,
                "stage_rejected",
                stage_id=request.stage.stage_id,
                details={"reason": decision.decision_reason},
            )
            await self._send_event(
                WorkflowEvent(
                    event_type="failure_event",
                    workflow_id=request.workflow_id,
                    workflow_type=request.workflow_type,
                    stage_id=request.stage.stage_id,
                    stage_type=request.stage.stage_metadata.stage_type,
                    assigned_node=previous_node or "unassigned",
                    reason=decision.decision_reason,
                    status="failed",
                )
            )
            await asyncio.to_thread(
                self.store.update_workflow_status,
                request.workflow_id,
                request.workflow_type,
                "failed",
                request.stage.stage_id,
            )
            raise RuntimeError(f"Stage rejected: {decision.decision_reason}")

        if previous_node and previous_node != decision.target_node:
            await asyncio.to_thread(
                self.store.append_transition,
                request.workflow_id,
                "migration_event",
                stage_id=request.stage.stage_id,
                details={
                    "from_node": previous_node,
                    "to_node": decision.target_node,
                    "reason": decision.decision_reason,
                },
            )
            await self._send_event(
                WorkflowEvent(
                    event_type="migration_event",
                    workflow_id=request.workflow_id,
                    workflow_type=request.workflow_type,
                    stage_id=request.stage.stage_id,
                    stage_type=request.stage.stage_metadata.stage_type,
                    assigned_node=decision.target_node,
                    from_node=previous_node,
                    to_node=decision.target_node,
                    transfer_time_ms=request.stage.transfer_time_ms,
                    reason=decision.decision_reason,
                    status="migrating",
                )
            )

        job_name = await asyncio.to_thread(
            self._create_job,
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stage=request.stage,
            target_node=decision.target_node,
        )
        started_at = datetime.now(timezone.utc)
        await asyncio.to_thread(
            self.store.upsert_stage,
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stage_id=request.stage.stage_id,
            stage_type=request.stage.stage_metadata.stage_type,
            status="running",
            assigned_node=decision.target_node,
            job_name=job_name,
            action_type=decision.action_type,
            decision_reason=decision.decision_reason,
            queue_wait_ms=request.stage.queue_wait_ms,
            exec_time_ms=request.stage.exec_time_ms,
            transfer_time_ms=request.stage.transfer_time_ms,
            started_at=started_at,
        )
        await asyncio.to_thread(
            self.store.append_transition,
            request.workflow_id,
            "stage_started",
            stage_id=request.stage.stage_id,
            details={
                "assigned_node": decision.target_node,
                "job_name": job_name,
                "action_type": decision.action_type,
            },
        )

        await self._send_event(
            WorkflowEvent(
                event_type="stage_start",
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                stage_id=request.stage.stage_id,
                stage_type=request.stage.stage_metadata.stage_type,
                assigned_node=decision.target_node,
                queue_wait_ms=request.stage.queue_wait_ms,
                status="running",
            )
        )

        status = await asyncio.to_thread(
            self._wait_for_job,
            job_name,
            request.stage.timeout_seconds or self.settings.job_timeout_seconds,
        )

        if status != "completed":
            await asyncio.to_thread(
                self.store.upsert_stage,
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                stage_id=request.stage.stage_id,
                stage_type=request.stage.stage_metadata.stage_type,
                status="failed",
                assigned_node=decision.target_node,
                job_name=job_name,
                action_type=decision.action_type,
                decision_reason=decision.decision_reason,
                queue_wait_ms=request.stage.queue_wait_ms,
                exec_time_ms=request.stage.exec_time_ms,
                transfer_time_ms=request.stage.transfer_time_ms,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )
            await asyncio.to_thread(
                self.store.append_transition,
                request.workflow_id,
                "stage_failed",
                stage_id=request.stage.stage_id,
                details={"job_name": job_name},
            )
            await self._send_event(
                WorkflowEvent(
                    event_type="failure_event",
                    workflow_id=request.workflow_id,
                    workflow_type=request.workflow_type,
                    stage_id=request.stage.stage_id,
                    stage_type=request.stage.stage_metadata.stage_type,
                    assigned_node=decision.target_node,
                    reason=f"job {job_name} failed",
                    status="failed",
                )
            )
            await asyncio.to_thread(
                self.store.update_workflow_status,
                request.workflow_id,
                request.workflow_type,
                "failed",
                request.stage.stage_id,
            )
            raise RuntimeError(f"Job {job_name} failed")

        completed_at = datetime.now(timezone.utc)
        await asyncio.to_thread(
            self.store.upsert_stage,
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stage_id=request.stage.stage_id,
            stage_type=request.stage.stage_metadata.stage_type,
            status="completed",
            assigned_node=decision.target_node,
            job_name=job_name,
            action_type=decision.action_type,
            decision_reason=decision.decision_reason,
            queue_wait_ms=request.stage.queue_wait_ms,
            exec_time_ms=request.stage.exec_time_ms,
            transfer_time_ms=request.stage.transfer_time_ms,
            started_at=started_at,
            completed_at=completed_at,
        )
        await asyncio.to_thread(
            self.store.append_transition,
            request.workflow_id,
            "stage_completed",
            stage_id=request.stage.stage_id,
            details={"job_name": job_name, "assigned_node": decision.target_node},
        )
        await self._send_event(
            WorkflowEvent(
                event_type="stage_end",
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                stage_id=request.stage.stage_id,
                stage_type=request.stage.stage_metadata.stage_type,
                assigned_node=decision.target_node,
                exec_time_ms=request.stage.exec_time_ms,
                status="completed",
            )
        )

        self.current_placement[(request.workflow_id, request.stage.stage_id)] = decision.target_node
        return StageExecutionResult(
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stage_id=request.stage.stage_id,
            target_node=decision.target_node,
            action_type=decision.action_type,
            decision_reason=decision.decision_reason,
            job_name=job_name,
            status="completed",
        )

    async def execute_workflow(self, request: ExecuteWorkflowRequest) -> WorkflowExecutionResult:
        await asyncio.to_thread(
            self.store.ensure_workflow,
            request.workflow_id,
            request.workflow_type,
        )
        await asyncio.to_thread(
            self.store.update_workflow_status,
            request.workflow_id,
            request.workflow_type,
            "running",
            None,
        )
        await asyncio.to_thread(
            self.store.append_transition,
            request.workflow_id,
            "workflow_started",
            details={"stage_count": len(request.stages)},
        )
        results: list[StageExecutionResult] = []
        placement: dict[str, str] = dict(request.current_placement)

        for index, stage in enumerate(request.stages):
            if stage.stage_id not in placement:
                stored_assignment = await asyncio.to_thread(
                    self.store.get_stage_assignment,
                    request.workflow_id,
                    stage.stage_id,
                )
                if stored_assignment:
                    placement[stage.stage_id] = stored_assignment

            remaining_stages = request.stages[index:]
            planned_decision: PlacementDecision | None = None
            try:
                replanned_decisions = await self._replan_remaining_stages(
                    workflow_id=request.workflow_id,
                    workflow_type=request.workflow_type,
                    stages=remaining_stages,
                    node_profiles=[profile.model_dump() for profile in request.node_profiles],
                    current_placement=placement,
                )
            except (httpx.HTTPError, ValueError) as exc:
                await asyncio.to_thread(
                    self.store.append_transition,
                    request.workflow_id,
                    "workflow_replan_failed",
                    stage_id=stage.stage_id,
                    details={
                        "remaining_stage_count": len(remaining_stages),
                        "reason": str(exc),
                    },
                )
            else:
                replanned_by_stage = {
                    decision.stage_id: decision for decision in replanned_decisions
                }
                planned_decision = replanned_by_stage.get(stage.stage_id)
            current_stage_placement = placement.get(stage.stage_id)
            stage_request = ExecuteStageRequest(
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                stage=stage,
                node_profiles=request.node_profiles,
                current_placement=current_stage_placement,
            )

            if planned_decision is not None:
                await self._mark_stage_running(
                    workflow_id=request.workflow_id,
                    workflow_type=request.workflow_type,
                    stage_id=stage.stage_id,
                )
                await asyncio.to_thread(
                    self.store.append_transition,
                    request.workflow_id,
                    "workflow_replanned",
                    stage_id=stage.stage_id,
                    details={
                        "remaining_stage_count": len(remaining_stages),
                        "selected_target": planned_decision.target_node,
                        "selected_action": planned_decision.action_type,
                    },
                )
                result = await self._execute_stage_with_decision(
                    request=stage_request,
                    decision=planned_decision,
                    previous_node=placement.get(stage.stage_id),
                )
            else:
                result = await self.execute_stage(stage_request)
            placement[stage.stage_id] = result.target_node
            results.append(result)

        last_stage = request.stages[-1]
        last_target = results[-1].target_node
        await asyncio.to_thread(
            self.store.update_workflow_status,
            request.workflow_id,
            request.workflow_type,
            "completed",
            last_stage.stage_id,
        )
        await asyncio.to_thread(
            self.store.append_transition,
            request.workflow_id,
            "workflow_completed",
            stage_id=last_stage.stage_id,
            details={"assigned_node": last_target},
        )
        await self._send_event(
            WorkflowEvent(
                event_type="workflow_end",
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                stage_id=last_stage.stage_id,
                stage_type=last_stage.stage_metadata.stage_type,
                assigned_node=last_target,
                status="completed",
            )
        )
        return WorkflowExecutionResult(
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            stages=results,
        )

    async def get_workflow_state(self, workflow_id: str) -> WorkflowRunState:
        workflow = await asyncio.to_thread(self.store.get_workflow, workflow_id)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow

    async def list_workflow_states(self) -> list[WorkflowRunState]:
        return await asyncio.to_thread(self.store.list_workflows)

    async def _mark_stage_running(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        stage_id: str,
    ) -> None:
        await asyncio.to_thread(
            self.store.ensure_workflow,
            workflow_id,
            workflow_type,
        )
        await asyncio.to_thread(
            self.store.update_workflow_status,
            workflow_id,
            workflow_type,
            "running",
            stage_id,
        )

    async def _decide_stage(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        stage: StageExecutionSpec,
        node_profiles: list[dict],
        current_placement: str | None,
    ) -> PlacementDecision:
        async with httpx.AsyncClient(timeout=10.0) as client_http:
            response = await client_http.post(
                f"{self.settings.placement_engine_url.rstrip('/')}/placement/decide",
                json={
                    "workflow_id": workflow_id,
                    "workflow_type": workflow_type,
                    "stage_id": stage.stage_id,
                    "stage_metadata": stage.stage_metadata.model_dump(),
                    "node_profiles": node_profiles,
                    "current_placement": current_placement,
                },
            )
            response.raise_for_status()
        return PlacementDecision(**response.json()["decision"])

    async def _send_event(self, event: WorkflowEvent) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client_http:
            response = await client_http.post(
                self.settings.state_aggregator_event_url,
                json=event.model_dump(mode="json"),
            )
            response.raise_for_status()

    async def _replan_remaining_stages(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        stages: list[StageExecutionSpec],
        node_profiles: list[dict],
        current_placement: dict[str, str],
        ) -> list[PlacementDecision]:
        async with httpx.AsyncClient(timeout=10.0) as client_http:
            response = await client_http.post(
                f"{self.settings.placement_engine_url.rstrip('/')}/placement/replan",
                json={
                    "workflow_id": workflow_id,
                    "workflow_type": workflow_type,
                    "stages": [
                        {
                            "stage_id": stage.stage_id,
                            "stage_metadata": stage.stage_metadata.model_dump(),
                        }
                        for stage in stages
                    ],
                    "node_profiles": node_profiles,
                    "current_placement": current_placement,
                },
            )
            response.raise_for_status()
        payload = response.json()
        decisions = payload.get("decisions")
        if not isinstance(decisions, list):
            raise ValueError("placement/replan response missing decisions list")
        return [PlacementDecision(**item) for item in decisions]

    def _create_job(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        stage: StageExecutionSpec,
        target_node: str,
    ) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%H%M%S")
        job_name = f"{_sanitize_name(workflow_id)}-{_sanitize_name(stage.stage_id)}-{timestamp}"
        env = [
            client.V1EnvVar(name=key, value=value)
            for key, value in sorted(stage.env.items())
        ]
        env.extend(
            [
                client.V1EnvVar(name="WORKFLOW_ID", value=workflow_id),
                client.V1EnvVar(name="WORKFLOW_TYPE", value=workflow_type),
                client.V1EnvVar(name="STAGE_ID", value=stage.stage_id),
                client.V1EnvVar(name="STAGE_TYPE", value=stage.stage_metadata.stage_type),
                client.V1EnvVar(name="TARGET_NODE", value=target_node),
            ]
        )
        container = client.V1Container(
            name="stage",
            image=stage.image,
            image_pull_policy="Always",
            command=stage.command or None,
            args=stage.args or None,
            env=env or None,
        )
        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[container],
            node_selector={"kubernetes.io/hostname": target_node.lower()},
        )
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app": "workflow-executor-stage",
                    "workflow_id": _sanitize_name(workflow_id),
                    "stage_id": _sanitize_name(stage.stage_id),
                }
            ),
            spec=pod_spec,
        )
        body = client.V1Job(
            metadata=client.V1ObjectMeta(
                name=job_name,
                labels={
                    "app": "workflow-executor-stage",
                    "workflow_id": _sanitize_name(workflow_id),
                    "workflow_type": _sanitize_name(workflow_type),
                    "stage_id": _sanitize_name(stage.stage_id),
                    "target_node": target_node.lower(),
                },
            ),
            spec=client.V1JobSpec(
                template=template,
                backoff_limit=0,
                ttl_seconds_after_finished=300,
            ),
        )
        self.batch_api.create_namespaced_job(namespace=self.settings.namespace, body=body)
        return job_name

    def _wait_for_job(self, job_name: str, timeout_seconds: int) -> str:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            job = self.batch_api.read_namespaced_job_status(
                name=job_name,
                namespace=self.settings.namespace,
            )
            status = job.status
            if status.succeeded and status.succeeded >= 1:
                return "completed"
            if status.failed and status.failed >= 1:
                return "failed"
            time.sleep(self.settings.poll_interval_seconds)
        return "failed"
