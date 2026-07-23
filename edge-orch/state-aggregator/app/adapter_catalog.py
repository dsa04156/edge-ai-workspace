from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .device_management_models import (
    AdapterCatalogDocument,
    AdapterDefinition,
    ProfileTemplate,
    ValidationIssue,
    matches_pattern,
)


class AdapterCatalog:
    def __init__(self, document: AdapterCatalogDocument) -> None:
        self.version = document.version
        self.adapters = document.adapters
        self._by_id = {item.adapter_id: item for item in self.adapters}
        if len(self._by_id) != len(self.adapters):
            raise ValueError("adapterId values must be unique")

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

        fields = {field.name: field for field in adapter.fields}
        issues: list[ValidationIssue] = []
        for name in sorted(set(properties) - set(fields)):
            issues.append(
                ValidationIssue(
                    code="unknown_protocol_field",
                    field=name,
                    message=f"protocol field {name!r} is not allowed",
                )
            )
        for name, field in fields.items():
            if name not in properties:
                if field.required:
                    issues.append(
                        ValidationIssue(
                            code="required_field",
                            field=name,
                            message=f"protocol field {name!r} is required",
                        )
                    )
                continue
            value = properties[name]
            if isinstance(value, str) and not value.strip():
                issues.append(
                    ValidationIssue(
                        code="empty_value",
                        field=name,
                        message=f"protocol field {name!r} must not be empty",
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
                        message=f"protocol field {name!r} must be an integer",
                    )
                )
                continue
            if field.type in {"string", "enum"} and not isinstance(value, str):
                issues.append(
                    ValidationIssue(
                        code="invalid_type",
                        field=name,
                        message=f"protocol field {name!r} must be a string",
                    )
                )
                continue
            if field.const is not None and value != field.const:
                issues.append(
                    ValidationIssue(
                        code="constant_mismatch",
                        field=name,
                        message=f"protocol field {name!r} must equal the installed endpoint value",
                    )
                )
            if field.options and value not in field.options:
                issues.append(
                    ValidationIssue(
                        code="invalid_option",
                        field=name,
                        message=f"protocol field {name!r} is not a supported option",
                    )
                )
            if isinstance(value, str) and not matches_pattern(field.pattern, value):
                issues.append(
                    ValidationIssue(
                        code="pattern_mismatch",
                        field=name,
                        message=f"protocol field {name!r} has an invalid format",
                    )
                )
        return issues

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
            name: "***" if name in secret_fields else value
            for name, value in properties.items()
        }
