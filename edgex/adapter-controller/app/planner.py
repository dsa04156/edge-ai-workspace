from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from .catalog import RuntimeTemplateCatalog
from .models import (
    PlanReason,
    RuntimeObservation,
    RuntimePlan,
    RuntimePlanRequest,
    RuntimeTemplate,
)


class RuntimePlanner:
    def __init__(self, catalog: RuntimeTemplateCatalog) -> None:
        self.catalog = catalog

    def plan(
        self,
        request: RuntimePlanRequest,
        observations: Iterable[RuntimeObservation],
        *,
        target_node_ready: bool = True,
    ) -> RuntimePlan:
        try:
            template = self.catalog.require_adapter(request.adapter_id)
        except ValueError:
            return self._blocked(
                request,
                template=None,
                code="unknown_adapter",
                message="요청한 Adapter가 승인 catalog에 없습니다.",
            )

        if template.verification_state == "unverified":
            return self._blocked(
                request,
                template=template,
                code="template_unverified",
                message="실장비와 Device Service 검증 전에는 배포할 수 없습니다.",
            )

        binding = next(
            (
                item
                for item in template.hardware_bindings
                if item.binding_id == request.hardware_binding_id
            ),
            None,
        )
        if binding is None:
            return self._blocked(
                request,
                template=template,
                code="hardware_binding_not_allowed",
                message="hardware binding이 승인 template에 없습니다.",
            )
        if binding.node_name != request.target_node:
            return self._blocked(
                request,
                template=template,
                code="node_not_allowed",
                message="hardware binding과 target node 조합이 일치하지 않습니다.",
            )
        if not target_node_ready:
            return self._blocked(
                request,
                template=template,
                code="node_not_ready",
                message="대상 KubeEdge node가 Ready 상태가 아닙니다.",
            )

        existing = next(
            (
                item
                for item in observations
                if item.hardware_binding_id == request.hardware_binding_id
            ),
            None,
        )
        if existing is not None:
            if existing.phase != "SERVICE_READY":
                return self._blocked(
                    request,
                    template=template,
                    code="runtime_not_ready",
                    message="동일 hardware binding의 runtime이 아직 준비되지 않았습니다.",
                )
            if request.mode == "deploy":
                return self._blocked(
                    request,
                    template=template,
                    code="hardware_binding_in_use",
                    message="동일 hardware binding에 기존 runtime이 있어 재사용해야 합니다.",
                )
            return self._result(
                request=request,
                template=template,
                action="REUSE",
                allowed=True,
                runtime_name=existing.runtime_name,
                service_name=existing.service_name,
                management_mode=existing.management_mode,
            )

        if request.mode == "reuse":
            return self._blocked(
                request,
                template=template,
                code="runtime_not_found",
                message="재사용할 수 있는 runtime이 없습니다.",
            )
        if not template.deployment_enabled:
            return self._blocked(
                request,
                template=template,
                code="template_not_deployable",
                message="template는 등록되어 있지만 신규 배포 승인이 아직 없습니다.",
            )

        identity = self._runtime_identity(template, request)
        return self._result(
            request=request,
            template=template,
            action="DEPLOY",
            allowed=True,
            runtime_name=identity,
            service_name=identity,
            management_mode="controller",
        )

    def _blocked(
        self,
        request: RuntimePlanRequest,
        *,
        template: RuntimeTemplate | None,
        code: str,
        message: str,
    ) -> RuntimePlan:
        return self._result(
            request=request,
            template=template,
            action="BLOCKED",
            allowed=False,
            reasons=[PlanReason(code=code, message=message)],
        )

    def _result(
        self,
        *,
        request: RuntimePlanRequest,
        template: RuntimeTemplate | None,
        action: str,
        allowed: bool,
        runtime_name: str | None = None,
        service_name: str | None = None,
        management_mode: str | None = None,
        reasons: list[PlanReason] | None = None,
    ) -> RuntimePlan:
        payload = {
            "action": action,
            "allowed": allowed,
            "adapterId": request.adapter_id,
            "templateId": template.template_id if template else None,
            "runtimeName": runtime_name,
            "serviceName": service_name,
            "targetNode": request.target_node,
            "hardwareBindingId": request.hardware_binding_id,
            "managementMode": management_mode,
            "verificationState": (
                template.verification_state if template else "unverified"
            ),
            "reasons": [
                item.model_dump(by_alias=True)
                for item in (reasons or [])
            ],
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return RuntimePlan.model_validate(
            {
                **payload,
                "planHash": hashlib.sha256(canonical).hexdigest(),
            }
        )

    @staticmethod
    def _runtime_identity(
        template: RuntimeTemplate,
        request: RuntimePlanRequest,
    ) -> str:
        digest = hashlib.sha256(
            (
                f"{template.template_id}\0{request.target_node}\0"
                f"{request.hardware_binding_id}"
            ).encode("utf-8")
        ).hexdigest()[:10]
        prefix = re.sub(r"[^a-z0-9-]+", "-", request.adapter_id).strip("-")
        prefix = prefix[:40].rstrip("-")
        return f"adapter-{prefix}-{digest}"[:63].rstrip("-")
