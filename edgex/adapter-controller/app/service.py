from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any

from .api import ControllerConflict, ControllerNotFound, ControllerValidationError
from .catalog import RuntimeTemplateCatalog
from .models import (
    RuntimeActionRequest,
    RuntimeCreateRequest,
    RuntimeObservation,
    RuntimePlan,
    RuntimePlanRequest,
    RuntimeTemplate,
)
from .discovery_models import (
    CandidateApprovalRequest,
    CandidateRejectRequest,
    CandidateRetryRequest,
)
from .planner import RuntimePlanner
from .renderer import render_adapter_runtime
from .metrics import render_discovery_metrics


logger = logging.getLogger(__name__)


class AdapterControllerService:
    def __init__(
        self,
        catalog: RuntimeTemplateCatalog,
        kube: Any,
        edgex_probe: Any,
        reconciler: Any,
        *,
        namespace: str,
        candidate_registry: Any | None = None,
        registration_coordinator: Any | None = None,
        device_catalog: Any | None = None,
    ) -> None:
        if namespace != "edgex-edge":
            raise ValueError("Adapter Controller is limited to edgex-edge")
        self.catalog = catalog
        self.kube = kube
        self.edgex_probe = edgex_probe
        self.reconciler = reconciler
        self.namespace = namespace
        self.planner = RuntimePlanner(catalog)
        self.candidate_registry = candidate_registry
        self.registration_coordinator = registration_coordinator
        self.device_catalog = device_catalog

    def attach_registration_coordinator(self, coordinator: Any) -> None:
        self.registration_coordinator = coordinator

    def list_runtimes(self) -> list[RuntimeObservation]:
        result: list[RuntimeObservation] = []
        controller_names = {
            str((item.get("metadata") or {}).get("name") or "")
            for item in self.kube.list_runtimes()
        }
        for template in self.catalog.templates:
            for runtime in template.external_runtimes:
                if runtime.runtime_name in controller_names:
                    continue
                workload_ready = self.kube.is_deployment_ready(
                    self.namespace,
                    runtime.workload_name,
                )
                service_ready = (
                    workload_ready
                    and self.edgex_probe.service_ready(runtime.service_name)
                )
                phase = (
                    "SERVICE_READY"
                    if service_ready
                    else ("WORKLOAD_READY" if workload_ready else "DEPLOYING")
                )
                result.append(
                    RuntimeObservation(
                        runtime_name=runtime.runtime_name,
                        adapter_id=template.adapter_id,
                        template_id=template.template_id,
                        service_name=runtime.service_name,
                        target_node=runtime.target_node,
                        hardware_binding_id=runtime.hardware_binding_id,
                        hardware_binding_ids=runtime.hardware_binding_ids,
                        management_mode="external",
                        management_owner="argocd",
                        purpose=template.purpose,
                        verification_state=template.verification_state,
                        phase=phase,
                        consumers=self.edgex_probe.consumer_count(
                            runtime.service_name
                        ),
                        mutable=False,
                        workload_name=runtime.workload_name,
                        image=self.kube.deployment_image(
                            self.namespace,
                            runtime.workload_name,
                        ),
                    )
                )
        for runtime in self.kube.list_runtimes():
            result.append(self._observation_from_runtime(runtime))
        return sorted(result, key=lambda item: item.runtime_name)

    def plan(self, request: RuntimePlanRequest) -> RuntimePlan:
        return self.planner.plan(
            request,
            self.list_runtimes(),
            target_node_ready=self.kube.node_ready(request.target_node),
        )

    def apply_runtime(
        self,
        name: str,
        request: RuntimeCreateRequest,
    ) -> RuntimeObservation:
        existing = self.kube.get_runtime(name)
        if existing is not None:
            existing_spec = existing.get("spec") or {}
            request_ref = existing_spec.get("requestRef") or {}
            expected = request.request_ref.model_dump(by_alias=True)
            if request_ref == expected:
                return self._reconcile_and_observe(existing)
            if existing_spec.get("desiredState") != "Retired":
                raise ControllerConflict(
                    "runtime exists from a different idempotent request"
                )

        plan = self.plan(request.plan)
        if request.request_ref.plan_hash != plan.plan_hash:
            raise ControllerConflict("runtime plan is stale or has a different hash")
        if plan.action != "DEPLOY" or not plan.allowed:
            reason = plan.reasons[0].code if plan.reasons else "runtime_plan_blocked"
            raise ControllerValidationError(
                f"runtime deployment is not allowed: {reason}"
            )
        if plan.runtime_name != name:
            raise ControllerValidationError(
                "runtime name does not match the immutable deployment plan"
            )
        if existing is not None:
            existing_spec = existing.get("spec") or {}
            immutable_fields = {
                "templateId": plan.template_id,
                "adapterId": plan.adapter_id,
                "targetNode": plan.target_node,
                "hardwareBindingId": plan.hardware_binding_id,
            }
            if any(
                existing_spec.get(field) != value
                for field, value in immutable_fields.items()
            ):
                raise ControllerConflict(
                    "retired runtime identity does not match the deployment plan"
                )
            persisted = self.kube.patch_runtime_spec(
                name,
                {
                    "desiredState": "Running",
                    "restartNonce": "",
                    "edgeX": {
                        **dict(existing_spec.get("edgeX") or {}),
                        "serviceName": plan.service_name,
                    },
                    "requestRef": request.request_ref.model_dump(
                        by_alias=True
                    ),
                    "actionRef": None,
                },
            )
            return self._reconcile_and_observe(persisted)
        template = self.catalog.require(str(plan.template_id))
        resource = render_adapter_runtime(
            plan,
            template,
            request.request_ref,
            namespace=self.namespace,
        )
        persisted = self.kube.apply_runtime(resource)
        return self._reconcile_and_observe(persisted)

    def restart_runtime(
        self,
        name: str,
        request: RuntimeActionRequest,
    ) -> RuntimeObservation:
        runtime = self._require_controller_runtime(name)
        action_ref = (runtime.get("spec") or {}).get("actionRef") or {}
        replay = self._action_replay_or_conflict(
            action_ref,
            action="restart",
            request=request,
        )
        if replay:
            return self._observation_from_runtime(runtime)
        patched = self.kube.patch_runtime_spec(
            name,
            {
                "restartNonce": request.request_id,
                "actionRef": {
                    "action": "restart",
                    **request.model_dump(by_alias=True),
                },
            },
        )
        return self._reconcile_and_observe(patched)

    def retire_runtime(
        self,
        name: str,
        request: RuntimeActionRequest,
    ) -> RuntimeObservation:
        runtime = self._require_controller_runtime(name)
        spec = runtime.get("spec") or {}
        action_ref = spec.get("actionRef") or {}
        replay = self._action_replay_or_conflict(
            action_ref,
            action="retire",
            request=request,
        )
        if replay and spec.get("desiredState") == "Retired":
            return self._reconcile_and_observe(runtime)
        service_name = str((spec.get("edgeX") or {}).get("serviceName") or "")
        consumers = self.edgex_probe.consumer_count(service_name)
        if consumers:
            raise ControllerConflict(
                f"runtime has {consumers} EdgeX Device consumers"
            )
        patched = self.kube.patch_runtime_spec(
            name,
            {
                "desiredState": "Retired",
                "actionRef": {
                    "action": "retire",
                    **request.model_dump(by_alias=True),
                },
            },
        )
        patched.setdefault("status", {})["consumers"] = 0
        return self._reconcile_and_observe(patched)

    def reconcile_all(self) -> int:
        count = 0
        for runtime in self.kube.list_runtimes():
            spec = runtime.get("spec") or {}
            try:
                template = self.catalog.require(str(spec.get("templateId") or ""))
            except ValueError:
                continue
            service_name = str((spec.get("edgeX") or {}).get("serviceName") or "")
            runtime.setdefault("status", {})[
                "consumers"
            ] = self.edgex_probe.consumer_count(service_name)
            self.reconciler.reconcile(runtime, template)
            count += 1
        if self.candidate_registry is not None:
            count += self.candidate_registry.reconcile_presence()
        if self.registration_coordinator is not None:
            count += self.registration_coordinator.reconcile_all()
        return count

    def list_discovery_inventory(self):
        return self._require_candidate_registry().list_inventory()

    def ingest_discovery_report(self, report):
        return self._require_candidate_registry().ingest_report(report)

    def create_manual_candidate(self, request):
        return self._require_candidate_registry().create_manual(request)

    def update_candidate_decision(self, candidate_id: str, request):
        if self.registration_coordinator is not None:
            if request.decision == "accepted":
                current = self._require_candidate_registry().get_stored_candidate(
                    candidate_id
                )
                if current.state == "FAILED":
                    approved = self.registration_coordinator.retry(
                        candidate_id,
                        CandidateRetryRequest(
                            actor="dashboard-admin",
                            reason=request.note or "등록 Saga 재시도",
                            request_ref=request.request_ref,
                        ),
                    )
                else:
                    approved = self.registration_coordinator.approve(
                        candidate_id,
                        CandidateApprovalRequest(
                            actor="dashboard-admin",
                            reason=request.note or "운영자 승인",
                            request_ref=request.request_ref,
                        ),
                    )
                return self._start_registration_immediately(
                    candidate_id,
                    approved,
                )
            if request.decision == "ignored":
                return self.registration_coordinator.reject(
                    candidate_id,
                    CandidateRejectRequest(
                        actor="dashboard-admin",
                        reason=request.note or "운영자 거절",
                        request_ref=request.request_ref,
                    ),
                )
        return self._require_candidate_registry().update_decision(
            candidate_id,
            request,
        )

    def _start_registration_immediately(self, candidate_id: str, candidate):
        current = candidate
        for _ in range(3):
            if current.state not in {
                "APPROVED",
                "SERVICE_READY",
                "METADATA_REGISTERED",
            }:
                break
            previous_state = current.state
            try:
                self.registration_coordinator.reconcile_candidate(candidate_id)
            except Exception:
                logger.exception(
                    "immediate registration start failed candidateId=%s "
                    "currentState=%s; background reconciliation will retry",
                    candidate_id,
                    previous_state,
                )
                break
            current = self._require_candidate_registry().get_candidate(candidate_id)
            if current.state == previous_state:
                break
        return current

    def delete_candidate(self, candidate_id: str, request):
        return self._require_candidate_registry().delete_candidate(
            candidate_id,
            request,
        )

    def get_candidate(self, candidate_id: str):
        return self._require_candidate_registry().get_candidate(candidate_id)

    def approve_candidate(self, candidate_id: str, request):
        return self._require_registration().approve(candidate_id, request)

    def reject_candidate(self, candidate_id: str, request):
        return self._require_registration().reject(candidate_id, request)

    def retry_candidate(self, candidate_id: str, request):
        return self._require_registration().retry(candidate_id, request)

    def reconcile_discovery(self, request):
        changed = self._require_candidate_registry().reconcile_presence(
            node_id=request.node_id,
            protocol=request.protocol,
        )
        if self.registration_coordinator is not None:
            changed += self.registration_coordinator.reconcile_all()
        return {"reconciled": changed}

    def get_discovery_plan(self, node_id: str):
        return self._require_candidate_registry().get_plan(node_id)

    def put_discovery_plan(self, node_id: str, plan):
        if node_id != plan.node_id:
            raise ControllerValidationError(
                "Discovery Plan path and nodeId must match"
            )
        return self._require_candidate_registry().put_plan(plan)

    def get_registration(self, candidate_id: str):
        return self._require_registration().get_registration(candidate_id)

    def list_discovery_events(
        self,
        *,
        candidate_id: str | None = None,
        limit: int = 200,
    ):
        return self._require_candidate_registry().list_events(
            candidate_id=candidate_id,
            limit=limit,
        )

    def list_device_bindings(self):
        if self.device_catalog is None:
            return {"version": 0, "bindings": [], "errors": ["catalog_disabled"]}
        return {
            "version": self.device_catalog.version,
            "bindings": [
                item.model_dump(
                    by_alias=True,
                    mode="json",
                    exclude_none=True,
                )
                for item in self.device_catalog.bindings
            ],
            "errors": list(self.device_catalog.errors),
        }

    def discovery_metrics(self) -> str:
        inventory = self._require_candidate_registry().list_inventory()
        registrations = (
            self.registration_coordinator.store.list_registrations()
            if self.registration_coordinator is not None
            else []
        )
        return render_discovery_metrics(inventory, registrations)

    def _require_candidate_registry(self):
        if self.candidate_registry is None:
            raise ControllerValidationError("device discovery registry is disabled")
        return self.candidate_registry

    def _require_registration(self):
        if self.registration_coordinator is None:
            raise ControllerValidationError(
                "device registration coordinator is disabled"
            )
        return self.registration_coordinator

    def _require_controller_runtime(self, name: str) -> dict[str, Any]:
        runtime = self.kube.get_runtime(name)
        if runtime is None:
            raise ControllerNotFound(
                f"controller-managed runtime {name!r} was not found"
            )
        return runtime

    def _reconcile_and_observe(
        self,
        runtime: dict[str, Any],
    ) -> RuntimeObservation:
        spec = runtime.get("spec") or {}
        template = self.catalog.require(str(spec.get("templateId") or ""))
        service_name = str((spec.get("edgeX") or {}).get("serviceName") or "")
        runtime.setdefault("status", {})[
            "consumers"
        ] = self.edgex_probe.consumer_count(service_name)
        status = self.reconciler.reconcile(runtime, template)
        observed = deepcopy(runtime)
        observed["status"] = status
        return self._observation_from_runtime(observed)

    def _observation_from_runtime(
        self,
        runtime: dict[str, Any],
    ) -> RuntimeObservation:
        metadata = runtime.get("metadata") or {}
        spec = runtime.get("spec") or {}
        status = runtime.get("status") or {}
        template = self.catalog.require(str(spec.get("templateId") or ""))
        service_name = str((spec.get("edgeX") or {}).get("serviceName") or "")
        consumers = self.edgex_probe.consumer_count(service_name)
        return RuntimeObservation(
            runtime_name=str(metadata.get("name") or ""),
            adapter_id=template.adapter_id,
            template_id=template.template_id,
            service_name=service_name,
            target_node=str(spec.get("targetNode") or ""),
            hardware_binding_id=str(spec.get("hardwareBindingId") or ""),
            hardware_binding_ids=[str(spec.get("hardwareBindingId") or "")],
            management_mode="controller",
            management_owner="controller",
            purpose=template.purpose,
            verification_state=template.verification_state,
            phase=str(status.get("phase") or "PLANNED"),
            consumers=consumers,
            mutable=str(status.get("phase") or "") != "RETIRED",
            workload_name=str(
                (status.get("workloadRef") or {}).get("name")
                or metadata.get("name")
                or ""
            ),
            image=self.kube.deployment_image(
                self.namespace,
                str(
                    (status.get("workloadRef") or {}).get("name")
                    or metadata.get("name")
                    or ""
                ),
            ),
        )

    @staticmethod
    def _action_replay_or_conflict(
        action_ref: dict[str, Any],
        *,
        action: str,
        request: RuntimeActionRequest,
    ) -> bool:
        if not action_ref:
            return False
        if (
            action_ref.get("action") == action
            and action_ref.get("requestId") == request.request_id
        ):
            if action_ref.get("payloadHash") != request.payload_hash:
                raise ControllerConflict(
                    "action request ID was reused with a different payload"
                )
            return True
        return False
