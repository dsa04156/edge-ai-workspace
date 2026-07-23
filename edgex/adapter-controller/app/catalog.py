from __future__ import annotations

import json
from pathlib import Path

from .models import RuntimeCatalogDocument, RuntimeTemplate


class RuntimeTemplateCatalog:
    def __init__(self, document: RuntimeCatalogDocument) -> None:
        self.version = document.version
        self.namespace = document.namespace
        self.templates = document.templates
        self._by_template_id = {
            item.template_id: item for item in self.templates
        }
        if len(self._by_template_id) != len(self.templates):
            raise ValueError("runtime template IDs must be unique")
        self._by_adapter_id = {item.adapter_id: item for item in self.templates}
        if len(self._by_adapter_id) != len(self.templates):
            raise ValueError("adapter IDs must be unique in the runtime catalog")
        binding_ids = [
            binding.binding_id
            for template in self.templates
            for binding in template.hardware_bindings
        ]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("hardware binding IDs must be unique across templates")

    @classmethod
    def load(cls, path: Path) -> "RuntimeTemplateCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(RuntimeCatalogDocument.model_validate(payload))

    def require(self, template_id: str) -> RuntimeTemplate:
        try:
            return self._by_template_id[template_id]
        except KeyError as exc:
            raise ValueError(f"unknown runtime template {template_id!r}") from exc

    def require_adapter(self, adapter_id: str) -> RuntimeTemplate:
        try:
            return self._by_adapter_id[adapter_id]
        except KeyError as exc:
            raise ValueError(f"unknown adapter {adapter_id!r}") from exc
