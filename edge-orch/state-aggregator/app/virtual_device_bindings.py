from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

MAX_EVENT_QUERY_PAGE_SIZE = 100
MAX_EVENT_QUERY_PAGES = 10
MAX_EVENTS_PER_DEVICE = 1000
MAX_PRIOR_PROBE_EVENTS_PER_DEVICE = 200


class BindingConfigError(ValueError):
    """Raised when a virtual-device binding document is unusable."""


class BindingModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
        str_strip_whitespace=True,
    )


class EventQuery(BindingModel):
    page_size: int = Field(default=MAX_EVENT_QUERY_PAGE_SIZE, ge=1, le=MAX_EVENT_QUERY_PAGE_SIZE)
    max_pages: int = Field(default=MAX_EVENT_QUERY_PAGES, ge=1, le=MAX_EVENT_QUERY_PAGES)
    max_events_per_device: int = Field(
        default=MAX_EVENTS_PER_DEVICE,
        ge=1,
        le=MAX_EVENTS_PER_DEVICE,
    )
    max_prior_probe_events_per_device: int = Field(
        default=MAX_PRIOR_PROBE_EVENTS_PER_DEVICE,
        ge=1,
        le=MAX_PRIOR_PROBE_EVENTS_PER_DEVICE,
    )


class PhysicalDeviceRef(BindingModel):
    name: str = Field(min_length=1)
    expected_profile_name: str = Field(min_length=1)


class SourceResourceBinding(BindingModel):
    source_name: str = Field(min_length=1)
    resource_name: str = Field(min_length=1)


class CapabilityInput(BindingModel):
    input_id: str = Field(min_length=1)
    capability_field: str = Field(min_length=1)
    required: bool
    bindings: list[SourceResourceBinding] = Field(min_length=1)
    accepted_value_types: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    accepted_units: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_bindings(self) -> CapabilityInput:
        pairs = [(binding.source_name, binding.resource_name) for binding in self.bindings]
        if len(pairs) != len(set(pairs)):
            raise ValueError("bindings must have unique sourceName/resourceName pairs")
        return self


class Capability(BindingModel):
    id: str = Field(min_length=1)
    freshness_seconds: int = Field(gt=0)
    inputs: list[CapabilityInput] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_capability_fields(self) -> Capability:
        fields = [input_.capability_field for input_ in self.inputs]
        if len(fields) != len(set(fields)):
            raise ValueError("capabilityField must be unique within a capability")
        required_pairs = [
            (binding.source_name, binding.resource_name)
            for input_ in self.inputs
            if input_.required
            for binding in input_.bindings
        ]
        if len(required_pairs) != len(set(required_pairs)):
            raise ValueError(
                "one physical binding cannot satisfy two required inputs in a capability"
            )
        return self


class InputFieldMap(BindingModel):
    input_id: str = Field(min_length=1)
    ai_field: str = Field(min_length=1)


class WorkloadRef(BindingModel):
    namespace: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    name: str = Field(min_length=1)


class AiServiceRef(BindingModel):
    service_id: str = Field(min_length=1)
    input_contract: str = Field(min_length=1)
    binding_mode: Literal["declarative_read_only"]
    input_field_map: list[InputFieldMap]
    workload_ref: WorkloadRef | None = None


class VirtualDeviceInstance(BindingModel):
    id: str = Field(min_length=1)
    physical_device_ref: PhysicalDeviceRef
    capabilities: list[Capability] = Field(min_length=1)
    ai_service_ref: AiServiceRef

    @model_validator(mode="after")
    def require_consistent_inputs_and_ai_map(self) -> VirtualDeviceInstance:
        capability_ids = [capability.id for capability in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("capability IDs must be unique per instance")

        input_ids = [
            input_.input_id
            for capability in self.capabilities
            for input_ in capability.inputs
        ]
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("inputId must be stable and unique across an instance")

        map_ids = [mapping.input_id for mapping in self.ai_service_ref.input_field_map]
        ai_fields = [mapping.ai_field for mapping in self.ai_service_ref.input_field_map]
        if len(map_ids) != len(set(map_ids)):
            raise ValueError("inputFieldMap inputId entries must be unique")
        if len(ai_fields) != len(set(ai_fields)):
            raise ValueError("aiField must be unique in the AI contract")
        unknown_ids = set(map_ids) - set(input_ids)
        if unknown_ids:
            raise ValueError("inputFieldMap contains an unknown inputId")
        required_ids = {
            input_.input_id
            for capability in self.capabilities
            for input_ in capability.inputs
            if input_.required
        }
        mapped_ids = set(map_ids)
        if required_ids - mapped_ids:
            raise ValueError("every required inputId must appear in inputFieldMap")
        return self


class VirtualDeviceBindingConfig(BindingModel):
    api_version: Literal["virtual-device-binding/v1"]
    event_query: EventQuery = Field(default_factory=EventQuery)
    instances: list[VirtualDeviceInstance] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_instance_ids(self) -> VirtualDeviceBindingConfig:
        instance_ids = [instance.id for instance in self.instances]
        if len(instance_ids) != len(set(instance_ids)):
            raise ValueError("instance IDs must be unique")
        return self


def canonical_binding_bytes(validated: VirtualDeviceBindingConfig) -> bytes:
    """Return the sole normalized representation used for binding revisions."""
    payload = validated.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def config_revision(validated: VirtualDeviceBindingConfig) -> str:
    return hashlib.sha256(canonical_binding_bytes(validated)).hexdigest()


def load_virtual_device_bindings(
    path: Path,
    *,
    allow_empty_for_tests: bool = False,
) -> VirtualDeviceBindingConfig:
    """Load and validate one local binding document without retaining its raw bytes."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingConfigError(f"unable to load virtual-device bindings: {path}") from exc
    try:
        validated = VirtualDeviceBindingConfig.model_validate(document)
    except Exception as exc:
        raise BindingConfigError("invalid virtual-device binding document") from exc
    if not validated.instances and not allow_empty_for_tests:
        raise BindingConfigError("virtual-device binding document must not be empty")
    return validated


def revision_diagnostic(path: Path, *, allow_empty_for_tests: bool = False) -> str:
    return config_revision(
        load_virtual_device_bindings(path, allow_empty_for_tests=allow_empty_for_tests)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a virtual-device binding revision")
    parser.add_argument("revision", nargs="?")
    parser.add_argument("--path", required=True, type=Path)
    args = parser.parse_args()
    if args.revision not in (None, "revision"):
        parser.error("the only supported command is 'revision'")
    print(revision_diagnostic(args.path))


if __name__ == "__main__":
    main()
