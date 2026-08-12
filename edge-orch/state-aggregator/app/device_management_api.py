from __future__ import annotations

import hashlib
import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, status

from .config import Settings
from .adapter_controller_client import (
    AdapterControllerBackendError,
    AdapterControllerClientError,
    AdapterControllerConflictError,
    AdapterControllerNotFoundError,
    AdapterControllerResponseError,
    AdapterControllerValidationError,
)
from .adapter_runtime_models import (
    RuntimeActionRequest,
    RuntimeObservation,
    RuntimePlan,
    RuntimePlanRequest,
)
from .adapter_runtime_service import (
    ExternalRuntimeMutationError,
    RuntimeNotFoundError,
)
from .connection_management import (
    ConnectionIdempotencyConflict,
    ConnectionOperationNotFound,
    ConnectionValidationError,
)
from .connection_management_models import (
    ConnectionOnboardingRequest,
    ConnectionOperation,
    ConnectionValidationResult,
)
from .device_management import (
    DeviceProfileApplyError,
    DeviceProfileValidationError,
    IdempotencyConflict,
    ManagementApplyError,
    ManagementValidationError,
    OperationNotFound,
)
from .device_management_edgex import EdgeXManagementError
from .device_discovery_models import (
    CandidateDecommissionInput,
    CandidateDecisionInput,
    CandidateDecisionUpdate,
    CandidateMutationRef,
    CandidateView,
    DiscoveryInventory,
    DiscoveryProtocol,
    ManualCandidateInput,
)
from .device_management_models import (
    AdapterStatusView,
    DeviceOnboardingRequest,
    DevicePatchRequest,
    DeviceProfileApplyResult,
    DeviceProfileCreateRequest,
    DeviceProfileSummary,
    DeviceProfileValidationResult,
    ManagementOperation,
    ValidationResult,
)


def create_device_management_router(
    settings: Settings,
    management_service: Any,
    *,
    runtime_service: Any | None = None,
    connection_service: Any | None = None,
    discovery_service: Any | None = None,
) -> APIRouter:
    if settings.device_management_enabled:
        if not settings.device_management_hmac_key:
            raise ValueError(
                "device management HMAC key is required when management is enabled"
            )
    if settings.adapter_runtime_management_enabled and runtime_service is None:
        raise ValueError(
            "runtime management service is required when runtime management is enabled"
        )
    if settings.adapter_runtime_management_enabled and connection_service is None:
        raise ValueError(
            "connection management service is required when runtime management is enabled"
        )
    if settings.adapter_runtime_mutation_enabled and not (
        settings.adapter_runtime_management_enabled
        and settings.device_management_enabled
    ):
        raise ValueError(
            "runtime mutation requires runtime and device management to be enabled"
        )
    if settings.device_discovery_management_enabled and discovery_service is None:
        raise ValueError(
            "device discovery service is required when discovery management is enabled"
        )
    if settings.device_discovery_management_enabled and not (
        settings.adapter_runtime_management_enabled
        and settings.device_management_enabled
    ):
        raise ValueError(
            "device discovery management requires runtime and device management"
        )

    router = APIRouter(prefix="/management", tags=["device-management"])

    def require_management_mutation() -> str:
        if not settings.device_management_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        return "dashboard-operator"

    def require_idempotency_key(value: str | None) -> str:
        if value is None or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key header is required",
            )
        if len(value) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key header is too long",
            )
        return value

    def require_runtime_management() -> None:
        if not settings.adapter_runtime_management_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )

    def require_discovery_management() -> None:
        if not settings.device_discovery_management_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )

    def require_runtime_mutation() -> str:
        if not settings.adapter_runtime_mutation_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        return require_management_mutation()

    def runtime_action_request(
        action: str,
        name: str,
        idempotency_key: str,
    ) -> RuntimeActionRequest:
        hmac_key = settings.device_management_hmac_key
        if not hmac_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        request_id = hmac.new(
            hmac_key.encode("utf-8"),
            idempotency_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload_hash = hashlib.sha256(
            f"{action}\0{name}".encode("utf-8")
        ).hexdigest()
        return RuntimeActionRequest(
            request_id=request_id,
            payload_hash=payload_hash,
        )

    def candidate_mutation_ref(
        action: str,
        target: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> CandidateMutationRef:
        hmac_key = settings.device_management_hmac_key
        if not hmac_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        request_id = hmac.new(
            hmac_key.encode("utf-8"),
            idempotency_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        canonical = json.dumps(
            {
                "action": action,
                "target": target,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return CandidateMutationRef(
            request_id=request_id,
            payload_hash=hashlib.sha256(canonical).hexdigest(),
        )

    def map_runtime_error(exc: Exception) -> HTTPException:
        if isinstance(
            exc,
            (AdapterControllerNotFoundError, RuntimeNotFoundError),
        ):
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Adapter runtime was not found",
            )
        if isinstance(
            exc,
            (
                AdapterControllerConflictError,
                ExternalRuntimeMutationError,
            ),
        ):
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Adapter runtime request conflicts with current state",
            )
        if isinstance(exc, AdapterControllerValidationError):
            return HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Adapter runtime request is invalid",
            )
        if isinstance(
            exc,
            (
                AdapterControllerBackendError,
                AdapterControllerResponseError,
                AdapterControllerClientError,
            ),
        ):
            return HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Adapter Controller is unavailable",
            )
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Adapter runtime operation failed",
        )

    @router.get("/adapters", response_model=list[AdapterStatusView])
    async def get_adapters() -> list[AdapterStatusView]:
        try:
            adapters = await management_service.list_adapters()
            return [
                adapter.model_copy(
                    update={"mutation_enabled": settings.device_management_enabled}
                )
                for adapter in adapters
            ]
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX adapter state is unavailable",
            ) from exc

    @router.get("/profiles", response_model=list[DeviceProfileSummary])
    async def get_profiles() -> list[DeviceProfileSummary]:
        try:
            return await management_service.list_profiles()
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX Device Profile 목록을 조회할 수 없습니다.",
            ) from exc

    @router.post(
        "/profiles/validate",
        response_model=DeviceProfileValidationResult,
    )
    async def validate_profile(
        request: DeviceProfileCreateRequest,
    ) -> DeviceProfileValidationResult:
        try:
            return await management_service.validate_profile(
                request,
                actor="viewer",
            )
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX Device Profile 검증 상태를 조회할 수 없습니다.",
            ) from exc

    @router.post(
        "/profiles",
        response_model=DeviceProfileApplyResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_profile(
        request: DeviceProfileCreateRequest,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> DeviceProfileApplyResult:
        actor = require_management_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        try:
            return await management_service.create_profile(
                request,
                idempotency_key=idempotency_key,
                actor=actor,
            )
        except DeviceProfileValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.result.model_dump(by_alias=True),
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except DeviceProfileApplyError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "profileName": exc.profile_name,
                    "message": "EdgeX Device Profile 생성 또는 재조회에 실패했습니다.",
                },
            ) from exc
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX Metadata backend is unavailable",
            ) from exc

    @router.post("/devices/validate", response_model=ValidationResult)
    async def validate_device(request: DeviceOnboardingRequest) -> ValidationResult:
        try:
            return await management_service.validate(request, actor="viewer")
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX validation backend is unavailable",
            ) from exc

    @router.post(
        "/devices",
        response_model=ManagementOperation,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_device(
        request: DeviceOnboardingRequest,
        idempotency_key_header: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> ManagementOperation:
        actor = require_management_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        try:
            return await management_service.create_device(
                request,
                idempotency_key=idempotency_key,
                actor=actor,
            )
        except ManagementValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.result.model_dump(by_alias=True),
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ManagementApplyError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "requestId": exc.operation.request_id,
                    "status": exc.operation.status,
                    "message": "EdgeX Metadata apply failed",
                },
            ) from exc
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX Metadata backend is unavailable",
            ) from exc

    @router.patch("/devices/{name}", response_model=ManagementOperation)
    async def patch_device(
        name: str,
        patch: DevicePatchRequest,
        idempotency_key_header: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> ManagementOperation:
        actor = require_management_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        try:
            return await management_service.patch_device(
                name,
                patch,
                idempotency_key=idempotency_key,
                actor=actor,
            )
        except ManagementValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.result.model_dump(by_alias=True),
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ManagementApplyError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "requestId": exc.operation.request_id,
                    "status": exc.operation.status,
                    "message": "EdgeX Metadata patch failed",
                },
            ) from exc
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX Metadata backend is unavailable",
            ) from exc

    @router.delete("/devices/{name}", response_model=ManagementOperation)
    async def delete_device(
        name: str,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
        confirm_device: Annotated[
            str | None,
            Header(alias="X-Confirm-Device"),
        ] = None,
    ) -> ManagementOperation:
        actor = require_management_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        if confirm_device != name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact device confirmation is required",
            )
        try:
            return await management_service.delete_device(
                name,
                idempotency_key=idempotency_key,
                actor=actor,
            )
        except ManagementValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.result.model_dump(by_alias=True),
            ) from exc
        except IdempotencyConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ManagementApplyError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "requestId": exc.operation.request_id,
                    "status": exc.operation.status,
                    "message": "EdgeX Metadata delete failed",
                },
            ) from exc
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX Metadata backend is unavailable",
            ) from exc

    @router.get("/operations/{request_id}", response_model=ManagementOperation)
    async def get_operation(request_id: str) -> ManagementOperation:
        try:
            return await management_service.get_operation(request_id)
        except OperationNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="management operation not found",
            ) from exc
        except EdgeXManagementError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="EdgeX operation state is unavailable",
            ) from exc

    @router.get(
        "/adapter-runtimes",
        response_model=list[RuntimeObservation],
    )
    async def get_adapter_runtimes() -> list[RuntimeObservation]:
        require_runtime_management()
        try:
            runtimes = await runtime_service.list_runtimes()
            return [
                item.model_copy(
                    update={
                        "mutation_enabled": (
                            settings.adapter_runtime_mutation_enabled
                            and item.mutable
                        )
                    }
                )
                for item in runtimes
            ]
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.post(
        "/adapter-runtimes/plan",
        response_model=RuntimePlan,
    )
    async def plan_adapter_runtime(
        request: RuntimePlanRequest,
    ) -> RuntimePlan:
        require_runtime_management()
        try:
            return await runtime_service.plan_runtime(request)
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.post(
        "/adapter-runtimes/{name}/restart",
        response_model=RuntimeObservation,
    )
    async def restart_adapter_runtime(
        name: str,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> RuntimeObservation:
        require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        try:
            return await runtime_service.restart_runtime(
                name,
                runtime_action_request("restart", name, idempotency_key),
            )
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.delete(
        "/adapter-runtimes/{name}",
        response_model=RuntimeObservation,
    )
    async def retire_adapter_runtime(
        name: str,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
        confirm_runtime: Annotated[
            str | None,
            Header(alias="X-Confirm-Runtime"),
        ] = None,
    ) -> RuntimeObservation:
        require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        if confirm_runtime != name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact runtime confirmation is required",
            )
        try:
            return await runtime_service.retire_runtime(
                name,
                runtime_action_request("retire", name, idempotency_key),
            )
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.post(
        "/connections/validate",
        response_model=ConnectionValidationResult,
    )
    async def validate_connection(
        request: ConnectionOnboardingRequest,
    ) -> ConnectionValidationResult:
        require_runtime_management()
        try:
            return await connection_service.validate(
                request,
                actor="viewer",
            )
        except Exception as exc:
            if isinstance(exc, AdapterControllerClientError):
                raise map_runtime_error(exc) from exc
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Connection validation backend is unavailable",
            ) from exc

    @router.post(
        "/connections",
        response_model=ConnectionOperation,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_connection(
        request: ConnectionOnboardingRequest,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> ConnectionOperation:
        actor = require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        try:
            return await connection_service.create_connection(
                request,
                idempotency_key=idempotency_key,
                actor=actor,
            )
        except ConnectionValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.result.model_dump(by_alias=True),
            ) from exc
        except ConnectionIdempotencyConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ConnectionOperationNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="connection operation not found",
            ) from exc
        except AdapterControllerClientError as exc:
            raise map_runtime_error(exc) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Connection apply failed",
            ) from exc

    @router.get(
        "/connections/operations/{request_id}",
        response_model=ConnectionOperation,
    )
    async def get_connection_operation(
        request_id: str,
    ) -> ConnectionOperation:
        require_runtime_management()
        try:
            return await connection_service.get_operation(request_id)
        except ConnectionOperationNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="connection operation not found",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Connection operation state is unavailable",
            ) from exc

    @router.get(
        "/discovery",
        response_model=DiscoveryInventory,
    )
    async def get_discovery_inventory(
        q: str | None = Query(default=None, max_length=255),
        node: str | None = Query(default=None, max_length=253),
        protocol: DiscoveryProtocol | None = None,
        decision: str | None = Query(
            default=None,
            pattern=r"^(pending|accepted|ignored)$",
        ),
        presence: str | None = Query(
            default=None,
            pattern=r"^(present|stale|declared)$",
        ),
        include_ignored: bool = Query(default=False, alias="includeIgnored"),
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> DiscoveryInventory:
        require_discovery_management()
        try:
            inventory = await discovery_service.list_inventory()
        except Exception as exc:
            raise map_runtime_error(exc) from exc
        total = len(inventory.candidates)
        search = (q or "").strip().casefold()
        candidates = []
        for candidate in inventory.candidates:
            if not include_ignored and candidate.decision == "ignored":
                continue
            if node and candidate.node_name != node:
                continue
            if protocol and candidate.protocol != protocol:
                continue
            if decision and candidate.decision != decision:
                continue
            if presence and candidate.presence != presence:
                continue
            if search:
                searchable = " ".join(
                    [
                        candidate.candidate_id,
                        candidate.display_name,
                        candidate.node_name,
                        candidate.protocol,
                        candidate.transport,
                        candidate.device_path or "",
                        candidate.note,
                        candidate.decision_note,
                        *[str(value) for value in candidate.properties.values()],
                    ]
                ).casefold()
                if search not in searchable:
                    continue
            candidates.append(candidate)
        filtered = len(candidates)
        return inventory.model_copy(
            update={
                "candidates": candidates[:limit],
                "total_candidates": total,
                "filtered_candidates": filtered,
            }
        )

    @router.post(
        "/discovery/manual",
        response_model=CandidateView,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_manual_candidate(
        candidate: ManualCandidateInput,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> CandidateView:
        require_discovery_management()
        require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        payload = candidate.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        try:
            return await discovery_service.create_manual(
                candidate,
                candidate_mutation_ref(
                    "create",
                    "manual",
                    idempotency_key,
                    payload,
                ),
            )
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.patch(
        "/discovery/{candidate_id}",
        response_model=CandidateView,
    )
    async def update_candidate_decision(
        candidate_id: str,
        update: CandidateDecisionInput,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> CandidateView:
        require_discovery_management()
        require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        payload = update.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        request = CandidateDecisionUpdate(
            **payload,
            request_ref=candidate_mutation_ref(
                "decision",
                candidate_id,
                idempotency_key,
                payload,
            ),
        )
        try:
            return await discovery_service.update_decision(
                candidate_id,
                request,
            )
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.delete(
        "/discovery/{candidate_id}",
        response_model=CandidateView,
    )
    async def delete_candidate(
        candidate_id: str,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> CandidateView:
        require_discovery_management()
        require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        try:
            return await discovery_service.delete_candidate(
                candidate_id,
                candidate_mutation_ref(
                    "delete",
                    candidate_id,
                    idempotency_key,
                    {},
                ),
            )
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    @router.post(
        "/discovery/{candidate_id}/decommission",
        response_model=CandidateView,
    )
    async def decommission_candidate(
        candidate_id: str,
        decommission: CandidateDecommissionInput,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
        confirm_candidate: Annotated[
            str | None,
            Header(alias="X-Confirm-Candidate"),
        ] = None,
    ) -> CandidateView:
        actor = require_runtime_mutation()
        idempotency_key = require_idempotency_key(idempotency_key_header)
        if confirm_candidate != candidate_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact candidate confirmation is required",
            )
        payload = decommission.model_dump(
            by_alias=True,
            mode="json",
            exclude_none=True,
        )
        try:
            return await discovery_service.decommission_candidate(
                candidate_id,
                reason=decommission.reason,
                actor=actor,
                request_ref=candidate_mutation_ref(
                    "decommission",
                    candidate_id,
                    idempotency_key,
                    payload,
                ),
            )
        except Exception as exc:
            raise map_runtime_error(exc) from exc

    return router
