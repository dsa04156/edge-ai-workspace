from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from .config import Settings
from .discovery_models import (
    CandidateDecisionUpdate,
    CandidateDecommissionRequest,
    CandidateDeleteRequest,
    CandidateApprovalRequest,
    CandidatePage,
    CandidateRejectRequest,
    CandidateRetryRequest,
    CandidateView,
    CandidatePresence,
    DiscoveryAuditEvent,
    DiscoveryInventory,
    DiscoveryPlan,
    DiscoveryProtocol,
    DiscoveryReconcileRequest,
    DiscoveryState,
    ManualCandidateCreate,
    NodeDiscoveryReport,
    RegistrationRecord,
)
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
                headers={"X-Error-Code": "INTERNAL_SIGNATURE_INVALID"},
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
                headers={"X-Error-Code": "INTERNAL_SIGNATURE_INVALID"},
            )

    def require_mutation_enabled() -> None:
        if not settings.mutation_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
                headers={"X-Error-Code": "FEATURE_DISABLED"},
            )

    def require_discovery_enabled() -> None:
        if not settings.device_discovery_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
                headers={"X-Error-Code": "FEATURE_DISABLED"},
            )

    async def invoke(call: Any) -> Any:
        try:
            return await asyncio.to_thread(call)
        except ControllerNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
                headers={"X-Error-Code": "RESOURCE_NOT_FOUND"},
            ) from exc
        except ControllerConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
                headers={"X-Error-Code": "STATE_CONFLICT"},
            ) from exc
        except ControllerValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
                headers={"X-Error-Code": "REQUEST_NOT_ALLOWED"},
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Adapter Controller backend operation failed",
                headers={"X-Error-Code": "BACKEND_OPERATION_FAILED"},
            ) from exc

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @router.get("/metrics", response_class=Response)
    async def metrics() -> Response:
        if not settings.device_discovery_enabled:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not Found",
            )
        payload = await invoke(service.discovery_metrics)
        return Response(
            content=payload,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

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

    @router.get(
        "/internal/v1/discovery",
        response_model=DiscoveryInventory,
    )
    async def list_discovery_inventory(
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
        require_discovery_enabled()
        return await invoke(service.list_discovery_inventory)

    @router.post(
        "/internal/v1/discovery/reports",
        response_model=DiscoveryInventory,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def ingest_discovery_report(
        payload: NodeDiscoveryReport,
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
        require_discovery_enabled()
        return await invoke(lambda: service.ingest_discovery_report(payload))

    @router.post(
        "/internal/v1/discovery/manual",
        response_model=CandidateView,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_manual_candidate(
        payload: ManualCandidateCreate,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(lambda: service.create_manual_candidate(payload))

    @router.patch(
        "/internal/v1/discovery/{candidate_id}",
        response_model=CandidateView,
    )
    async def update_candidate_decision(
        candidate_id: str,
        payload: CandidateDecisionUpdate,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(
            lambda: service.update_candidate_decision(candidate_id, payload)
        )

    @router.delete(
        "/internal/v1/discovery/{candidate_id}",
        response_model=CandidateView,
    )
    async def delete_candidate(
        candidate_id: str,
        payload: CandidateDeleteRequest,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(lambda: service.delete_candidate(candidate_id, payload))

    @router.post(
        "/internal/v1/discovery/{candidate_id}/decommission",
        response_model=CandidateView,
    )
    async def decommission_candidate(
        candidate_id: str,
        payload: CandidateDecommissionRequest,
        request: Request,
        confirm_candidate: Annotated[
            str | None,
            Header(alias="X-Confirm-Candidate"),
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
        require_discovery_enabled()
        require_mutation_enabled()
        if confirm_candidate != candidate_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="exact candidate confirmation is required",
            )
        return await invoke(
            lambda: service.decommission_candidate(candidate_id, payload)
        )

    @router.get(
        "/api/v1/discovery/candidates",
        response_model=CandidatePage,
    )
    async def list_discovery_candidates_v1(
        request: Request,
        protocol: DiscoveryProtocol | None = None,
        node_id: str | None = Query(default=None, alias="nodeId"),
        state_filter: DiscoveryState | None = Query(
            default=None,
            alias="state",
        ),
        presence: CandidatePresence | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, alias="pageSize", ge=1, le=500),
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
        require_discovery_enabled()
        inventory = await invoke(service.list_discovery_inventory)
        raw_candidates = (
            inventory.candidates
            if hasattr(inventory, "candidates")
            else inventory.get("candidates", [])
        )
        candidates = [
            item
            if isinstance(item, CandidateView)
            else CandidateView.model_validate(item)
            for item in raw_candidates
        ]
        items = [
            item
            for item in candidates
            if (protocol is None or item.protocol == protocol)
            and (node_id is None or item.node_name == node_id)
            and (state_filter is None or item.state == state_filter)
            and (presence is None or item.presence == presence)
        ]
        start = (page - 1) * page_size
        return CandidatePage(
            items=items[start : start + page_size],
            total=len(items),
            page=page,
            page_size=page_size,
        )

    @router.get(
        "/api/v1/discovery/candidates/{candidate_id}",
        response_model=CandidateView,
    )
    async def get_discovery_candidate_v1(
        candidate_id: str,
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
        require_discovery_enabled()
        return await invoke(lambda: service.get_candidate(candidate_id))

    @router.post(
        "/api/v1/discovery/candidates/{candidate_id}/approve",
        response_model=CandidateView,
    )
    async def approve_discovery_candidate_v1(
        candidate_id: str,
        payload: CandidateApprovalRequest,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(
            lambda: service.approve_candidate(candidate_id, payload)
        )

    @router.post(
        "/api/v1/discovery/candidates/{candidate_id}/reject",
        response_model=CandidateView,
    )
    async def reject_discovery_candidate_v1(
        candidate_id: str,
        payload: CandidateRejectRequest,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(
            lambda: service.reject_candidate(candidate_id, payload)
        )

    @router.post(
        "/api/v1/discovery/candidates/{candidate_id}/retry",
        response_model=CandidateView,
    )
    async def retry_discovery_candidate_v1(
        candidate_id: str,
        payload: CandidateRetryRequest,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(
            lambda: service.retry_candidate(candidate_id, payload)
        )

    @router.post("/api/v1/discovery/reconcile")
    async def reconcile_discovery_v1(
        payload: DiscoveryReconcileRequest,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(lambda: service.reconcile_discovery(payload))

    @router.get(
        "/internal/v1/discovery/plans/{node_id}",
        response_model=DiscoveryPlan,
    )
    @router.get(
        "/api/v1/discovery/plans/{node_id}",
        response_model=DiscoveryPlan,
    )
    async def get_discovery_plan_v1(
        node_id: str,
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
        require_discovery_enabled()
        return await invoke(lambda: service.get_discovery_plan(node_id))

    @router.put(
        "/api/v1/discovery/plans/{node_id}",
        response_model=DiscoveryPlan,
    )
    async def put_discovery_plan_v1(
        node_id: str,
        payload: DiscoveryPlan,
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
        require_discovery_enabled()
        require_mutation_enabled()
        return await invoke(
            lambda: service.put_discovery_plan(node_id, payload)
        )

    @router.get(
        "/api/v1/registrations/{candidate_id}",
        response_model=RegistrationRecord,
    )
    async def get_registration_v1(
        candidate_id: str,
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
        require_discovery_enabled()
        return await invoke(lambda: service.get_registration(candidate_id))

    @router.get("/api/v1/catalog/bindings")
    async def list_device_bindings_v1(
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
        require_discovery_enabled()
        return await invoke(service.list_device_bindings)

    @router.get(
        "/api/v1/discovery/events",
        response_model=list[DiscoveryAuditEvent],
    )
    async def list_discovery_events_v1(
        request: Request,
        candidate_id: str | None = Query(
            default=None,
            alias="candidateId",
        ),
        limit: int = Query(default=200, ge=1, le=2000),
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
        require_discovery_enabled()
        return await invoke(
            lambda: service.list_discovery_events(
                candidate_id=candidate_id,
                limit=limit,
            )
        )

    return router
