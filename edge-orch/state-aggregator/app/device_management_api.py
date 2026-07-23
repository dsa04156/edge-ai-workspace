from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status

from .config import Settings
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
    settings: Settings, management_service: Any
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

    return router
