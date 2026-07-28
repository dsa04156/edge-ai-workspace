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
    "onvif",
    "rtsp",
    "rest",
]
CandidateDecision = Literal["pending", "accepted", "ignored"]
CandidatePresence = Literal["present", "stale", "declared"]
CandidateSource = Literal["node-scan", "manual"]
DiscoveryState = Literal[
    "DETECTED",
    "IDENTIFIED",
    "PENDING_APPROVAL",
    "APPROVED",
    "SERVICE_READY",
    "METADATA_REGISTERED",
    "EVENT_CONFIRMED",
    "BLOCKED",
    "REJECTED",
    "STALE",
    "FAILED",
]
AuthState = Literal[
    "not_checked",
    "approved",
    "denied",
    "unavailable",
    "error",
]
MatchConfidence = Literal["none", "partial", "exact", "ambiguous"]
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
    hardware_id: str | None = Field(default=None, min_length=1, max_length=1024)
    protocol: DiscoveryProtocol
    transport: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/,:@+~-]+$",
    )
    vendor: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    firmware_version: str | None = Field(default=None, max_length=255)
    capabilities: list[str] = Field(default_factory=list, max_length=128)
    recommended_profile: str | None = Field(default=None, max_length=255)
    match_confidence: MatchConfidence = "none"
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
        if any(not item or len(item) > 128 for item in self.capabilities):
            raise ValueError("candidate capabilities contain an invalid value")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("candidate capabilities must be unique")
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
    hardware_id: str | None = Field(default=None, min_length=1, max_length=1024)
    vendor: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    capabilities: list[str] = Field(default_factory=list, max_length=128)
    recommended_profile: str | None = Field(default=None, max_length=255)
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


class CandidateDecommissionRequest(ControllerModel):
    actor: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)
    request_ref: CandidateMutationRef


class CandidateActionRef(ControllerModel):
    action: Literal["create", "decision", "delete", "decommission"]
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateTransition(ControllerModel):
    from_state: DiscoveryState | None = None
    to_state: DiscoveryState
    reason: str = Field(min_length=1, max_length=1000)
    actor: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    error_code: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Z0-9_]+$",
    )

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _timezone_required(value)


class StoredCandidate(ControllerModel):
    candidate_id: str = Field(pattern=r"^candidate-[0-9a-f]{24}(?:[0-9a-f]{40})?$")
    identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: CandidateSource
    node_name: str
    protocol: DiscoveryProtocol
    transport: str
    display_name: str
    device_path: str | None = None
    hardware_id: str = Field(default="", max_length=1024)
    vendor: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    recommended_profile: str | None = None
    match_confidence: MatchConfidence = "none"
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    decision: CandidateDecision = "pending"
    decision_note: str = ""
    state: DiscoveryState = "DETECTED"
    resume_state: DiscoveryState | None = None
    auth_state: AuthState = "not_checked"
    failure_reason: str | None = None
    retry_count: int = Field(default=0, ge=0)
    registration_step: str | None = Field(default=None, max_length=128)
    matched_binding_id: str | None = None
    transitions: list[CandidateTransition] = Field(default_factory=list)
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
    hardware_id: str = ""
    vendor: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    recommended_profile: str | None = None
    match_confidence: MatchConfidence = "none"
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    decision: CandidateDecision
    decision_note: str = ""
    state: DiscoveryState = "DETECTED"
    auth_state: AuthState = "not_checked"
    failure_reason: str | None = None
    retry_count: int = 0
    registration_step: str | None = None
    transition_count: int = 0
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
    version: Literal[1, 2] = 2
    nodes: list[StoredDiscoveryNode] = Field(default_factory=list)
    candidates: list[StoredCandidate] = Field(default_factory=list)


class SerialDiscoveryPlan(ControllerModel):
    enabled: bool = False
    allowed_vid_pid: list[str] = Field(default_factory=list, max_length=128)
    baud_rates: list[int] = Field(default_factory=lambda: [115200], max_length=16)
    manifest_probe_enabled: bool = False
    manifest_command: str = Field(default="WHOAMI", min_length=1, max_length=64)
    manifest_timeout_seconds: float = Field(default=1.5, gt=0, le=30)

    @field_validator("allowed_vid_pid")
    @classmethod
    def validate_vid_pid(cls, values: list[str]) -> list[str]:
        for value in values:
            parts = value.split(":")
            if len(parts) != 2 or any(
                len(part) != 4
                or any(char not in "0123456789abcdefABCDEF" for char in part)
                for part in parts
            ):
                raise ValueError("allowedVidPid entries must use four-digit VID:PID")
        return [value.casefold() for value in values]

    @field_validator("baud_rates")
    @classmethod
    def validate_baud_rates(cls, values: list[int]) -> list[int]:
        if any(value < 1200 or value > 4_000_000 for value in values):
            raise ValueError("Serial baud rate is outside the supported range")
        if len(values) != len(set(values)):
            raise ValueError("Serial baud rates must be unique")
        return values


class I2CRegisterIdentity(ControllerModel):
    address: str = Field(pattern=r"^0x[0-9a-fA-F]{2}$")
    identity_register: str = Field(
        alias="register",
        pattern=r"^0x[0-9a-fA-F]{2}$",
    )
    expected: str = Field(pattern=r"^0x[0-9a-fA-F]{2}$")


class I2CIdentificationRule(ControllerModel):
    address: str | None = Field(
        default=None,
        pattern=r"^0x[0-9a-fA-F]{2}$",
    )
    identity_register: str | None = Field(
        default=None,
        alias="register",
        pattern=r"^0x[0-9a-fA-F]{2}$",
    )
    expected: str | None = Field(
        default=None,
        pattern=r"^0x[0-9a-fA-F]{2}$",
    )
    identities: list[I2CRegisterIdentity] = Field(
        default_factory=list,
        max_length=16,
    )
    model: str = Field(min_length=1, max_length=255)
    profile: str = Field(min_length=1, max_length=255)
    capabilities: list[str] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def require_one_identity_mode(self) -> "I2CIdentificationRule":
        singular = (
            self.address,
            self.identity_register,
            self.expected,
        )
        has_any_singular = any(value is not None for value in singular)
        has_all_singular = all(value is not None for value in singular)
        if self.identities and has_any_singular:
            raise ValueError(
                "I2C rule must use either one register identity or identities"
            )
        if not self.identities and not has_all_singular:
            raise ValueError(
                "I2C rule requires address/register/expected or identities"
            )
        identity_keys = [
            (
                identity.address.casefold(),
                identity.identity_register.casefold(),
            )
            for identity in self.identity_checks()
        ]
        if len(identity_keys) != len(set(identity_keys)):
            raise ValueError("I2C identity checks must be unique")
        return self

    def identity_checks(self) -> list[I2CRegisterIdentity]:
        if self.identities:
            return list(self.identities)
        return [
            I2CRegisterIdentity(
                address=str(self.address),
                register=str(self.identity_register),
                expected=str(self.expected),
            )
        ]


class I2CDiscoveryPlan(ControllerModel):
    enabled: bool = False
    buses: list[int] = Field(default_factory=list, max_length=64)
    allowed_addresses: list[str] = Field(default_factory=list, max_length=128)
    active_probe_enabled: bool = False
    identification_rules: list[I2CIdentificationRule] = Field(
        default_factory=list,
        max_length=128,
    )

    @field_validator("buses")
    @classmethod
    def validate_buses(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 255 for value in values):
            raise ValueError("I2C bus numbers must be between 0 and 255")
        if len(values) != len(set(values)):
            raise ValueError("I2C buses must be unique")
        return values

    @field_validator("allowed_addresses")
    @classmethod
    def validate_addresses(cls, values: list[str]) -> list[str]:
        for value in values:
            if (
                len(value) != 4
                or not value.startswith("0x")
                or any(char not in "0123456789abcdefABCDEF" for char in value[2:])
            ):
                raise ValueError("I2C addresses must use 0xNN notation")
        return [value.casefold() for value in values]

    @model_validator(mode="after")
    def validate_active_probe_contract(self) -> "I2CDiscoveryPlan":
        if not self.active_probe_enabled:
            return self
        if not self.enabled:
            raise ValueError("active I2C probe requires i2c.enabled=true")
        if not self.buses:
            raise ValueError("active I2C probe requires an allowlisted bus")
        if not self.allowed_addresses:
            raise ValueError(
                "active I2C probe requires allowlisted addresses"
            )
        if not self.identification_rules:
            raise ValueError(
                "active I2C probe requires identification rules"
            )
        allowed = set(self.allowed_addresses)
        for rule in self.identification_rules:
            for identity in rule.identity_checks():
                if identity.address.casefold() not in allowed:
                    raise ValueError(
                        "I2C identification rule references a non-allowlisted "
                        "address"
                    )
        return self


class ModbusDiscoveryPlan(ControllerModel):
    enabled: bool = False
    endpoints: list[str] = Field(default_factory=list, max_length=128)
    cidrs: list[str] = Field(default_factory=list, max_length=64)
    unit_ids: list[int] = Field(default_factory=list, max_length=248)


class OPCUADiscoveryPlan(ControllerModel):
    enabled: bool = False
    endpoints: list[str] = Field(default_factory=list, max_length=128)


class ONVIFDiscoveryPlan(ControllerModel):
    enabled: bool = False
    cidrs: list[str] = Field(default_factory=list, max_length=64)


class MQTTDiscoveryPlan(ControllerModel):
    enabled: bool = False
    discovery_topic: str = Field(
        default="edge/discovery/+/+",
        min_length=1,
        max_length=512,
    )
    broker_ref: str | None = Field(default=None, max_length=255)


class DiscoveryPlan(ControllerModel):
    node_id: str = Field(min_length=1, max_length=253)
    serial: SerialDiscoveryPlan = Field(default_factory=SerialDiscoveryPlan)
    i2c: I2CDiscoveryPlan = Field(default_factory=I2CDiscoveryPlan)
    modbus_rtu: ModbusDiscoveryPlan = Field(default_factory=ModbusDiscoveryPlan)
    modbus_tcp: ModbusDiscoveryPlan = Field(default_factory=ModbusDiscoveryPlan)
    opcua: OPCUADiscoveryPlan = Field(default_factory=OPCUADiscoveryPlan)
    onvif: ONVIFDiscoveryPlan = Field(default_factory=ONVIFDiscoveryPlan)
    mqtt: MQTTDiscoveryPlan = Field(default_factory=MQTTDiscoveryPlan)
    version: int = Field(default=1, ge=1)
    updated_at: datetime | None = None

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _timezone_required(value)


class CandidateApprovalRequest(ControllerModel):
    actor: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)
    request_ref: CandidateMutationRef


class CandidateRejectRequest(ControllerModel):
    actor: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)
    request_ref: CandidateMutationRef


class CandidateRetryRequest(ControllerModel):
    actor: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)
    request_ref: CandidateMutationRef


class DiscoveryReconcileRequest(ControllerModel):
    node_id: str | None = Field(default=None, max_length=253)
    protocol: DiscoveryProtocol | None = None


class RegistrationRecord(ControllerModel):
    candidate_id: str
    status: DiscoveryState
    step: str
    attempt: int = Field(default=1, ge=1)
    binding_id: str | None = None
    runtime_name: str | None = None
    service_name: str | None = None
    profile_name: str | None = None
    device_name: str | None = None
    created_runtime: bool = False
    created_profile: bool = False
    created_device: bool = False
    started_at: datetime
    updated_at: datetime
    event_not_before: datetime | None = None
    event_deadline: datetime | None = None
    completed_at: datetime | None = None
    last_error_code: str | None = None
    last_error: str | None = None

    @field_validator(
        "started_at",
        "updated_at",
        "event_not_before",
        "event_deadline",
        "completed_at",
    )
    @classmethod
    def validate_registration_time(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return None if value is None else _timezone_required(value)


class DiscoveryAuditEvent(ControllerModel):
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_type: str = Field(min_length=1, max_length=128)
    occurred_at: datetime
    candidate_id: str | None = None
    node_id: str | None = None
    protocol: DiscoveryProtocol | None = None
    actor: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def validate_event_time(cls, value: datetime) -> datetime:
        return _timezone_required(value)


class CandidatePage(ControllerModel):
    items: list[CandidateView]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


def model_payload(model: ControllerModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)
