"""Separate operational API; the browser service designer remains a dry run."""
from __future__ import annotations

import hmac
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .model_offload_controller import ModelOffloadError, ModelOffloadExecutionController


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4096)
    max_tokens: int = Field(ge=1, le=256)


def create_model_offload_router(controller: ModelOffloadExecutionController | None,
                                token: str) -> APIRouter:
    router = APIRouter(prefix="/api/runtime-model-offloading", tags=["runtime-execution"])

    def active() -> ModelOffloadExecutionController:
        if controller is None:
            raise HTTPException(503, "model_offload_execution_disabled")
        return controller

    def authorize(value: str | None) -> None:
        if not token or not value or not hmac.compare_digest(value, token):
            raise HTTPException(403, "execution_token_required")

    @router.get("")
    async def state():
        return controller.snapshot() if controller else {"enabled": False, "reason_code": "model_offload_execution_disabled"}

    @router.get("/execution-plan")
    async def plan():
        return active().snapshot()["execution_plan"]

    @router.get("/history")
    async def history(limit: int = Query(default=100, ge=1, le=1000)):
        return {"items": active().journal.events(limit)}

    @router.get("/requests/{request_id}")
    async def request_status(request_id: str, x_execution_token: str | None = Header(default=None)):
        authorize(x_execution_token)
        item = active().journal.request(request_id)
        if item is None:
            raise HTTPException(404, "request_not_found")
        return item

    @router.post("/generate")
    async def generate(body: GenerateRequest, x_execution_token: str | None = Header(default=None)):
        authorize(x_execution_token)
        try:
            return await active().submit(body.request_id, body.prompt, body.max_tokens)
        except ModelOffloadError as exc:
            raise HTTPException(exc.status_code, exc.reason) from None

    return router
