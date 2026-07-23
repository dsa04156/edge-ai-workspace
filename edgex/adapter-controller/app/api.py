from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from .config import Settings
from .models import (
    RuntimeActionRequest,
    RuntimeCreateRequest,
    RuntimeObservation,
    RuntimePlan,
    RuntimePlanRequest,
)


class ControllerError(RuntimeError):
    pass


class ControllerNotFound(ControllerError):
    pass


class ControllerConflict(ControllerError):
    pass


class ControllerValidationError(ControllerError):
    pass


def create_controller_router(settings: Settings, service: Any) -> APIRouter:
    if not settings.internal_hmac_key:
        raise ValueError("Adapter Controller internal HMAC key is required")

    router = APIRouter()

    async def require_signature(
        request: Request,
        timestamp_header: Annotated[
            str | None,
            Header(alias="X-Controller-Timestamp"),
        ] = None,
        signature_header: Annotated[
            str | None,
            Header(alias="X-Controller-Signature"),
        ] = None,
    ) -> None:
        try:
            timestamp = int(timestamp_header or "")
        except ValueError:
            timestamp = 0
        if abs(int(time.time()) - timestamp) > settings.signature_max_age_seconds:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="valid internal request signature required",
            )
        body = await request.body()
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = (
            f"{timestamp}\n{request.method.upper()}\n"
            f"{request.url.path}\n{body_hash}"
        ).encode("utf-8")
        expected = hmac.new(
            settings.internal_hmac_key.encode("utf-8"),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        if not signature_header or not hmac.compare_digest(
            signature_header,
            expected,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="valid internal request signature required",
            )

    def require_mutation_enabled() -> None:
        if not settings.mutation_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )

    async def invoke(call: Any) -> Any:
        try:
            return await asyncio.to_thread(call)
        except ControllerNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except ControllerConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ControllerValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Adapter Controller backend operation failed",
            ) from exc

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @router.get(
        "/internal/v1/runtimes",
        response_model=list[RuntimeObservation],
    )
    async def list_runtimes(
        request: Request,
        timestamp_header: Annotated[
            str | None,
            Header(alias="X-Controller-Timestamp"),
        ] = None,
        signature_header: Annotated[
            str | None,
            Header(alias="X-Controller-Signature"),
        ] = None,
    ) -> Any:
        await require_signature(request, timestamp_header, signature_header)
        return await invoke(service.list_runtimes)

    @router.post(
        "/internal/v1/runtimes/plan",
        response_model=RuntimePlan,
    )
    async def plan_runtime(
        payload: RuntimePlanRequest,
        request: Request,
        timestamp_header: Annotated[
            str | None,
            Header(alias="X-Controller-Timestamp"),
        ] = None,
        signature_header: Annotated[
            str | None,
            Header(alias="X-Controller-Signature"),
        ] = None,
    ) -> Any:
        await require_signature(request, timestamp_header, signature_header)
        return await invoke(lambda: service.plan(payload))

    @router.put(
        "/internal/v1/runtimes/{name}",
        response_model=RuntimeObservation,
        status_code=status.HTTP_201_CREATED,
    )
    async def apply_runtime(
        name: str,
        payload: RuntimeCreateRequest,
        request: Request,
        timestamp_header: Annotated[
            str | None,
            Header(alias="X-Controller-Timestamp"),
        ] = None,
        signature_header: Annotated[
            str | None,
            Header(alias="X-Controller-Signature"),
        ] = None,
    ) -> Any:
        await require_signature(request, timestamp_header, signature_header)
        require_mutation_enabled()
        return await invoke(lambda: service.apply_runtime(name, payload))

    @router.post(
        "/internal/v1/runtimes/{name}/restart",
        response_model=RuntimeObservation,
    )
    async def restart_runtime(
        name: str,
        payload: RuntimeActionRequest,
        request: Request,
        timestamp_header: Annotated[
            str | None,
            Header(alias="X-Controller-Timestamp"),
        ] = None,
        signature_header: Annotated[
            str | None,
            Header(alias="X-Controller-Signature"),
        ] = None,
    ) -> Any:
        await require_signature(request, timestamp_header, signature_header)
        require_mutation_enabled()
        return await invoke(lambda: service.restart_runtime(name, payload))

    @router.delete(
        "/internal/v1/runtimes/{name}",
        response_model=RuntimeObservation,
    )
    async def retire_runtime(
        name: str,
        payload: RuntimeActionRequest,
        request: Request,
        confirm_runtime: Annotated[
            str | None,
            Header(alias="X-Confirm-Runtime"),
        ] = None,
        timestamp_header: Annotated[
            str | None,
            Header(alias="X-Controller-Timestamp"),
        ] = None,
        signature_header: Annotated[
            str | None,
            Header(alias="X-Controller-Signature"),
        ] = None,
    ) -> Any:
        await require_signature(request, timestamp_header, signature_header)
        require_mutation_enabled()
        if confirm_runtime != name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact runtime confirmation is required",
            )
        return await invoke(lambda: service.retire_runtime(name, payload))

    return router
