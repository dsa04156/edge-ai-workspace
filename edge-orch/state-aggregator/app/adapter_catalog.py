from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .device_management_models import (
    AdapterCatalogDocument,
    AdapterDefinition,
    ProfileTemplate,
    ValidationIssue,
    matches_pattern,
)

_SECRET_FIELD_NAME = re.compile(
    r"(?:password|passwd|token|secret|credential|privatekey)",
    re.IGNORECASE,
)


class AdapterCatalog:
    def __init__(self, document: AdapterCatalogDocument) -> None:
        self.version = document.version
        self.adapters = document.adapters
        self._by_id = {item.adapter_id: item for item in self.adapters}
        if len(self._by_id) != len(self.adapters):
            raise ValueError("adapterId values must be unique")
        binding_ids = [
            binding.binding_id
            for adapter in self.adapters
            for binding in adapter.runtime.hardware_bindings
        ]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("hardware binding IDs must be unique across adapters")
        template_ids = [
            adapter.runtime.template_id
            for adapter in self.adapters
            if adapter.runtime.template_id is not None
        ]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("runtime template IDs must be unique across adapters")

    @classmethod
    def load(cls, path: Path) -> "AdapterCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(AdapterCatalogDocument.model_validate(payload))

    def require(self, adapter_id: str) -> AdapterDefinition:
        try:
            return self._by_id[adapter_id]
        except KeyError as exc:
            raise ValueError(f"unknown adapter {adapter_id!r}") from exc

    def validate_protocol(
        self, adapter_id: str, properties: dict[str, Any]
    ) -> list[ValidationIssue]:
        try:
            adapter = self.require(adapter_id)
        except ValueError:
            return [
                ValidationIssue(
                    code="unknown_adapter",
                    field="adapterId",
                    message=f"adapter {adapter_id!r} is not in the catalog",
                )
            ]
        if adapter.declared_status != "installed":
            return [
                ValidationIssue(
                    code="unsupported_adapter",
                    field="adapterId",
                    message=adapter.reason or f"adapter {adapter_id!r} is unsupported",
                )
            ]

        fields = {
            field.name: field
            for field in adapter.fields
            if field.scope == "device"
        }
        issues = self._validate_fields(fields, properties, prefix="protocol")
        issues.extend(
            self._validate_hardware_binding_fields(adapter, properties)
        )
        return issues

    def validate_runtime_settings(
        self,
        adapter_id: str,
        settings: dict[str, Any],
    ) -> list[ValidationIssue]:
        try:
            adapter = self.require(adapter_id)
        except ValueError:
            return [
                ValidationIssue(
                    code="unknown_adapter",
                    field="adapterId",
                    message=f"adapter {adapter_id!r} is not in the catalog",
                )
            ]
        if adapter.declared_status != "installed":
            return [
                ValidationIssue(
                    code="unsupported_adapter",
                    field="adapterId",
                    message=adapter.reason or f"adapter {adapter_id!r} is unsupported",
                )
            ]
        fields = {
            field.name: field
            for field in adapter.fields
            if field.scope == "runtime"
        }
        return self._validate_fields(fields, settings, prefix="runtime")

    @staticmethod
    def _validate_fields(
        fields: dict[str, Any],
        properties: dict[str, Any],
        *,
        prefix: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for name in sorted(set(properties) - set(fields)):
            issues.append(
                ValidationIssue(
                    code=f"unknown_{prefix}_field",
                    field=name,
                    message=f"{prefix} field {name!r} is not allowed",
                )
            )
        for name, field in fields.items():
            if name not in properties:
                if field.required:
                    issues.append(
                        ValidationIssue(
                            code="required_field",
                            field=name,
                            message=f"{prefix} field {name!r} is required",
                        )
                    )
                continue
            value = properties[name]
            if isinstance(value, str) and not value.strip():
                issues.append(
                    ValidationIssue(
                        code="empty_value",
                        field=name,
                        message=f"{prefix} field {name!r} must not be empty",
                    )
                )
                continue
            if field.type == "integer" and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                issues.append(
                    ValidationIssue(
                        code="invalid_type",
                        field=name,
                        message=f"{prefix} field {name!r} must be an integer",
                    )
                )
                continue
            if field.type == "string" and not isinstance(value, str):
                issues.append(
                    ValidationIssue(
                        code="invalid_type",
                        field=name,
                        message=f"{prefix} field {name!r} must be a string",
                    )
                )
                continue
            if field.type == "enum" and (
                value is None or isinstance(value, (dict, list))
            ):
                issues.append(
                    ValidationIssue(
                        code="invalid_type",
                        field=name,
                        message=f"{prefix} field {name!r} must be a scalar value",
                    )
                )
                continue
            if field.const is not None and value != field.const:
                issues.append(
                    ValidationIssue(
                        code="constant_mismatch",
                        field=name,
                        message=f"{prefix} field {name!r} must equal the installed endpoint value",
                    )
                )
            if field.options and value not in field.options:
                issues.append(
                    ValidationIssue(
                        code="invalid_option",
                        field=name,
                        message=f"{prefix} field {name!r} is not a supported option",
                    )
                )
            if isinstance(value, str) and not matches_pattern(field.pattern, value):
                issues.append(
                    ValidationIssue(
                        code="pattern_mismatch",
                        field=name,
                        message=f"{prefix} field {name!r} has an invalid format",
                    )
                )
        return issues

    def _validate_hardware_binding_fields(
        self,
        adapter: Any,
        properties: dict[str, Any],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        binding_fields = adapter.runtime.reuse_policy.binding_fields
        bindings = adapter.runtime.hardware_bindings
        if binding_fields and bindings and not any(
            all(
                properties.get(name) == binding.protocol_properties.get(name)
                for name in binding_fields
            )
            for binding in bindings
        ):
            issues.append(
                ValidationIssue(
                    code="hardware_binding_mismatch",
                    field="device.protocolProperties",
                    message=(
                        "protocol binding fields do not match an approved hardware "
                        "connection"
                    ),
                )
            )
        return issues

    def validate_hardware_binding(
        self,
        adapter_id: str,
        binding_id: str,
        properties: dict[str, Any],
    ) -> list[ValidationIssue]:
        try:
            adapter = self.require(adapter_id)
        except ValueError:
            return [
                ValidationIssue(
                    code="unknown_adapter",
                    field="adapterId",
                    message=f"adapter {adapter_id!r} is not in the catalog",
                )
            ]
        binding = next(
            (
                item
                for item in adapter.runtime.hardware_bindings
                if item.binding_id == binding_id
            ),
            None,
        )
        if binding is None:
            return [
                ValidationIssue(
                    code="hardware_binding_not_allowed",
                    field="hardwareBindingId",
                    message=f"hardware binding {binding_id!r} is not approved",
                )
            ]
        mismatches = [
            name
            for name, value in binding.protocol_properties.items()
            if properties.get(name) != value
        ]
        if not mismatches:
            return []
        return [
            ValidationIssue(
                code="hardware_binding_mismatch",
                field="device.protocolProperties",
                message=(
                    f"protocol fields {', '.join(mismatches)} do not match "
                    f"hardware binding {binding_id!r}"
                ),
            )
        ]

    def profile_template(
        self, adapter_id: str, properties: dict[str, Any]
    ) -> ProfileTemplate:
        issues = self.validate_protocol(adapter_id, properties)
        if issues:
            prefix = "unsupported: " if issues[0].code == "unsupported_adapter" else ""
            raise ValueError(prefix + "; ".join(item.message for item in issues))
        adapter = self.require(adapter_id)
        capabilities = adapter.profile_capabilities
        if capabilities is None:
            raise ValueError(f"adapter {adapter_id!r} is unsupported for profile creation")
        selector = properties.get(capabilities.selector_field)
        for template in capabilities.templates:
            if template.selector_value == selector:
                return template.model_copy(deep=True)
        raise ValueError(
            f"adapter {adapter_id!r} has no profile template for {selector!r}"
        )

    def redact_protocol(
        self, adapter_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        adapter = self.require(adapter_id)
        secret_fields = {field.name for field in adapter.fields if field.secret}
        return {
            name: (
                "***"
                if name in secret_fields or _SECRET_FIELD_NAME.search(name)
                else value
            )
            for name, value in properties.items()
        }
