from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .device_management_models import EdgeXScalar, ManagementModel


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


class CandidateMutationRef(ManagementModel):
    request_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManualCandidateInput(ManagementModel):
    node_name: str = Field(min_length=1, max_length=253)
    protocol: DiscoveryProtocol
    transport: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    device_path: str | None = Field(
        default=None,
        pattern=r"^/dev/[A-Za-z0-9._/,:@+~-]+$",
    )
    properties: dict[str, EdgeXScalar] = Field(default_factory=dict)
    note: str = Field(default="", max_length=1000)


class ManualCandidateCreate(ManagementModel):
    candidate: ManualCandidateInput
    request_ref: CandidateMutationRef


class CandidateDecisionInput(ManagementModel):
    decision: CandidateDecision
    note: str = Field(default="", max_length=1000)


class CandidateDecisionUpdate(CandidateDecisionInput):
    request_ref: CandidateMutationRef


class CandidateDeleteRequest(ManagementModel):
    request_ref: CandidateMutationRef


class CandidateView(ManagementModel):
    candidate_id: str
    source: Literal["node-scan", "manual"]
    node_name: str
    protocol: DiscoveryProtocol
    transport: str
    display_name: str
    device_path: str | None = None
    properties: dict[str, EdgeXScalar] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)
    note: str = ""
    decision: CandidateDecision
    decision_note: str = ""
    presence: Literal["present", "stale", "declared"]
    first_seen: datetime
    last_seen: datetime
    updated_at: datetime
    matched_adapter_id: str | None = None
    matched_hardware_binding_id: str | None = None
    package_state: Literal[
        "registration-ready",
        "binding-required",
        "verification-required",
        "unsupported",
    ]
    package_reason: str
    registration_ready: bool = False


class DiscoveryNodeView(ManagementModel):
    node_name: str
    agent_id: str
    last_report_at: datetime
    presence: Literal["online", "stale"]
    candidate_count: int = Field(ge=0)
    scan_errors: list[str] = Field(default_factory=list)


class DiscoveryInventory(ManagementModel):
    generated_at: datetime
    stale_after_seconds: int
    nodes: list[DiscoveryNodeView]
    candidates: list[CandidateView]
    total_candidates: int = Field(default=0, ge=0)
    filtered_candidates: int = Field(default=0, ge=0)
