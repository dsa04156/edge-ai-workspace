from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from .api import ControllerConflict, ControllerValidationError
from .device_catalog import DeviceBinding, DeviceBindingCatalog
from .discovery_models import (
    CandidateApprovalRequest,
    CandidateRejectRequest,
    CandidateRetryRequest,
    CandidateView,
    RegistrationRecord,
)
from .discovery_store import DiscoveryStoreError, SQLiteDiscoveryStore
from .models import (
    RuntimeActionRequest,
    RuntimeApplyRequest,
    RuntimeCreateRequest,
    RuntimePlanRequest,
)


TERMINAL_STATES = {"EVENT_CONFIRMED", "REJECTED"}
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RegistrationCoordinator:
    def __init__(
        self,
        *,
        registry: Any,
        store: SQLiteDiscoveryStore,
        device_catalog: DeviceBindingCatalog,
        auth_provider: Any,
        edge_x: Any,
        kube: Any,
        runtime_service: Any,
        event_timeout_seconds: int = 60,
    ) -> None:
        self.registry = registry
        self.store = store
        self.device_catalog = device_catalog
        self.auth_provider = auth_provider
        self.edge_x = edge_x
        self.kube = kube
        self.runtime_service = runtime_service
        self.event_timeout_seconds = event_timeout_seconds
        self._lock = RLock()

    def approve(
        self,
        candidate_id: str,
        request: CandidateApprovalRequest,
    ) -> CandidateView:
        with self._lock:
            return self._approve(candidate_id, request)

    def _approve(
        self,
        candidate_id: str,
        request: CandidateApprovalRequest,
    ) -> CandidateView:
        replay = self._get_replay(
            f"approve:{candidate_id}",
            request,
        )
        if replay is not None:
            return CandidateView.model_validate(replay)
        candidate = self.registry.get_stored_candidate(candidate_id)
        if candidate.state in {
            "APPROVED",
            "SERVICE_READY",
            "METADATA_REGISTERED",
            "EVENT_CONFIRMED",
        }:
            view = self.registry.get_candidate(candidate_id)
            self._remember_response(
                f"approve:{candidate_id}",
                request,
                view,
            )
            return view
        if (
            candidate.state == "BLOCKED"
            and candidate.auth_state in {"unavailable", "error"}
        ):
            self.registry.transition(
                candidate_id,
                "PENDING_APPROVAL",
                reason="operator requested external authorization retry",
                actor=request.actor,
            )
            candidate = self.registry.get_stored_candidate(candidate_id)
        if candidate.state != "PENDING_APPROVAL":
            raise ControllerConflict(
                f"candidate in state {candidate.state} cannot be approved"
            )
        view = self.registry.get_candidate(candidate_id)
        if view.presence == "stale":
            raise ControllerValidationError(
                "stale candidate cannot be approved"
            )
        match = self.device_catalog.match(candidate)
        if match.confidence != "exact" or match.binding is None:
            raise ControllerValidationError(
                "candidate has no exact verified Device Catalog binding"
            )
        decision = self.auth_provider.approve(
            candidate,
            actor=request.actor,
            reason=request.reason,
        )
        candidate.auth_state = decision.state
        candidate.matched_binding_id = match.binding.binding_id
        candidate.recommended_profile = match.binding.profile.name
        candidate.match_confidence = "exact"
        if not decision.approved:
            candidate.failure_reason = decision.reason
            self.registry.save_candidate(candidate)
            blocked = self.registry.transition(
                candidate_id,
                "BLOCKED",
                reason=decision.reason,
                actor=request.actor,
                error_code=decision.error_code or "AUTH_DENIED",
            )
            self._remember_response(
                f"approve:{candidate_id}",
                request,
                blocked,
            )
            return blocked
        candidate.auth_state = "approved"
        candidate.failure_reason = None
        candidate.registration_step = "APPROVED"
        self.registry.save_candidate(candidate)
        approved = self.registry.transition(
            candidate_id,
            "APPROVED",
            reason=request.reason,
            actor=request.actor,
        )
        now = _now()
        self.store.put_registration(
            RegistrationRecord(
                candidate_id=candidate_id,
                status="APPROVED",
                step="APPROVED",
                binding_id=match.binding.binding_id,
                started_at=now,
                updated_at=now,
            )
        )
        self._remember_response(
            f"approve:{candidate_id}",
            request,
            approved,
        )
        return approved

    def reject(
        self,
        candidate_id: str,
        request: CandidateRejectRequest,
    ) -> CandidateView:
        with self._lock:
            return self._reject(candidate_id, request)

    def _reject(
        self,
        candidate_id: str,
        request: CandidateRejectRequest,
    ) -> CandidateView:
        replay = self._get_replay(
            f"reject:{candidate_id}",
            request,
        )
        if replay is not None:
            return CandidateView.model_validate(replay)
        candidate = self.registry.get_stored_candidate(candidate_id)
        if candidate.state == "REJECTED":
            view = self.registry.get_candidate(candidate_id)
        elif candidate.state in {
            "PENDING_APPROVAL",
            "BLOCKED",
            "FAILED",
        }:
            view = self.registry.transition(
                candidate_id,
                "REJECTED",
                reason=request.reason,
                actor=request.actor,
            )
        else:
            raise ControllerConflict(
                f"candidate in state {candidate.state} cannot be rejected"
            )
        self._remember_response(f"reject:{candidate_id}", request, view)
        return view

    def retry(
        self,
        candidate_id: str,
        request: CandidateRetryRequest,
    ) -> CandidateView:
        with self._lock:
            return self._retry(candidate_id, request)

    def _retry(
        self,
        candidate_id: str,
        request: CandidateRetryRequest,
    ) -> CandidateView:
        replay = self._get_replay(
            f"retry:{candidate_id}",
            request,
        )
        if replay is not None:
            return CandidateView.model_validate(replay)
        candidate = self.registry.get_stored_candidate(candidate_id)
        if candidate.state != "FAILED":
            raise ControllerConflict(
                f"candidate in state {candidate.state} cannot be retried"
            )
        match = self.device_catalog.match(candidate)
        if match.confidence != "exact" or match.binding is None:
            raise ControllerValidationError(
                "retry requires an exact verified Catalog binding"
            )
        decision = self.auth_provider.approve(
            candidate,
            actor=request.actor,
            reason=request.reason,
        )
        if not decision.approved:
            candidate.auth_state = decision.state
            candidate.failure_reason = decision.reason
            self.registry.save_candidate(candidate)
            raise ControllerValidationError(decision.reason)
        previous = self.store.get_registration(candidate_id)
        if previous is not None and any(
            (
                previous.created_device,
                previous.created_profile,
                previous.created_runtime,
            )
        ):
            rollback_errors = self._rollback(previous)
            previous.updated_at = _now()
            self.store.put_registration(previous)
            if rollback_errors:
                raise ControllerValidationError(
                    "retry is blocked until owned-resource rollback succeeds"
                )
        candidate.retry_count += 1
        candidate.auth_state = "approved"
        candidate.failure_reason = None
        candidate.registration_step = "APPROVED"
        self.registry.save_candidate(candidate)
        view = self.registry.transition(
            candidate_id,
            "APPROVED",
            reason=request.reason,
            actor=request.actor,
        )
        now = _now()
        self.store.put_registration(
            RegistrationRecord(
                candidate_id=candidate_id,
                status="APPROVED",
                step="APPROVED",
                attempt=(previous.attempt + 1 if previous else 1),
                binding_id=match.binding.binding_id,
                started_at=now,
                updated_at=now,
            )
        )
        self._remember_response(f"retry:{candidate_id}", request, view)
        return view

    def get_registration(self, candidate_id: str) -> RegistrationRecord:
        registration = self.store.get_registration(candidate_id)
        if registration is None:
            raise ControllerValidationError(
                "candidate has no registration Saga"
            )
        return registration

    def reconcile_all(self) -> int:
        with self._lock:
            count = 0
            for registration in self.store.list_registrations():
                if registration.status in TERMINAL_STATES:
                    continue
                try:
                    self._reconcile_candidate(registration.candidate_id)
                    count += 1
                except Exception:
                    logger.exception(
                        "registration reconciliation failed candidateId=%s "
                        "registrationStep=%s errorCode=UNHANDLED_RECONCILE",
                        registration.candidate_id,
                        registration.step,
                    )
            return count

    def reconcile_candidate(self, candidate_id: str) -> RegistrationRecord:
        with self._lock:
            return self._reconcile_candidate(candidate_id)

    def _reconcile_candidate(
        self,
        candidate_id: str,
    ) -> RegistrationRecord:
        started = time.monotonic()
        current_state: str | None = None
        try:
            candidate = self.registry.get_stored_candidate(candidate_id)
            current_state = candidate.state
            registration = self.get_registration(candidate_id)
            if candidate.state == "APPROVED":
                return self._ensure_runtime(candidate, registration)
            if candidate.state == "SERVICE_READY":
                return self._ensure_metadata(candidate, registration)
            if candidate.state == "METADATA_REGISTERED":
                return self._confirm_event(candidate, registration)
            registration.status = candidate.state
            if candidate.state == "EVENT_CONFIRMED":
                registration.step = "EVENT_CONFIRMED"
                registration.completed_at = registration.completed_at or _now()
                registration.last_error = None
                registration.last_error_code = None
            elif candidate.state == "REJECTED":
                registration.step = "REJECTED"
            registration.updated_at = _now()
            return self.store.put_registration(registration)
        finally:
            self._log_reconciliation(
                candidate_id,
                current_state=current_state,
                duration_seconds=time.monotonic() - started,
            )

    def _log_reconciliation(
        self,
        candidate_id: str,
        *,
        current_state: str | None,
        duration_seconds: float,
    ) -> None:
        try:
            candidate = self.registry.get_stored_candidate(candidate_id)
            registration = self.store.get_registration(candidate_id)
            payload = {
                "eventType": "registration.reconcile",
                "candidateId": candidate_id,
                "nodeId": candidate.node_name,
                "protocol": candidate.protocol,
                "currentState": current_state,
                "nextState": candidate.state,
                "registrationStep": (
                    registration.step if registration is not None else None
                ),
                "durationSeconds": round(duration_seconds, 6),
                "errorCode": (
                    registration.last_error_code
                    if registration is not None
                    else None
                ),
            }
        except Exception:
            payload = {
                "eventType": "registration.reconcile",
                "candidateId": candidate_id,
                "nodeId": None,
                "protocol": None,
                "currentState": current_state,
                "nextState": None,
                "registrationStep": None,
                "durationSeconds": round(duration_seconds, 6),
                "errorCode": "REGISTRATION_OBSERVATION_FAILED",
            }
        logger.info(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    def _ensure_runtime(
        self,
        candidate: Any,
        registration: RegistrationRecord,
    ) -> RegistrationRecord:
        if self.registry.get_candidate(candidate.candidate_id).presence == "stale":
            return self._fail_runtime_stage(
                candidate,
                registration,
                code="CANDIDATE_STALE",
                message="candidate disappeared before Runtime preparation",
            )
        if not self.kube.node_ready(candidate.node_name):
            return self._fail_runtime_stage(
                candidate,
                registration,
                code="NODE_NOT_READY",
                message="target KubeEdge node is not Ready",
            )
        match = self.device_catalog.match(candidate)
        if match.confidence != "exact" or match.binding is None:
            return self._fail_runtime_stage(
                candidate,
                registration,
                code="CATALOG_MATCH_CHANGED",
                message="verified Catalog binding changed after approval",
            )
        binding = match.binding
        try:
            plan = self.runtime_service.plan(
                RuntimePlanRequest(
                    adapter_id=binding.adapter.runtime_adapter_id,
                    target_node=candidate.node_name,
                    hardware_binding_id=binding.runtime_hardware_binding_id,
                    mode="auto",
                )
            )
        except Exception as exc:
            return self._fail_runtime_stage(
                candidate,
                registration,
                code="RUNTIME_PLAN_FAILED",
                message=f"Runtime planning failed: {exc.__class__.__name__}",
            )
        if not plan.allowed or plan.action == "BLOCKED":
            reason = (
                plan.reasons[0].code
                if plan.reasons
                else "RUNTIME_PLAN_BLOCKED"
            )
            return self._fail_runtime_stage(
                candidate,
                registration,
                code="RUNTIME_PLAN_BLOCKED",
                message=f"Runtime plan was blocked: {reason}",
            )
        registration.runtime_name = plan.runtime_name
        registration.service_name = plan.service_name
        registration.binding_id = binding.binding_id
        registration.step = "RUNTIME_REQUESTED"
        self._set_candidate_step(candidate.candidate_id, registration.step)
        registration.updated_at = _now()
        if plan.action == "DEPLOY":
            try:
                request_id = _sha(
                    f"{candidate.candidate_id}|runtime|{registration.attempt}"
                )
                runtime = self.runtime_service.apply_runtime(
                    str(plan.runtime_name),
                    RuntimeCreateRequest(
                        plan=RuntimePlanRequest(
                            adapter_id=binding.adapter.runtime_adapter_id,
                            target_node=candidate.node_name,
                            hardware_binding_id=(
                                binding.runtime_hardware_binding_id
                            ),
                            mode="auto",
                        ),
                        request_ref=RuntimeApplyRequest(
                            request_id=request_id,
                            payload_hash=_sha(
                                f"{binding.binding_id}|{candidate.identity_hash}"
                            ),
                            plan_hash=plan.plan_hash,
                        ),
                    ),
                )
                registration.created_runtime = True
                if runtime.phase == "FAILED":
                    return self._fail_runtime_stage(
                        candidate,
                        registration,
                        code="RUNTIME_START_FAILED",
                        message="Device Service Runtime entered FAILED",
                    )
                if runtime.phase != "SERVICE_READY":
                    return self.store.put_registration(registration)
            except Exception as exc:
                return self._fail_runtime_stage(
                    candidate,
                    registration,
                    code="RUNTIME_START_FAILED",
                    message=f"Device Service startup failed: {exc.__class__.__name__}",
                )
        else:
            try:
                runtime = next(
                    (
                        item
                        for item in self.runtime_service.list_runtimes()
                        if item.runtime_name == plan.runtime_name
                    ),
                    None,
                )
            except Exception as exc:
                return self._fail_runtime_stage(
                    candidate,
                    registration,
                    code="RUNTIME_READ_FAILED",
                    message=f"Runtime readback failed: {exc.__class__.__name__}",
                )
            if runtime is None or runtime.phase != "SERVICE_READY":
                if runtime is not None and runtime.phase == "FAILED":
                    return self._fail_runtime_stage(
                        candidate,
                        registration,
                        code="RUNTIME_START_FAILED",
                        message="Device Service Runtime entered FAILED",
                    )
                registration.step = "WAITING_FOR_RUNTIME"
                self._set_candidate_step(
                    candidate.candidate_id,
                    registration.step,
                )
                return self.store.put_registration(registration)
        if runtime.image != binding.adapter.image:
            return self._fail_runtime_stage(
                candidate,
                registration,
                code="RUNTIME_IMAGE_NOT_VERIFIED",
                message=(
                    "running Device Service image does not match the "
                    "allowlisted Catalog digest"
                ),
            )
        self.registry.transition(
            candidate.candidate_id,
            "SERVICE_READY",
            reason="verified Device Service Runtime is ready",
            actor="registration-saga",
        )
        registration.status = "SERVICE_READY"
        registration.step = "SERVICE_READY"
        self._set_candidate_step(candidate.candidate_id, registration.step)
        registration.updated_at = _now()
        return self.store.put_registration(registration)

    def _fail_runtime_stage(
        self,
        candidate: Any,
        registration: RegistrationRecord,
        *,
        code: str,
        message: str,
    ) -> RegistrationRecord:
        rollback_errors = self._rollback(registration)
        suffix = (
            f"; rollback pending: {', '.join(rollback_errors)}"
            if rollback_errors
            else ""
        )
        return self._fail(
            candidate,
            registration,
            code=code,
            message=f"{message}{suffix}",
        )

    def _ensure_metadata(
        self,
        candidate: Any,
        registration: RegistrationRecord,
    ) -> RegistrationRecord:
        binding = self.device_catalog.get(str(registration.binding_id))
        profile = self.device_catalog.profile_document(binding)
        registration.profile_name = binding.profile.name
        registration.device_name = self._device_name(candidate, binding)
        try:
            registration.created_profile = self.edge_x.ensure_profile(profile)
            registration.step = "PROFILE_READY"
            self._set_candidate_step(candidate.candidate_id, registration.step)
            registration.updated_at = _now()
            self.store.put_registration(registration)
            device = self._device_document(
                candidate,
                binding,
                registration,
            )
            registration.created_device = self.edge_x.ensure_device(device)
            registration.step = "DEVICE_READBACK_VERIFIED"
            self._set_candidate_step(candidate.candidate_id, registration.step)
            registration.updated_at = _now()
            self.store.put_registration(registration)
        except Exception as exc:
            rollback_errors = self._rollback(registration)
            suffix = (
                f"; rollback pending: {', '.join(rollback_errors)}"
                if rollback_errors
                else ""
            )
            return self._fail(
                candidate,
                registration,
                code="METADATA_REGISTRATION_FAILED",
                message=(
                    "EdgeX Metadata registration failed: "
                    f"{exc.__class__.__name__}{suffix}"
                ),
            )
        self.registry.transition(
            candidate.candidate_id,
            "METADATA_REGISTERED",
            reason="EdgeX Profile and Device readback were verified",
            actor="registration-saga",
        )
        now = _now()
        registration.status = "METADATA_REGISTERED"
        registration.step = "WAITING_FIRST_EVENT"
        self._set_candidate_step(candidate.candidate_id, registration.step)
        registration.event_not_before = now
        registration.event_deadline = now + timedelta(
            seconds=self.event_timeout_seconds
        )
        registration.updated_at = now
        return self.store.put_registration(registration)

    def _confirm_event(
        self,
        candidate: Any,
        registration: RegistrationRecord,
    ) -> RegistrationRecord:
        try:
            confirmed = self.edge_x.first_event_received(
                str(registration.device_name),
                not_before_ns=(
                    int(registration.event_not_before.timestamp() * 1_000_000_000)
                    if registration.event_not_before is not None
                    else None
                ),
            )
        except Exception as exc:
            if (
                registration.event_deadline is not None
                and _now() >= registration.event_deadline
            ):
                rollback_errors = self._rollback(registration)
                suffix = (
                    f"; rollback pending: {', '.join(rollback_errors)}"
                    if rollback_errors
                    else ""
                )
                return self._fail(
                    candidate,
                    registration,
                    code="CORE_DATA_UNAVAILABLE",
                    message=(
                        "Core Data verification failed: "
                        f"{exc.__class__.__name__}{suffix}"
                    ),
                )
            registration.last_error_code = "CORE_DATA_UNAVAILABLE"
            registration.last_error = (
                f"Core Data verification pending: {exc.__class__.__name__}"
            )
            registration.updated_at = _now()
            return self.store.put_registration(registration)
        if confirmed:
            self.registry.transition(
                candidate.candidate_id,
                "EVENT_CONFIRMED",
                reason="first Core Data Event was observed",
                actor="registration-saga",
            )
            now = _now()
            registration.status = "EVENT_CONFIRMED"
            registration.step = "EVENT_CONFIRMED"
            self._set_candidate_step(candidate.candidate_id, registration.step)
            registration.completed_at = now
            registration.updated_at = now
            registration.last_error = None
            registration.last_error_code = None
            return self.store.put_registration(registration)
        if (
            registration.event_deadline is not None
            and _now() >= registration.event_deadline
        ):
            rollback_errors = self._rollback(registration)
            suffix = (
                f"; rollback pending: {', '.join(rollback_errors)}"
                if rollback_errors
                else ""
            )
            return self._fail(
                candidate,
                registration,
                code="FIRST_EVENT_TIMEOUT",
                message=(
                    "first Core Data Event was not received before timeout"
                    f"{suffix}"
                ),
            )
        registration.step = "WAITING_FIRST_EVENT"
        registration.updated_at = _now()
        return self.store.put_registration(registration)

    def _fail(
        self,
        candidate: Any,
        registration: RegistrationRecord,
        *,
        code: str,
        message: str,
    ) -> RegistrationRecord:
        current = self.registry.get_stored_candidate(candidate.candidate_id)
        if current.state in {
            "APPROVED",
            "SERVICE_READY",
            "METADATA_REGISTERED",
        }:
            self.registry.transition(
                candidate.candidate_id,
                "FAILED",
                reason=message,
                actor="registration-saga",
                error_code=code,
            )
        registration.status = "FAILED"
        registration.step = "FAILED"
        self._set_candidate_step(candidate.candidate_id, registration.step)
        registration.last_error_code = code
        registration.last_error = message
        registration.updated_at = _now()
        return self.store.put_registration(registration)

    def _rollback(self, registration: RegistrationRecord) -> list[str]:
        errors: list[str] = []
        dependent_cleanup_safe = True
        if registration.created_device and registration.device_name:
            try:
                self.edge_x.delete_owned_device(
                    registration.device_name,
                    candidate_id=registration.candidate_id,
                )
                registration.created_device = False
            except Exception as exc:
                dependent_cleanup_safe = False
                errors.append(f"device:{exc.__class__.__name__}")
        if (
            dependent_cleanup_safe
            and registration.created_profile
            and registration.profile_name
        ):
            try:
                self.edge_x.delete_unused_profile(registration.profile_name)
                registration.created_profile = False
            except Exception as exc:
                errors.append(f"profile:{exc.__class__.__name__}")
        if (
            dependent_cleanup_safe
            and registration.created_runtime
            and registration.runtime_name
        ):
            try:
                request_id = _sha(
                    f"{registration.candidate_id}|rollback|"
                    f"{registration.attempt}"
                )
                self.runtime_service.retire_runtime(
                    registration.runtime_name,
                    RuntimeActionRequest(
                        request_id=request_id,
                        payload_hash=_sha(
                            f"rollback|{registration.runtime_name}"
                        ),
                    ),
                )
                registration.created_runtime = False
            except Exception as exc:
                errors.append(f"runtime:{exc.__class__.__name__}")
        return errors

    @staticmethod
    def _device_name(candidate: Any, binding: DeviceBinding) -> str:
        stable = re.sub(
            r"[^a-z0-9-]+",
            "-",
            str(candidate.hardware_id).casefold(),
        ).strip("-")
        identity_suffix = candidate.identity_hash[:10]
        available = (
            63
            - len(binding.device_name_prefix)
            - len(identity_suffix)
            - 2
        )
        stable_prefix = stable[: max(0, available)].strip("-")
        if stable_prefix:
            return (
                f"{binding.device_name_prefix}-"
                f"{stable_prefix}-{identity_suffix}"
            )
        return f"{binding.device_name_prefix}-{identity_suffix}"

    @staticmethod
    def _device_document(
        candidate: Any,
        binding: DeviceBinding,
        registration: RegistrationRecord,
    ) -> dict[str, Any]:
        connection = deepcopy(binding.connection)
        for target_name, source_name in binding.connection_property_map.items():
            if source_name == "$devicePath":
                value = candidate.device_path
            else:
                value = candidate.properties.get(source_name)
            if value is None or value == "":
                raise ValueError(
                    f"candidate is missing connection source {source_name!r}"
                )
            connection[target_name] = value
        protocol_name = binding.edge_x_protocol or candidate.protocol
        service_name = str(registration.service_name or "")
        if not service_name:
            raise ValueError("registration is missing the resolved Device Service name")
        return {
            "name": registration.device_name,
            "description": (
                f"Approved {candidate.model or candidate.protocol} device "
                f"on {candidate.node_name}"
            ),
            "adminState": "UNLOCKED",
            "operatingState": "UNKNOWN",
            "labels": [
                "physical-device",
                "discovery-approved",
                candidate.protocol,
            ],
            "serviceName": service_name,
            "profileName": binding.profile.name,
            "protocols": {
                protocol_name: connection
            },
            "autoEvents": [
                item.model_dump(by_alias=True)
                for item in binding.auto_events
            ],
            "tags": {
                "controllerCandidateId": candidate.candidate_id,
                "hardwareId": candidate.hardware_id,
                "nodeName": candidate.node_name,
                "catalogBindingId": binding.binding_id,
            },
            "properties": {},
        }

    def _remember_response(
        self,
        scope: str,
        request: Any,
        view: CandidateView,
    ) -> None:
        try:
            self.store.put_idempotent_response(
                scope,
                request.request_ref.request_id,
                request.request_ref.payload_hash,
                view.model_dump(
                    by_alias=True,
                    mode="json",
                    exclude_none=True,
                ),
            )
        except DiscoveryStoreError as exc:
            raise ControllerConflict(str(exc)) from exc

    def _get_replay(
        self,
        scope: str,
        request: Any,
    ) -> dict[str, Any] | None:
        try:
            return self.store.get_idempotent_response(
                scope,
                request.request_ref.request_id,
                request.request_ref.payload_hash,
            )
        except DiscoveryStoreError as exc:
            raise ControllerConflict(str(exc)) from exc

    def _set_candidate_step(self, candidate_id: str, step: str) -> None:
        candidate = self.registry.get_stored_candidate(candidate_id)
        candidate.registration_step = step
        self.registry.save_candidate(candidate)
