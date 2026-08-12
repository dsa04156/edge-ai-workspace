from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .discovery_models import DiscoveryProtocol, StoredCandidate
from .models import ControllerModel


IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"^[A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}$"
)


class DeviceMatchRule(ControllerModel):
    node_id: str | None = Field(default=None, max_length=253)
    vendor_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{4}$",
    )
    product_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{4}$",
    )
    hardware_id: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, max_length=255)
    endpoint: str | None = Field(default=None, max_length=1024)
    required_capabilities: list[str] = Field(default_factory=list, max_length=128)
    properties: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        max_length=32,
    )

    @model_validator(mode="after")
    def require_stable_match_field(self) -> "DeviceMatchRule":
        if not any(
            (
                self.vendor_id,
                self.product_id,
                self.hardware_id,
                self.model,
                self.endpoint,
                self.required_capabilities,
                self.properties,
            )
        ):
            raise ValueError("device binding requires a stable match field")
        if len(self.required_capabilities) != len(
            set(self.required_capabilities)
        ):
            raise ValueError("required capabilities must be unique")
        if any(not key or len(key) > 128 for key in self.properties):
            raise ValueError("match property names are invalid")
        return self


class DeviceAdapterReference(ControllerModel):
    runtime_adapter_id: str = Field(min_length=1, max_length=128)
    service_name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    image: str
    parser: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_immutable_image(self) -> "DeviceAdapterReference":
        if IMMUTABLE_IMAGE_PATTERN.fullmatch(self.image) is None:
            raise ValueError("Device Service image must use an immutable digest")
        return self


class DeviceProfileReference(ControllerModel):
    name: str = Field(min_length=1, max_length=255)
    file: str = Field(
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9._/-]+\.json$",
    )

    @model_validator(mode="after")
    def prevent_path_traversal(self) -> "DeviceProfileReference":
        path = Path(self.file)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("profile path must remain inside the catalog directory")
        return self


class DeviceSecurityPolicy(ControllerModel):
    approval_required: bool = True


class DeviceAutoEvent(ControllerModel):
    source_name: str = Field(min_length=1, max_length=255)
    interval: str = Field(
        min_length=2,
        max_length=32,
        pattern=r"^[1-9][0-9]*(?:ms|s|m|h)$",
    )
    on_change: bool = False


class DeviceBinding(ControllerModel):
    binding_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    protocol: DiscoveryProtocol
    match: DeviceMatchRule
    runtime_hardware_binding_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$",
    )
    connection: dict[str, str | int | float | bool] = Field(
        default_factory=dict
    )
    connection_property_map: dict[str, str] = Field(
        default_factory=dict,
        max_length=32,
    )
    edge_x_protocol: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )
    auto_events: list[DeviceAutoEvent] = Field(default_factory=list, max_length=64)
    adapter: DeviceAdapterReference
    profile: DeviceProfileReference
    security: DeviceSecurityPolicy = Field(
        default_factory=DeviceSecurityPolicy
    )
    registration_mode: Literal["create-or-reuse", "reuse-existing"] = (
        "create-or-reuse"
    )
    existing_device_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    existing_device_tags: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        max_length=32,
    )
    device_name_prefix: str = Field(
        default="physical",
        min_length=1,
        max_length=40,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    )

    @model_validator(mode="after")
    def validate_protocol_mapping(self) -> "DeviceBinding":
        if any(
            not target
            or not source
            or len(target) > 128
            or len(source) > 128
            for target, source in self.connection_property_map.items()
        ):
            raise ValueError("connectionPropertyMap contains an invalid field")
        if self.protocol == "modbus" and self.edge_x_protocol not in {
            "modbus-tcp",
            "modbus-rtu",
        }:
            raise ValueError(
                "Modbus binding requires edgeXProtocol modbus-tcp or modbus-rtu"
            )
        source_names = [item.source_name for item in self.auto_events]
        if len(source_names) != len(set(source_names)):
            raise ValueError("autoEvent source names must be unique")
        if self.registration_mode == "reuse-existing":
            if not self.existing_device_name:
                raise ValueError(
                    "reuse-existing binding requires existingDeviceName"
                )
            if not self.existing_device_tags:
                raise ValueError(
                    "reuse-existing binding requires expected Device tags"
                )
        elif self.existing_device_name or self.existing_device_tags:
            raise ValueError(
                "existing Device fields require registrationMode=reuse-existing"
            )
        return self


class DeviceCatalogDocument(ControllerModel):
    version: int = Field(default=1, ge=1)
    image_allowlist: list[str] = Field(default_factory=list)
    parser_allowlist: list[str] = Field(default_factory=list)
    profile_allowlist: list[str] = Field(default_factory=list)
    bindings: list[dict[str, Any]] = Field(default_factory=list)


class CatalogMatch(ControllerModel):
    confidence: Literal["none", "partial", "exact", "ambiguous"]
    binding: DeviceBinding | None = None
    binding_ids: list[str] = Field(default_factory=list)
    reason: str


class DeviceBindingCatalog:
    def __init__(
        self,
        *,
        version: int,
        base_path: Path,
        bindings: list[DeviceBinding],
        errors: list[str],
        image_allowlist: set[str],
        parser_allowlist: set[str],
        profile_allowlist: set[str],
    ) -> None:
        self.version = version
        self.base_path = base_path
        self.bindings = bindings
        self.errors = errors
        self.image_allowlist = image_allowlist
        self.parser_allowlist = parser_allowlist
        self.profile_allowlist = profile_allowlist
        ids = [item.binding_id for item in bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("Device Catalog binding IDs must be unique")

    @classmethod
    def load(cls, path: Path) -> "DeviceBindingCatalog":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            document = DeviceCatalogDocument.model_validate(raw)
        except Exception as exc:
            return cls(
                version=1,
                base_path=path.parent,
                bindings=[],
                errors=[f"catalog_document_invalid:{exc.__class__.__name__}"],
                image_allowlist=set(),
                parser_allowlist=set(),
                profile_allowlist=set(),
            )
        images = set(document.image_allowlist)
        parsers = set(document.parser_allowlist)
        profiles = set(document.profile_allowlist)
        bindings: list[DeviceBinding] = []
        errors: list[str] = []
        for index, payload in enumerate(document.bindings):
            try:
                binding = DeviceBinding.model_validate(payload)
                cls._validate_allowlists(
                    binding,
                    images=images,
                    parsers=parsers,
                    profiles=profiles,
                    base_path=path.parent,
                )
                bindings.append(binding)
            except Exception as exc:
                binding_id = str(payload.get("bindingId") or f"index-{index}")
                errors.append(
                    f"{binding_id}:catalog_binding_invalid:"
                    f"{exc.__class__.__name__}:{exc}"
                )
        return cls(
            version=document.version,
            base_path=path.parent,
            bindings=bindings,
            errors=errors,
            image_allowlist=images,
            parser_allowlist=parsers,
            profile_allowlist=profiles,
        )

    def match(self, candidate: StoredCandidate) -> CatalogMatch:
        protocol_bindings = [
            item for item in self.bindings if item.protocol == candidate.protocol
        ]
        manifest_evidence = candidate.evidence.get("manifest")
        if (
            protocol_bindings
            and manifest_evidence is not None
            and manifest_evidence != "validated-json"
        ):
            return CatalogMatch(
                confidence="partial",
                binding_ids=[
                    item.binding_id for item in protocol_bindings
                ],
                reason=(
                    "active device Manifest verification did not succeed: "
                    f"{manifest_evidence}"
                ),
            )
        exact = [
            item
            for item in protocol_bindings
            if self._matches(item, candidate)
        ]
        if len(exact) > 1:
            return CatalogMatch(
                confidence="ambiguous",
                binding_ids=sorted(item.binding_id for item in exact),
                reason="multiple exact Device Catalog bindings matched",
            )
        if len(exact) == 1:
            return CatalogMatch(
                confidence="exact",
                binding=exact[0],
                binding_ids=[exact[0].binding_id],
                reason="stable identity exactly matched a verified binding",
            )
        if protocol_bindings:
            return CatalogMatch(
                confidence="partial",
                binding_ids=[item.binding_id for item in protocol_bindings],
                reason="protocol is known but stable identity/profile did not match",
            )
        return CatalogMatch(
            confidence="none",
            reason="no verified Device Catalog binding supports this protocol",
        )

    def get(self, binding_id: str) -> DeviceBinding:
        for item in self.bindings:
            if item.binding_id == binding_id:
                return item
        raise ValueError(f"unknown Device Catalog binding {binding_id!r}")

    def profile_document(self, binding: DeviceBinding) -> dict[str, Any]:
        path = (self.base_path / binding.profile.file).resolve()
        base = self.base_path.resolve()
        if base != path.parent and base not in path.parents:
            raise ValueError("profile path escaped the Device Catalog directory")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("name") != binding.profile.name:
            raise ValueError("profile file does not match its Catalog profile name")
        return payload

    @staticmethod
    def _matches(binding: DeviceBinding, candidate: StoredCandidate) -> bool:
        rule = binding.match
        properties = candidate.properties
        if (
            candidate.recommended_profile is not None
            and candidate.recommended_profile != binding.profile.name
        ):
            return False
        if rule.node_id is not None and rule.node_id != candidate.node_name:
            return False
        if rule.vendor_id is not None and str(
            properties.get("VendorID") or ""
        ).casefold() != rule.vendor_id.casefold():
            return False
        if rule.product_id is not None and str(
            properties.get("ProductID") or ""
        ).casefold() != rule.product_id.casefold():
            return False
        if rule.hardware_id is not None and (
            candidate.hardware_id != rule.hardware_id
        ):
            return False
        if rule.model is not None and candidate.model != rule.model:
            return False
        if rule.endpoint is not None and candidate.device_path != rule.endpoint:
            return False
        if any(
            candidate.properties.get(name) != value
            for name, value in rule.properties.items()
        ):
            return False
        if not set(rule.required_capabilities).issubset(
            set(candidate.capabilities)
        ):
            return False
        return True

    @staticmethod
    def _validate_allowlists(
        binding: DeviceBinding,
        *,
        images: set[str],
        parsers: set[str],
        profiles: set[str],
        base_path: Path,
    ) -> None:
        if binding.adapter.image not in images:
            raise ValueError("Device Service image is not allowlisted")
        if binding.adapter.parser not in parsers:
            raise ValueError("Device parser is not allowlisted")
        if binding.profile.name not in profiles:
            raise ValueError("Device Profile is not allowlisted")
        profile_path = base_path / binding.profile.file
        if not profile_path.is_file():
            raise ValueError("Device Profile file does not exist")
