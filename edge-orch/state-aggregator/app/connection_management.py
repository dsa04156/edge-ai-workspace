from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from .adapter_runtime_models import (
    RuntimeActionRequest,
    RuntimeCreateRequest,
    RuntimePlanRequest,
    RuntimeRequestRef,
)
from .connection_management_models import (
    ConnectionOnboardingRequest,
    ConnectionOperation,
    ConnectionValidationResult,
)
from .device_management import ManagementApplyError
from .device_management_models import (
    DeviceOnboardingRequest,
    ValidationIssue,
)


audit_logger = logging.getLogger("app.connection_management.audit")


class ConnectionManagementError(RuntimeError):
    pass


class ConnectionIdempotencyConflict(ConnectionManagementError):
    pass


class ConnectionOperationNotFound(ConnectionManagementError):
    pass


class ConnectionValidationError(ConnectionManagementError):
    def __init__(self, result: ConnectionValidationResult) -> None:
        self.result = result
        super().__init__("connection validation failed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectionManagementService:
    def __init__(
        self,
        runtime_service: Any,
        device_management: Any,
        *,
        hmac_key: str,
        operation_limit: int = 256,
    ) -> None:
        if not hmac_key:
            raise ValueError("connection management HMAC key must not be empty")
        if isinstance(operation_limit, bool) or operation_limit < 1:
            raise ValueError("operation_limit must be positive")
        self.runtime_service = runtime_service
        self.device_management = device_management
        self._hmac_key = hmac_key.encode("utf-8")
        self._operation_limit = operation_limit
        self._operations: OrderedDict[str, ConnectionOperation] = OrderedDict()
        self._requests: OrderedDict[str, ConnectionOnboardingRequest] = OrderedDict()
        self._lock = asyncio.Lock()

    async def validate(
        self,
        request: ConnectionOnboardingRequest,
        *,
        actor: str = "anonymous",
    ) -> ConnectionValidationResult:
        runtime_request = self._runtime_request(request)
        runtime_plan = await self.runtime_service.plan_runtime(runtime_request)
        issues: list[ValidationIssue] = []
        issues.extend(
            self.device_management.validate_runtime_settings(
                request.adapter_id,
                request.runtime.settings,
            )
        )
        if not runtime_plan.allowed:
            issues.extend(
                ValidationIssue(
                    code=item.code,
                    field="runtime",
                    message=item.message,
                )
                for item in runtime_plan.reasons
            )
        device_request = self._device_request(request)
        device_result = await self.device_management.validate(
            device_request,
            actor=actor,
            service_name_override=runtime_plan.service_name,
            node_name_override=runtime_plan.target_node,
            allow_unregistered_service=runtime_plan.action == "DEPLOY",
        )
        issues.extend(device_result.issues)
        result = ConnectionValidationResult(
            valid=runtime_plan.allowed and device_result.valid and not issues,
            issues=issues,
            warnings=device_result.warnings,
            runtime_plan=runtime_plan,
            edge_x_plan=device_result.plan,
        )
        self._audit_validation(request, actor, result)
        return result

    async def create_connection(
        self,
        request: ConnectionOnboardingRequest,
        *,
        idempotency_key: str,
        actor: str,
    ) -> ConnectionOperation:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        request_id = self._request_id(idempotency_key)
        payload_hash = self._payload_hash(
            request.model_dump(by_alias=True, exclude_none=True)
        )
        async with self._lock:
            replay = self._replay_or_conflict(request_id, payload_hash)
            if replay is not None:
                return replay

            validation = await self.validate(request, actor=actor)
            if not validation.valid:
                raise ConnectionValidationError(validation)
            runtime_plan = validation.runtime_plan
            if (
                runtime_plan.action not in {"REUSE", "DEPLOY"}
                or not runtime_plan.runtime_name
                or not runtime_plan.service_name
            ):
                raise ConnectionValidationError(validation)

            now = _now()
            operation = ConnectionOperation(
                request_id=request_id,
                payload_hash=payload_hash,
                status="PLANNED",
                adapter_id=request.adapter_id,
                runtime_action=runtime_plan.action,
                runtime_name=runtime_plan.runtime_name,
                service_name=runtime_plan.service_name,
                device_name=request.device.name,
                profile_name=request.profile.name,
                actor=actor,
                started_at=now,
                updated_at=now,
            )
            self._remember(operation, request)
            if runtime_plan.action == "DEPLOY":
                try:
                    runtime = await self.runtime_service.apply_runtime(
                        runtime_plan.runtime_name,
                        RuntimeCreateRequest(
                            plan=self._runtime_request(request),
                            request_ref=RuntimeRequestRef(
                                request_id=request_id,
                                payload_hash=payload_hash,
                                plan_hash=runtime_plan.plan_hash,
                            ),
                        ),
                    )
                except Exception as exc:
                    operation.status = "FAILED"
                    operation.error = (
                        f"runtime apply failed: {exc.__class__.__name__}"
                    )
                    operation.updated_at = _now()
                    self._remember(operation, request)
                    self._audit_operation(operation)
                    return operation.model_copy(deep=True)
                if runtime.phase != "SERVICE_READY":
                    operation.status = "RUNTIME_REQUESTED"
                    operation.updated_at = _now()
                    self._remember(operation, request)
                    self._audit_operation(operation)
                    return operation.model_copy(deep=True)

            operation.status = "RUNTIME_READY"
            operation.updated_at = _now()
            operation = await self._apply_metadata(operation, request)
            self._remember(operation, request)
            self._audit_operation(operation)
            return operation.model_copy(deep=True)

    async def get_operation(self, request_id: str) -> ConnectionOperation:
        async with self._lock:
            operation = self._operations.get(request_id)
            request = self._requests.get(request_id)
            if operation is None:
                return await self._recover_from_device_operation(request_id)
            self._operations.move_to_end(request_id)
            if operation.status == "RUNTIME_REQUESTED" and request is not None:
                runtimes = await self.runtime_service.list_runtimes()
                runtime = next(
                    (
                        item
                        for item in runtimes
                        if item.runtime_name == operation.runtime_name
                    ),
                    None,
                )
                if runtime is not None and runtime.phase == "SERVICE_READY":
                    operation.status = "RUNTIME_READY"
                    operation.updated_at = _now()
                    operation = await self._apply_metadata(operation, request)
                    self._remember(operation, request)
                elif runtime is not None and runtime.phase == "FAILED":
                    operation.status = "FAILED"
                    operation.error = "Adapter runtime reconciliation failed"
                    operation.updated_at = _now()
                    self._remember(operation, request)
            elif operation.status == "WAITING_EVENT":
                device_operation = await self.device_management.get_operation(
                    request_id
                )
                self._apply_device_status(operation, device_operation)
                self._remember(operation, request)
            return operation.model_copy(deep=True)

    async def _apply_metadata(
        self,
        operation: ConnectionOperation,
        request: ConnectionOnboardingRequest,
    ) -> ConnectionOperation:
        try:
            device_operation = await self.device_management.create_device(
                self._device_request(request),
                idempotency_key=f"connection:{operation.request_id}",
                actor=operation.actor,
                service_name_override=operation.service_name,
                node_name_override=request.runtime.target_node,
                request_id_override=operation.request_id,
                payload_hash_override=operation.payload_hash,
            )
            self._apply_device_status(operation, device_operation)
            return operation
        except ManagementApplyError as exc:
            operation.error = (
                "EdgeX Metadata apply failed: "
                f"{exc.cause.__class__.__name__}"
            )
            operation.updated_at = _now()
            if operation.runtime_action != "DEPLOY":
                operation.status = "FAILED"
                return operation
            operation.status = "COMPENSATING"
            try:
                await self.runtime_service.retire_runtime(
                    operation.runtime_name,
                    self._compensation_request(operation),
                )
                operation.status = "COMPENSATED"
                operation.compensation_status = "runtime_retired"
            except Exception as compensation_error:
                operation.status = "FAILED"
                operation.compensation_status = (
                    "runtime_retire_failed:"
                    f"{compensation_error.__class__.__name__}"
                )
            operation.updated_at = _now()
            return operation
        except Exception as exc:
            operation.status = "FAILED"
            operation.error = (
                "EdgeX onboarding failed: "
                f"{exc.__class__.__name__}"
            )
            operation.updated_at = _now()
            return operation

    @staticmethod
    def _apply_device_status(
        operation: ConnectionOperation,
        device_operation: Any,
    ) -> None:
        operation.metadata_applied = bool(device_operation.metadata_applied)
        operation.first_event_verified = bool(
            device_operation.first_event_verified
        )
        if device_operation.status == "verified":
            operation.status = "ACTIVE"
            operation.error = None
        elif device_operation.status == "waiting_for_event":
            operation.status = "WAITING_EVENT"
            operation.error = device_operation.error
        elif device_operation.status == "metadata_applied":
            operation.status = "DEVICE_APPLIED"
            operation.error = device_operation.error
        else:
            operation.status = "FAILED"
            operation.error = device_operation.error
        operation.updated_at = _now()

    async def _recover_from_device_operation(
        self,
        request_id: str,
    ) -> ConnectionOperation:
        try:
            device_operation = await self.device_management.get_operation(
                request_id
            )
        except Exception as exc:
            raise ConnectionOperationNotFound(
                f"connection operation {request_id!r} was not found"
            ) from exc
        now = _now()
        operation = ConnectionOperation(
            request_id=request_id,
            payload_hash=device_operation.payload_hash,
            status="WAITING_EVENT",
            adapter_id="recovered",
            runtime_action="REUSE",
            runtime_name="recovered",
            service_name="recovered",
            device_name=device_operation.device_name,
            profile_name=device_operation.profile_name,
            actor="recovered",
            started_at=now,
            updated_at=now,
        )
        self._apply_device_status(operation, device_operation)
        self._remember(operation, None)
        return operation.model_copy(deep=True)

    def _replay_or_conflict(
        self,
        request_id: str,
        payload_hash: str,
    ) -> ConnectionOperation | None:
        operation = self._operations.get(request_id)
        if operation is None:
            return None
        if operation.payload_hash != payload_hash:
            raise ConnectionIdempotencyConflict(
                "idempotency key was used with a different connection payload"
            )
        self._operations.move_to_end(request_id)
        return operation.model_copy(deep=True)

    def _remember(
        self,
        operation: ConnectionOperation,
        request: ConnectionOnboardingRequest | None,
    ) -> None:
        self._operations[operation.request_id] = operation.model_copy(deep=True)
        self._operations.move_to_end(operation.request_id)
        if request is not None:
            self._requests[operation.request_id] = request.model_copy(deep=True)
            self._requests.move_to_end(operation.request_id)
        while len(self._operations) > self._operation_limit:
            forgotten, _ = self._operations.popitem(last=False)
            self._requests.pop(forgotten, None)
        while len(self._requests) > self._operation_limit:
            self._requests.popitem(last=False)

    def _request_id(self, idempotency_key: str) -> str:
        return hmac.new(
            self._hmac_key,
            idempotency_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _runtime_request(
        request: ConnectionOnboardingRequest,
    ) -> RuntimePlanRequest:
        return RuntimePlanRequest(
            adapter_id=request.adapter_id,
            target_node=request.runtime.target_node,
            hardware_binding_id=request.runtime.hardware_binding_id,
            mode=request.runtime.mode,
            settings=request.runtime.settings,
        )

    @staticmethod
    def _device_request(
        request: ConnectionOnboardingRequest,
    ) -> DeviceOnboardingRequest:
        return DeviceOnboardingRequest(
            adapter_id=request.adapter_id,
            hardware_binding_id=request.runtime.hardware_binding_id,
            device=request.device,
            profile=request.profile,
        )

    @staticmethod
    def _compensation_request(
        operation: ConnectionOperation,
    ) -> RuntimeActionRequest:
        request_id = hashlib.sha256(
            f"{operation.request_id}:runtime-retire".encode("utf-8")
        ).hexdigest()
        payload_hash = hashlib.sha256(
            f"{operation.payload_hash}:runtime-retire".encode("utf-8")
        ).hexdigest()
        return RuntimeActionRequest(
            request_id=request_id,
            payload_hash=payload_hash,
        )

    @staticmethod
    def _audit_validation(
        request: ConnectionOnboardingRequest,
        actor: str,
        result: ConnectionValidationResult,
    ) -> None:
        audit_logger.info(
            json.dumps(
                {
                    "eventType": "connection_management_audit",
                    "action": "validate",
                    "actor": actor,
                    "targetDevice": request.device.name,
                    "runtimeAction": result.runtime_plan.action,
                    "status": "valid" if result.valid else "invalid",
                    "issueCodes": [item.code for item in result.issues],
                    "timestamp": _now().isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    @staticmethod
    def _audit_operation(operation: ConnectionOperation) -> None:
        audit_logger.info(
            json.dumps(
                {
                    "eventType": "connection_management_audit",
                    "requestId": operation.request_id,
                    "actor": operation.actor,
                    "action": "connect",
                    "runtimeAction": operation.runtime_action,
                    "runtimeName": operation.runtime_name,
                    "targetDevice": operation.device_name,
                    "targetProfile": operation.profile_name,
                    "status": operation.status,
                    "metadataApplied": operation.metadata_applied,
                    "firstEventVerified": operation.first_event_verified,
                    "compensationStatus": operation.compensation_status,
                    "error": operation.error,
                    "startedAt": operation.started_at.isoformat(),
                    "updatedAt": operation.updated_at.isoformat(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
