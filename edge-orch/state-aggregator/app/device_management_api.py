from __future__ import annotations

import hashlib
import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status

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
    IdempotencyConflict,
    ManagementApplyError,
    ManagementValidationError,
    OperationNotFound,
)
from .device_management_edgex import EdgeXManagementError
from .device_management_models import (
    AdapterStatusView,
    DeviceOnboardingRequest,
    DevicePatchRequest,
    ManagementOperation,
    ValidationResult,
)


def create_device_management_router(
    settings: Settings,
    management_service: Any,
    *,
    runtime_service: Any | None = None,
    connection_service: Any | None = None,
) -> APIRouter:
    if settings.device_management_enabled:
        if not settings.device_management_admin_token:
            raise ValueError(
                "device management admin token is required when management is enabled"
            )
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

    router = APIRouter(prefix="/management", tags=["device-management"])

    async def require_admin(
        authorization: Annotated[str | None, Header()] = None,
    ) -> str:
        if not settings.device_management_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
        scheme, separator, credential = (authorization or "").partition(" ")
        expected = settings.device_management_admin_token or ""
        if (
            separator != " "
            or scheme.lower() != "bearer"
            or not credential
            or not hmac.compare_digest(credential, expected)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="valid administrator bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return "dashboard-admin"

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

    async def require_runtime_admin(
        authorization: str | None,
    ) -> str:
        if not settings.adapter_runtime_mutation_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        return await require_admin(authorization)

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
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key_header: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> ManagementOperation:
        actor = await require_admin(authorization)
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
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key_header: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> ManagementOperation:
        actor = await require_admin(authorization)
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
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> RuntimeObservation:
        await require_runtime_admin(authorization)
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
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
        confirm_runtime: Annotated[
            str | None,
            Header(alias="X-Confirm-Runtime"),
        ] = None,
    ) -> RuntimeObservation:
        await require_runtime_admin(authorization)
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
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key_header: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> ConnectionOperation:
        actor = await require_runtime_admin(authorization)
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

    return router
