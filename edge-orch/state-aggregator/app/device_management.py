from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .adapter_catalog import AdapterCatalog
from .device_management_models import (
    AdapterStatusView,
    DeviceOnboardingRequest,
    DevicePatchRequest,
    ManagementOperation,
    ProfileTemplate,
    ValidationIssue,
    ValidationResult,
)
from .edgex import EdgeXError


DEVICE_REQUEST_ID_TAG = "edgeAiOnboardingRequestId"
DEVICE_PAYLOAD_HASH_TAG = "edgeAiOnboardingPayloadHash"
ONBOARDING_OPERATION_TAGS = frozenset(
    {DEVICE_REQUEST_ID_TAG, DEVICE_PAYLOAD_HASH_TAG}
)
IMMUTABLE_SYSTEM_TAGS = ONBOARDING_OPERATION_TAGS | {
    "nodeName",
    "physicalDeviceId",
    "hardwareBindingId",
}

audit_logger = logging.getLogger("app.device_management.audit")


class DeviceManagementError(RuntimeError):
    pass


class IdempotencyConflict(DeviceManagementError):
    pass


class OperationNotFound(DeviceManagementError):
    pass


class ManagementValidationError(DeviceManagementError):
    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__("device management validation failed")


class ManagementApplyError(DeviceManagementError):
    def __init__(self, operation: ManagementOperation, cause: Exception) -> None:
        self.operation = operation
        self.cause = cause
        super().__init__(operation.error or "device management apply failed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceManagementService:
    def __init__(
        self,
        catalog: AdapterCatalog,
        metadata: Any,
        events: Any,
        *,
        hmac_key: str,
        operation_limit: int = 256,
    ) -> None:
        if not hmac_key:
            raise ValueError("device management HMAC key must not be empty")
        if isinstance(operation_limit, bool) or operation_limit < 1:
            raise ValueError("operation_limit must be positive")
        self.catalog = catalog
        self.metadata = metadata
        self.events = events
        self._hmac_key = hmac_key.encode("utf-8")
        self._operation_limit = operation_limit
        self._operations: OrderedDict[str, ManagementOperation] = OrderedDict()
        self._mutation_lock = asyncio.Lock()

    async def list_adapters(self) -> list[AdapterStatusView]:
        services = {
            item.get("name"): item for item in await self.metadata.list_device_services()
        }
        result: list[AdapterStatusView] = []
        for adapter in self.catalog.adapters:
            status = adapter.declared_status
            reason = adapter.reason
            if status == "installed":
                service = services.get(adapter.service_name)
                if service is None:
                    if (
                        adapter.runtime.deployment_enabled
                        and adapter.runtime.verification_state != "unverified"
                    ):
                        status = "installable"
                        reason = (
                            "검증된 Device Service 패키지를 대상 노드에 "
                            "설치할 수 있습니다."
                        )
                    else:
                        status = "unavailable"
                        reason = "EdgeX Core Metadata에 Device Service가 없습니다."
                elif service.get("adminState") != "UNLOCKED":
                    status = "unavailable"
                    reason = "EdgeX Device Service가 UNLOCKED 상태가 아닙니다."
            result.append(
                AdapterStatusView(
                    adapter_id=adapter.adapter_id,
                    display_name=adapter.display_name,
                    service_name=adapter.service_name,
                    protocol_name=adapter.protocol_name,
                    node_name=adapter.node_name,
                    status=status,
                    reason=reason,
                    fields=deepcopy(adapter.fields),
                    profile_capabilities=deepcopy(adapter.profile_capabilities),
                    runtime=deepcopy(adapter.runtime),
                )
            )
        return result

    async def validate(
        self,
        request: DeviceOnboardingRequest,
        *,
        actor: str = "anonymous",
        service_name_override: str | None = None,
        node_name_override: str | None = None,
        allow_unregistered_service: bool = False,
    ) -> ValidationResult:
        protocol_issues = list(
            self.catalog.validate_protocol(
                request.adapter_id, request.device.protocol_properties
            )
        )
        if request.hardware_binding_id is not None:
            for issue in self.catalog.validate_hardware_binding(
                request.adapter_id,
                request.hardware_binding_id,
                request.device.protocol_properties,
            ):
                if not any(
                    existing.code == issue.code and existing.field == issue.field
                    for existing in protocol_issues
                ):
                    protocol_issues.append(issue)
        issues = list(protocol_issues)
        warnings: list[ValidationIssue] = []
        try:
            adapter = self.catalog.require(request.adapter_id)
        except ValueError:
            result = ValidationResult(valid=False, issues=issues)
            self._audit_validation(request, actor, result)
            return result
        service_name = self._effective_service_name(
            adapter,
            service_name_override,
        )
        node_name = self._effective_node_name(
            adapter,
            node_name_override,
        )

        for tag in sorted(set(request.device.tags) & ONBOARDING_OPERATION_TAGS):
            issues.append(
                ValidationIssue(
                    code="reserved_tag",
                    field=f"device.tags.{tag}",
                    message="onboarding operation tags are managed by the server",
                )
            )
        expected_system_tags = {
            "nodeName": node_name,
            "physicalDeviceId": request.device.protocol_properties.get("DeviceID"),
            "hardwareBindingId": request.hardware_binding_id,
        }
        for tag, expected in expected_system_tags.items():
            if (
                expected is not None
                and tag in request.device.tags
                and request.device.tags[tag] != expected
            ):
                issues.append(
                    ValidationIssue(
                        code="system_tag_mismatch",
                        field=f"device.tags.{tag}",
                        message=f"{tag} must match the selected adapter endpoint",
                    )
                )

        services = await self.metadata.list_device_services()
        service = next(
            (item for item in services if item.get("name") == service_name),
            None,
        )
        if adapter.declared_status == "installed" and (
            service is None or service.get("adminState") != "UNLOCKED"
        ) and not allow_unregistered_service:
            issues.append(
                ValidationIssue(
                    code="adapter_unavailable",
                    field="adapterId",
                    message="installed adapter의 EdgeX Device Service가 사용 가능하지 않습니다.",
                )
            )

        existing_device = await self.metadata.get_device(request.device.name)
        if existing_device is not None:
            issues.append(
                ValidationIssue(
                    code="device_exists",
                    field="device.name",
                    message=f"Device {request.device.name!r} already exists",
                )
            )

        if not protocol_issues:
            binding_owner = await self._protocol_binding_owner(
                        adapter,
                        request.device.protocol_properties,
                        exclude_name=request.device.name,
                        service_name=service_name,
                    )
            if binding_owner is not None:
                issues.append(
                    ValidationIssue(
                        code="protocol_binding_exists",
                        field="device.protocolProperties",
                        message=(
                            "protocol endpoint/resource is already bound to Device "
                            f"{binding_owner!r}"
                        ),
                    )
                )

        template: ProfileTemplate | None = None
        if not issues or all(
            issue.code in {"adapter_unavailable", "device_exists"} for issue in issues
        ):
            try:
                template = self.catalog.profile_template(
                    request.adapter_id, request.device.protocol_properties
                )
            except ValueError as exc:
                issues.append(
                    ValidationIssue(
                        code="profile_template_unavailable",
                        field="profile",
                        message=str(exc),
                    )
                )

        existing_profile = await self.metadata.get_profile(request.profile.name)
        if request.profile.mode == "existing":
            if existing_profile is None:
                issues.append(
                    ValidationIssue(
                        code="profile_missing",
                        field="profile.name",
                        message=f"Profile {request.profile.name!r} does not exist",
                    )
                )
            elif template is not None and not self._profile_matches_template(
                existing_profile, template
            ):
                issues.append(
                    ValidationIssue(
                        code="profile_incompatible",
                        field="profile.name",
                        message="existing Profile resources do not match the adapter endpoint",
                    )
                )
        elif existing_profile is not None:
            issues.append(
                ValidationIssue(
                    code="profile_exists",
                    field="profile.name",
                    message=f"Profile {request.profile.name!r} already exists",
                )
            )

        plan: dict[str, Any] = {}
        if template is not None:
            profile = (
                self._profile_document(request, template)
                if request.profile.mode == "create"
                else existing_profile
            )
            device = self._device_document(
                request,
                adapter,
                request_id=None,
                payload_hash=None,
                service_name=service_name,
                node_name=node_name,
            )
            mutations = ["create_device"]
            if request.profile.mode == "create":
                mutations.insert(0, "create_profile")
            plan = {
                "adapter": {
                    "adapterId": adapter.adapter_id,
                    "serviceName": service_name,
                    "protocolName": adapter.protocol_name,
                },
                "profile": profile,
                "device": device,
                "mutations": mutations,
                "verification": ["profile_readback", "device_readback", "first_event"],
            }

        result = ValidationResult(
            valid=not issues,
            issues=issues,
            warnings=warnings,
            plan=plan,
        )
        self._audit_validation(request, actor, result)
        return result

    async def create_device(
        self,
        request: DeviceOnboardingRequest,
        *,
        idempotency_key: str,
        actor: str,
        service_name_override: str | None = None,
        node_name_override: str | None = None,
        request_id_override: str | None = None,
        payload_hash_override: str | None = None,
    ) -> ManagementOperation:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        if (request_id_override is None) != (payload_hash_override is None):
            raise ValueError(
                "request_id_override and payload_hash_override must be provided together"
            )
        request_id = request_id_override or self._request_id(idempotency_key)
        hash_payload = request.model_dump(by_alias=True, exclude_none=True)
        if service_name_override is not None or node_name_override is not None:
            hash_payload["_bindingOverride"] = {
                "serviceName": service_name_override,
                "nodeName": node_name_override,
            }
        payload_hash = payload_hash_override or self._payload_hash(hash_payload)
        if re.fullmatch(r"[0-9a-f]{64}", request_id) is None:
            raise ValueError("request ID must be a 64-character lowercase hex digest")
        if re.fullmatch(r"[0-9a-f]{64}", payload_hash) is None:
            raise ValueError("payload hash must be a 64-character lowercase hex digest")
        async with self._mutation_lock:
            replay = self._replay_or_conflict(request_id, payload_hash)
            if replay is not None:
                return replay

            existing = await self.metadata.get_device(request.device.name)
            if existing is not None:
                recovered = await self._recover_matching_device(
                    existing,
                    request,
                    request_id,
                    payload_hash,
                    actor=actor,
                    service_name_override=service_name_override,
                    node_name_override=node_name_override,
                )
                if recovered is not None:
                    self._remember(recovered)
                    return recovered
                raise IdempotencyConflict(
                    f"Device {request.device.name!r} exists with a different operation"
                )

            result = await self.validate(
                request,
                actor=actor,
                service_name_override=service_name_override,
                node_name_override=node_name_override,
            )
            if not result.valid:
                raise ManagementValidationError(result)

            adapter = self.catalog.require(request.adapter_id)
            template = self.catalog.profile_template(
                request.adapter_id, request.device.protocol_properties
            )
            started_at = _now()
            operation = ManagementOperation(
                request_id=request_id,
                payload_hash=payload_hash,
                action="create",
                device_name=request.device.name,
                profile_name=request.profile.name,
                status="metadata_applied",
                actor=actor,
                started_at=started_at,
                updated_at=started_at,
            )
            created_profile = False
            try:
                if request.profile.mode == "create":
                    profile = self._profile_document(request, template)
                    await self.metadata.add_profile(profile)
                    created_profile = True
                    operation.created_profile = True
                    profile_readback = await self.metadata.get_profile(request.profile.name)
                    if profile_readback is None or not self._profile_matches_template(
                        profile_readback, template
                    ):
                        raise ValueError("Profile readback does not match the requested template")

                device = self._device_document(
                    request,
                    adapter,
                    request_id=request_id,
                    payload_hash=payload_hash,
                    service_name=self._effective_service_name(
                        adapter,
                        service_name_override,
                    ),
                    node_name=self._effective_node_name(
                        adapter,
                        node_name_override,
                    ),
                )
                await self.metadata.add_device(device)
                readback = await self.metadata.get_device(request.device.name)
                if readback is None or not self._device_readback_matches(readback, device):
                    raise ValueError("Device readback does not match the requested binding")

                operation.metadata_applied = True
                await self._refresh_event_status(operation)
                self._remember(operation)
                self._audit_operation(operation, idempotency_key=idempotency_key)
                return operation
            except Exception as exc:
                if created_profile:
                    await self._compensate_profile(request.profile.name)
                operation.status = "failed"
                operation.error = f"{exc.__class__.__name__}: {exc}"
                operation.updated_at = _now()
                self._remember(operation)
                self._audit_operation(operation, idempotency_key=idempotency_key)
                raise ManagementApplyError(operation, exc) from exc

    async def patch_device(
        self,
        name: str,
        patch: DevicePatchRequest,
        *,
        idempotency_key: str,
        actor: str,
    ) -> ManagementOperation:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        payload = {
            "name": name,
            "patch": patch.model_dump(by_alias=True, exclude_none=True),
        }
        request_id = self._request_id(idempotency_key)
        payload_hash = self._payload_hash(payload)
        async with self._mutation_lock:
            replay = self._replay_or_conflict(request_id, payload_hash)
            if replay is not None:
                return replay
            current = await self.metadata.get_device(name)
            if current is None:
                result = ValidationResult(
                    valid=False,
                    issues=[
                        ValidationIssue(
                            code="device_missing",
                            field="name",
                            message=f"Device {name!r} does not exist",
                        )
                    ],
                )
                raise ManagementValidationError(result)

            adapter = next(
                (
                    item
                    for item in self.catalog.adapters
                    if item.service_name == current.get("serviceName")
                    and item.protocol_name in (current.get("protocols") or {})
                ),
                None,
            )
            if adapter is None or adapter.declared_status != "installed":
                raise ManagementValidationError(
                    ValidationResult(
                        valid=False,
                        issues=[
                            ValidationIssue(
                                code="adapter_unavailable",
                                field="name",
                                message="Device is not managed by an installed catalog adapter",
                            )
                        ],
                    )
                )

            services = await self.metadata.list_device_services()
            device_service = next(
                (
                    item
                    for item in services
                    if item.get("name") == adapter.service_name
                ),
                None,
            )
            if (
                device_service is None
                or device_service.get("adminState") != "UNLOCKED"
            ):
                raise ManagementValidationError(
                    ValidationResult(
                        valid=False,
                        issues=[
                            ValidationIssue(
                                code="adapter_unavailable",
                                field="name",
                                message="Device Service is not currently available in Core Metadata",
                            )
                        ],
                    )
                )

            reserved_tags = sorted(set(patch.tags or {}) & IMMUTABLE_SYSTEM_TAGS)
            if reserved_tags:
                raise ManagementValidationError(
                    ValidationResult(
                        valid=False,
                        issues=[
                            ValidationIssue(
                                code="reserved_tag",
                                field=f"tags.{reserved_tags[0]}",
                                message="onboarding operation tags are managed by the server",
                            )
                        ],
                    )
                )

            update: dict[str, Any] = {}
            if patch.description is not None:
                update["description"] = patch.description
            if patch.labels is not None:
                update["labels"] = patch.labels
            if patch.admin_state is not None:
                update["adminState"] = patch.admin_state
            if patch.protocol_properties is not None:
                protocol_issues = self.catalog.validate_protocol(
                    adapter.adapter_id, patch.protocol_properties
                )
                if protocol_issues:
                    raise ManagementValidationError(
                        ValidationResult(valid=False, issues=protocol_issues)
                    )
                current_protocol = (
                    (current.get("protocols") or {}).get(adapter.protocol_name) or {}
                )
                changed_binding_fields = [
                    field_name
                    for field_name in adapter.runtime.reuse_policy.binding_fields
                    if patch.protocol_properties.get(field_name)
                    != current_protocol.get(field_name)
                ]
                if changed_binding_fields:
                    raise ManagementValidationError(
                        ValidationResult(
                            valid=False,
                            issues=[
                                ValidationIssue(
                                    code="hardware_binding_immutable",
                                    field="protocolProperties",
                                    message=(
                                        "physical hardware binding fields cannot be changed "
                                        f"by PATCH: {', '.join(changed_binding_fields)}"
                                    ),
                                )
                            ],
                        )
                    )
                binding_owner = await self._protocol_binding_owner(
                    adapter,
                    patch.protocol_properties,
                    exclude_name=name,
                    service_name=adapter.service_name,
                )
                if binding_owner is not None:
                    raise ManagementValidationError(
                        ValidationResult(
                            valid=False,
                            issues=[
                                ValidationIssue(
                                    code="protocol_binding_exists",
                                    field="protocolProperties",
                                    message=(
                                        "protocol endpoint/resource is already bound to Device "
                                        f"{binding_owner!r}"
                                    ),
                                )
                            ],
                        )
                    )
                template = self.catalog.profile_template(
                    adapter.adapter_id, patch.protocol_properties
                )
                profile = await self.metadata.get_profile(
                    str(current.get("profileName") or "")
                )
                if profile is None or not self._profile_matches_template(
                    profile, template
                ):
                    raise ManagementValidationError(
                        ValidationResult(
                            valid=False,
                            issues=[
                                ValidationIssue(
                                    code="profile_incompatible",
                                    field="protocolProperties",
                                    message="protocol endpoint does not match the bound Device Profile",
                                )
                            ],
                        )
                    )
                update["protocols"] = {
                    adapter.protocol_name: deepcopy(patch.protocol_properties)
                }
            if patch.tags is not None:
                tags = deepcopy(current.get("tags") or {})
                tags.update(deepcopy(patch.tags))
                update["tags"] = tags

            started_at = _now()
            operation = ManagementOperation(
                request_id=request_id,
                payload_hash=payload_hash,
                action="patch",
                device_name=name,
                profile_name=str(current.get("profileName") or ""),
                status="metadata_applied",
                actor=actor,
                started_at=started_at,
                updated_at=started_at,
            )
            try:
                await self.metadata.patch_device(name, update)
                readback = await self.metadata.get_device(name)
                if readback is None or any(readback.get(key) != value for key, value in update.items()):
                    raise ValueError("Device patch readback does not match requested fields")
                operation.metadata_applied = True
                await self._refresh_event_status(operation)
                self._remember(operation)
                self._audit_operation(operation, idempotency_key=idempotency_key)
                return operation
            except Exception as exc:
                operation.status = "failed"
                operation.error = f"{exc.__class__.__name__}: {exc}"
                operation.updated_at = _now()
                self._remember(operation)
                self._audit_operation(operation, idempotency_key=idempotency_key)
                raise ManagementApplyError(operation, exc) from exc

    async def get_operation(self, request_id: str) -> ManagementOperation:
        operation = self._operations.get(request_id)
        if operation is not None:
            self._operations.move_to_end(request_id)
            if operation.status == "waiting_for_event":
                await self._refresh_event_status(operation)
            return operation.model_copy(deep=True)

        for device in await self.metadata.list_devices():
            tags = device.get("tags") or {}
            if tags.get(DEVICE_REQUEST_ID_TAG) != request_id:
                continue
            payload_hash = tags.get(DEVICE_PAYLOAD_HASH_TAG)
            if not isinstance(payload_hash, str):
                break
            recovered = await self._operation_from_device(
                device,
                request_id=request_id,
                payload_hash=payload_hash,
                actor="recovered",
            )
            self._remember(recovered)
            return recovered.model_copy(deep=True)
        raise OperationNotFound(f"operation {request_id!r} was not found")

    def _profile_document(
        self, request: DeviceOnboardingRequest, template: ProfileTemplate
    ) -> dict[str, Any]:
        return {
            "apiVersion": "v2",
            "name": request.profile.name,
            "description": request.profile.description or "",
            "manufacturer": request.profile.manufacturer or "",
            "model": request.profile.model or "",
            "labels": list(request.profile.labels),
            "deviceResources": [
                item.model_dump(by_alias=True, exclude_none=True)
                for item in template.device_resources
            ],
            "deviceCommands": [
                item.model_dump(by_alias=True, exclude_none=True)
                for item in template.device_commands
            ],
        }

    @staticmethod
    def _profile_matches_template(
        profile: dict[str, Any], template: ProfileTemplate
    ) -> bool:
        resources = {
            item.get("name"): item for item in profile.get("deviceResources", [])
            if isinstance(item, dict)
        }
        for expected in template.device_resources:
            actual = resources.get(expected.name)
            if actual is None:
                return False
            properties = actual.get("properties") or {}
            if properties.get("valueType") != expected.properties.value_type:
                return False
            if properties.get("readWrite") != expected.properties.read_write:
                return False
        return True

    @staticmethod
    def _device_document(
        request: DeviceOnboardingRequest,
        adapter: Any,
        *,
        request_id: str | None,
        payload_hash: str | None,
        service_name: str | None = None,
        node_name: str | None = None,
    ) -> dict[str, Any]:
        tags = deepcopy(request.device.tags)
        for tag in ONBOARDING_OPERATION_TAGS:
            tags.pop(tag, None)
        effective_node_name = node_name or adapter.node_name
        if effective_node_name:
            tags["nodeName"] = effective_node_name
        physical_device_id = request.device.protocol_properties.get("DeviceID")
        if isinstance(physical_device_id, str) and physical_device_id:
            tags["physicalDeviceId"] = physical_device_id
        if request.hardware_binding_id:
            tags["hardwareBindingId"] = request.hardware_binding_id
        if request_id is not None and payload_hash is not None:
            tags[DEVICE_REQUEST_ID_TAG] = request_id
            tags[DEVICE_PAYLOAD_HASH_TAG] = payload_hash
        return {
            "name": request.device.name,
            "description": request.device.description,
            "adminState": request.device.admin_state,
            "operatingState": "UNKNOWN",
            "labels": list(request.device.labels),
            "serviceName": service_name or adapter.service_name,
            "profileName": request.profile.name,
            "protocols": {
                adapter.protocol_name: deepcopy(request.device.protocol_properties)
            },
            "tags": tags,
            "properties": {},
        }

    @staticmethod
    def _device_readback_matches(
        readback: dict[str, Any], requested: dict[str, Any]
    ) -> bool:
        return all(
            readback.get(field) == requested.get(field)
            for field in (
                "name",
                "serviceName",
                "profileName",
                "adminState",
                "protocols",
                "tags",
            )
        )

    async def _compensate_profile(self, name: str) -> None:
        try:
            users = await self.metadata.list_devices_by_profile(name)
            if not users:
                await self.metadata.delete_profile(name)
        except Exception:
            logging.getLogger(__name__).exception(
                "Profile compensation failed for %s", name
            )

    async def _protocol_binding_owner(
        self,
        adapter: Any,
        protocol_properties: dict[str, Any],
        *,
        exclude_name: str,
        service_name: str | None = None,
    ) -> str | None:
        expected = self._canonical_protocol_properties(adapter, protocol_properties)
        for device in await self.metadata.list_devices():
            name = device.get("name")
            if (
                name == exclude_name
                or device.get("serviceName") != (
                    service_name or adapter.service_name
                )
            ):
                continue
            protocols = device.get("protocols") or {}
            observed = protocols.get(adapter.protocol_name)
            if isinstance(observed, dict) and (
                self._canonical_protocol_properties(adapter, observed) == expected
            ):
                return str(name or "unknown")
        return None

    @staticmethod
    def _canonical_protocol_properties(
        adapter: Any, properties: dict[str, Any]
    ) -> dict[str, Any]:
        field_types = {field.name: field.type for field in adapter.fields}
        normalized: dict[str, Any] = {}
        for name, value in properties.items():
            if field_types.get(name) == "integer":
                try:
                    normalized[name] = int(value)
                except (TypeError, ValueError):
                    normalized[name] = value
            elif value is None:
                normalized[name] = None
            else:
                normalized[name] = str(value)
        return normalized

    async def _refresh_event_status(self, operation: ManagementOperation) -> None:
        try:
            points = await self.events.get_latest_event(operation.device_name)
        except EdgeXError as exc:
            operation.first_event_verified = False
            operation.status = "waiting_for_event"
            operation.error = (
                "first Event verification unavailable: "
                f"{exc.__class__.__name__}"
            )
            operation.updated_at = _now()
            return
        operation.first_event_verified = bool(points)
        operation.status = "verified" if points else "waiting_for_event"
        operation.error = None
        operation.updated_at = _now()

    async def _recover_matching_device(
        self,
        device: dict[str, Any],
        request: DeviceOnboardingRequest,
        request_id: str,
        payload_hash: str,
        *,
        actor: str,
        service_name_override: str | None = None,
        node_name_override: str | None = None,
    ) -> ManagementOperation | None:
        tags = device.get("tags") or {}
        if (
            tags.get(DEVICE_REQUEST_ID_TAG) != request_id
            or tags.get(DEVICE_PAYLOAD_HASH_TAG) != payload_hash
        ):
            return None
        adapter = self.catalog.require(request.adapter_id)
        requested = self._device_document(
            request,
            adapter,
            request_id=request_id,
            payload_hash=payload_hash,
            service_name=self._effective_service_name(
                adapter,
                service_name_override,
            ),
            node_name=self._effective_node_name(
                adapter,
                node_name_override,
            ),
        )
        if not self._device_readback_matches(device, requested):
            raise IdempotencyConflict(
                "Device has matching operation tags but its binding differs from the request"
            )
        return await self._operation_from_device(
            device,
            request_id=request_id,
            payload_hash=payload_hash,
            actor=actor,
        )

    async def _operation_from_device(
        self,
        device: dict[str, Any],
        *,
        request_id: str,
        payload_hash: str,
        actor: str,
    ) -> ManagementOperation:
        now = _now()
        operation = ManagementOperation(
            request_id=request_id,
            payload_hash=payload_hash,
            action="create",
            device_name=str(device.get("name") or ""),
            profile_name=str(device.get("profileName") or ""),
            status="metadata_applied",
            metadata_applied=True,
            actor=actor,
            started_at=now,
            updated_at=now,
        )
        await self._refresh_event_status(operation)
        return operation

    def _replay_or_conflict(
        self, request_id: str, payload_hash: str
    ) -> ManagementOperation | None:
        operation = self._operations.get(request_id)
        if operation is None:
            return None
        if operation.payload_hash != payload_hash:
            raise IdempotencyConflict(
                "the idempotency key was already used with a different payload"
            )
        self._operations.move_to_end(request_id)
        return operation.model_copy(deep=True)

    def _remember(self, operation: ManagementOperation) -> None:
        self._operations[operation.request_id] = operation.model_copy(deep=True)
        self._operations.move_to_end(operation.request_id)
        while len(self._operations) > self._operation_limit:
            self._operations.popitem(last=False)

    def _request_id(self, idempotency_key: str) -> str:
        return hmac.new(
            self._hmac_key, idempotency_key.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _effective_service_name(
        adapter: Any,
        service_name_override: str | None,
    ) -> str:
        service_name = service_name_override or adapter.service_name
        if not isinstance(service_name, str) or re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?",
            service_name,
        ) is None or len(service_name) > 63:
            raise ValueError("EdgeX Device Service name is invalid")
        return service_name

    @staticmethod
    def _effective_node_name(
        adapter: Any,
        node_name_override: str | None,
    ) -> str | None:
        node_name = node_name_override or adapter.node_name
        if node_name is None:
            return None
        if not isinstance(node_name, str) or len(node_name) > 253 or re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?",
            node_name,
        ) is None:
            raise ValueError("KubeEdge target node name is invalid")
        return node_name

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _audit_validation(
        self,
        request: DeviceOnboardingRequest,
        actor: str,
        result: ValidationResult,
    ) -> None:
        event = {
            "eventType": "device_management_audit",
            "requestId": None,
            "actor": actor,
            "action": "validate",
            "targetDevice": request.device.name,
            "targetProfile": request.profile.name,
            "status": "valid" if result.valid else "invalid",
            "issueCodes": [item.code for item in result.issues],
            "timestamp": _now().isoformat(),
        }
        audit_logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _audit_operation(
        operation: ManagementOperation, *, idempotency_key: str
    ) -> None:
        event = {
            "eventType": "device_management_audit",
            "requestId": operation.request_id,
            "idempotencyKeyHash": hashlib.sha256(
                idempotency_key.encode("utf-8")
            ).hexdigest(),
            "actor": operation.actor,
            "action": operation.action,
            "targetDevice": operation.device_name,
            "targetProfile": operation.profile_name,
            "status": operation.status,
            "metadataApplied": operation.metadata_applied,
            "firstEventVerified": operation.first_event_verified,
            "error": operation.error,
            "startedAt": operation.started_at.isoformat(),
            "finishedAt": operation.updated_at.isoformat(),
        }
        audit_logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))
