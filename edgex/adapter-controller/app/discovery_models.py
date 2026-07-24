from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .models import ControllerModel


DiscoveryProtocol = Literal[
    "serial",
    "i2c",
    "mqtt",
    "modbus",
    "opcua",
    "rtsp",
    "rest",
]
CandidateDecision = Literal["pending", "accepted", "ignored"]
CandidatePresence = Literal["present", "stale", "declared"]
CandidateSource = Literal["node-scan", "manual"]
CandidatePackageState = Literal[
    "registration-ready",
    "binding-required",
    "verification-required",
    "unsupported",
]
PropertyValue = str | int | float | bool


def _timezone_required(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class CandidateMutationRef(ControllerModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DiscoveryObservation(ControllerModel):
    hardware_key: str = Field(min_length=1, max_length=1024)
    protocol: DiscoveryProtocol
    transport: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/,:@+~-]+$",
    )
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bound_untrusted_maps(self) -> "DiscoveryObservation":
        if len(self.properties) > 32 or len(self.evidence) > 32:
            raise ValueError("candidate properties and evidence are limited to 32 entries")
        if any(len(str(key)) > 128 for key in self.properties):
            raise ValueError("candidate property names are too long")
        if any(len(str(key)) > 128 or len(value) > 1024 for key, value in self.evidence.items()):
            raise ValueError("candidate evidence is too large")
        return self


class NodeDiscoveryReport(ControllerModel):
    node_name: str = Field(min_length=1, max_length=253)
    agent_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    candidates: list[DiscoveryObservation] = Field(max_length=512)
    scan_errors: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _timezone_required(value)

    @field_validator("scan_errors")
    @classmethod
    def bound_scan_errors(cls, values: list[str]) -> list[str]:
        if any(len(value) > 1024 for value in values):
            raise ValueError("scan error is too long")
        return values


class ManualCandidateInput(ControllerModel):
    node_name: str = Field(min_length=1, max_length=253)
    protocol: DiscoveryProtocol
    transport: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/,:@+~-]+$",
    )
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def bound_properties(self) -> "ManualCandidateInput":
        if len(self.properties) > 32:
            raise ValueError("candidate properties are limited to 32 entries")
        return self


class ManualCandidateCreate(ControllerModel):
    candidate: ManualCandidateInput
    request_ref: CandidateMutationRef


class CandidateDecisionUpdate(ControllerModel):
    decision: CandidateDecision
    note: str = Field(default="", max_length=1000)
    request_ref: CandidateMutationRef


class CandidateDeleteRequest(ControllerModel):
    request_ref: CandidateMutationRef


class CandidateActionRef(ControllerModel):
    action: Literal["create", "decision", "delete"]
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class StoredCandidate(ControllerModel):
    candidate_id: str = Field(pattern=r"^candidate-[0-9a-f]{24}$")
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: CandidateSource
    node_name: str
    protocol: DiscoveryProtocol
    transport: str
    display_name: str
    device_path: str | None = None
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    decision: CandidateDecision = "pending"
    decision_note: str = ""
    discovered_by: str | None = None
    first_seen: datetime
    last_seen: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    last_action_ref: CandidateActionRef | None = None

    @field_validator("first_seen", "last_seen", "updated_at", "deleted_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _timezone_required(value)


class CandidateView(ControllerModel):
    candidate_id: str
    source: CandidateSource
    node_name: str
    protocol: DiscoveryProtocol
    transport: str
    display_name: str
    device_path: str | None = None
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    decision: CandidateDecision
    decision_note: str = ""
    presence: CandidatePresence
    first_seen: datetime
    last_seen: datetime
    updated_at: datetime
    matched_adapter_id: str | None = None
    matched_hardware_binding_id: str | None = None
    package_state: CandidatePackageState
    package_reason: str
    registration_ready: bool = False


class DiscoveryNodeView(ControllerModel):
    node_name: str
    agent_id: str
    last_report_at: datetime
    presence: Literal["online", "stale"]
    candidate_count: int = Field(ge=0)
    scan_errors: list[str] = Field(default_factory=list)

    @field_validator("last_report_at")
    @classmethod
    def validate_last_report_at(cls, value: datetime) -> datetime:
        return _timezone_required(value)


class DiscoveryInventory(ControllerModel):
    generated_at: datetime
    stale_after_seconds: int = Field(ge=10, le=3600)
    nodes: list[DiscoveryNodeView]
    candidates: list[CandidateView]


class StoredDiscoveryNode(ControllerModel):
    node_name: str
    agent_id: str
    last_report_at: datetime
    candidate_count: int = Field(ge=0)
    scan_errors: list[str] = Field(default_factory=list)


class CandidateRegistryDocument(ControllerModel):
    version: Literal[1] = 1
    nodes: list[StoredDiscoveryNode] = Field(default_factory=list)
    candidates: list[StoredCandidate] = Field(default_factory=list)


def model_payload(model: ControllerModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)
