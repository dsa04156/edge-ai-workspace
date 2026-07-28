from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from .api import ControllerConflict, ControllerNotFound, ControllerValidationError
from .catalog import RuntimeTemplateCatalog
from .device_catalog import DeviceBindingCatalog
from .discovery_models import (
    CandidateActionRef,
    CandidateDecisionUpdate,
    CandidateDecommissionRequest,
    CandidateDeleteRequest,
    CandidatePackageState,
    CandidateRegistryDocument,
    CandidateTransition,
    CandidateView,
    DiscoveryAuditEvent,
    DiscoveryInventory,
    DiscoveryNodeView,
    DiscoveryPlan,
    DiscoveryState,
    ManualCandidateCreate,
    ManualCandidateInput,
    NodeDiscoveryReport,
    StoredCandidate,
    StoredDiscoveryNode,
)
from .discovery_state import (
    InvalidDiscoveryTransition,
    initial_transition,
    restore_state,
    transition_candidate,
)
from .discovery_store import SQLiteDiscoveryStore


SECRET_KEY_PATTERN = re.compile(
    r"(?:password|passwd|token|secret|credential|private.?key)",
    re.IGNORECASE,
)
audit_logger = logging.getLogger("app.discovery.audit")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_id(identity_hash: str) -> str:
    return f"candidate-{identity_hash}"


def _without_sensitive_keys(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): deepcopy(value)
        for key, value in payload.items()
        if SECRET_KEY_PATTERN.search(str(key)) is None
    }


def stable_candidate_identity(
    node_id: str,
    protocol: str,
    stable_hardware_id: str,
) -> tuple[str, str]:
    identity_hash = hashlib.sha256(
        f"{node_id}|{protocol}|{stable_hardware_id}".encode("utf-8")
    ).hexdigest()
    return _candidate_id(identity_hash), identity_hash


class DeviceCandidateRegistry:
    def __init__(
        self,
        catalog: RuntimeTemplateCatalog,
        kube: Any,
        *,
        stale_after_seconds: int = 90,
        candidate_limit: int = 2000,
        store: SQLiteDiscoveryStore | None = None,
        device_catalog: DeviceBindingCatalog | None = None,
        plans_path: Any | None = None,
    ) -> None:
        if stale_after_seconds < 10:
            raise ValueError("discovery stale threshold must be at least 10 seconds")
        if candidate_limit < 1:
            raise ValueError("candidate limit must be positive")
        self.catalog = catalog
        self.kube = kube
        self.stale_after_seconds = stale_after_seconds
        self.candidate_limit = candidate_limit
        self.store = store
        self.device_catalog = device_catalog
        self._lock = RLock()
        if self.store is not None and self.store.is_empty():
            legacy, _ = self.kube.read_candidate_registry()
            self.store.import_legacy_registry(legacy)
        if self.store is not None and plans_path is not None:
            self._seed_plans(plans_path)

    def list_inventory(self) -> DiscoveryInventory:
        with self._lock:
            document, _ = self._read_registry()
            registry = CandidateRegistryDocument.model_validate(document)
            now = _now()
            candidates = [
                self._candidate_view(item, now=now)
                for item in registry.candidates
                if item.deleted_at is None
            ]
            nodes = [
                DiscoveryNodeView(
                    node_name=item.node_name,
                    agent_id=item.agent_id,
                    last_report_at=item.last_report_at,
                    presence=(
                        "online"
                        if (now - item.last_report_at).total_seconds()
                        <= self.stale_after_seconds
                        else "stale"
                    ),
                    candidate_count=item.candidate_count,
                    scan_errors=item.scan_errors,
                )
                for item in registry.nodes
            ]
            return DiscoveryInventory(
                generated_at=now,
                stale_after_seconds=self.stale_after_seconds,
                nodes=sorted(nodes, key=lambda item: item.node_name),
                candidates=sorted(
                    candidates,
                    key=lambda item: (
                        item.decision == "ignored",
                        item.presence == "stale",
                        item.node_name,
                        item.protocol,
                        item.display_name.casefold(),
                    ),
                ),
            )

    def ingest_report(self, report: NodeDiscoveryReport) -> DiscoveryInventory:
        if not self.kube.node_exists(report.node_name):
            raise ControllerValidationError("discovery report references an unknown node")
        now = _now()
        if abs((now - report.observed_at).total_seconds()) > 300:
            raise ControllerValidationError(
                "discovery report timestamp is outside the accepted window"
            )
        with self._lock:
            document, resource_version = self._read_registry()
            registry = CandidateRegistryDocument.model_validate(document)
            candidates = {item.candidate_id: item for item in registry.candidates}
            observed_candidate_ids: set[str] = set()
            for observed in report.candidates:
                hardware_id = (
                    observed.hardware_id
                    or str(observed.properties.get("SerialNumber") or "")
                    or observed.hardware_key
                )
                candidate_id, identity_hash = stable_candidate_identity(
                    report.node_name,
                    observed.protocol,
                    hardware_id,
                )
                existing = candidates.get(candidate_id)
                if existing is None:
                    # The path fallback exists only to adopt version-1
                    # ConfigMap records whose candidate ID used a truncated
                    # hash. Never merge two current candidates merely because
                    # a different device later occupied the same port.
                    existing = next(
                        (
                            item
                            for item in candidates.values()
                            if len(item.candidate_id)
                            == len("candidate-") + 24
                            and item.node_name == report.node_name
                            and item.protocol == observed.protocol
                            and item.device_path == observed.device_path
                        ),
                        None,
                    )
                if existing is None:
                    self._require_capacity(len(candidates))
                    created = StoredCandidate(
                        candidate_id=candidate_id,
                        identity_hash=identity_hash,
                        source="node-scan",
                        node_name=report.node_name,
                        protocol=observed.protocol,
                        transport=observed.transport,
                        display_name=observed.display_name,
                        device_path=observed.device_path,
                        hardware_id=hardware_id,
                        vendor=observed.vendor
                        or str(observed.properties.get("Manufacturer") or "")
                        or None,
                        model=observed.model,
                        firmware_version=observed.firmware_version,
                        capabilities=list(observed.capabilities),
                        recommended_profile=observed.recommended_profile,
                        match_confidence=observed.match_confidence,
                        properties=_without_sensitive_keys(
                            observed.properties
                        ),
                        evidence=_without_sensitive_keys(observed.evidence),
                        discovered_by=report.agent_id,
                        first_seen=report.observed_at,
                        last_seen=report.observed_at,
                        updated_at=now,
                    )
                    initial_transition(
                        created,
                        reason="stable hardware identity was observed",
                        actor=report.agent_id,
                    )
                    self._classify_candidate(
                        created,
                        actor="adapter-controller",
                    )
                    candidates[candidate_id] = created
                    observed_candidate_ids.add(candidate_id)
                    self._audit(
                        "candidate.detected",
                        created,
                        actor=report.agent_id,
                        message="node-local discovery reported a new candidate",
                    )
                    continue
                rediscovered_after_decommission = existing.deleted_at is not None
                if rediscovered_after_decommission:
                    if existing.state != "STALE":
                        transition_candidate(
                            existing,
                            "STALE",
                            reason=(
                                "decommissioned candidate remained physically "
                                "connected"
                            ),
                            actor=report.agent_id,
                            occurred_at=now,
                        )
                    transition_candidate(
                        existing,
                        "DETECTED",
                        reason=(
                            "stable hardware identity was automatically "
                            "discovered again"
                        ),
                        actor=report.agent_id,
                        occurred_at=now,
                    )
                    existing.deleted_at = None
                    existing.decision = "pending"
                    existing.decision_note = ""
                    existing.auth_state = "not_checked"
                    existing.failure_reason = None
                    existing.retry_count = 0
                    existing.registration_step = None
                    existing.matched_binding_id = None
                    existing.match_confidence = "none"
                    existing.last_action_ref = None
                observed_candidate_ids.add(existing.candidate_id)
                if existing.state == "STALE":
                    try:
                        transition_candidate(
                            existing,
                            restore_state(existing),
                            reason="stable hardware identity was observed again",
                            actor=report.agent_id,
                            occurred_at=now,
                        )
                    except InvalidDiscoveryTransition:
                        pass
                existing.transport = observed.transport
                existing.display_name = observed.display_name
                existing.device_path = observed.device_path
                existing.hardware_id = hardware_id
                existing.vendor = (
                    observed.vendor
                    or str(observed.properties.get("Manufacturer") or "")
                    or None
                )
                existing.model = observed.model or existing.model
                existing.firmware_version = (
                    observed.firmware_version or existing.firmware_version
                )
                existing.capabilities = (
                    list(observed.capabilities)
                    if observed.capabilities
                    else existing.capabilities
                )
                existing.recommended_profile = (
                    observed.recommended_profile
                    or existing.recommended_profile
                )
                existing.properties = _without_sensitive_keys(
                    observed.properties
                )
                existing.evidence = _without_sensitive_keys(
                    observed.evidence
                )
                existing.discovered_by = report.agent_id
                if report.observed_at > existing.last_seen:
                    existing.last_seen = report.observed_at
                existing.updated_at = now
                if existing.state in {"DETECTED", "IDENTIFIED", "BLOCKED"}:
                    self._classify_candidate(
                        existing,
                        actor="adapter-controller",
                    )
                if rediscovered_after_decommission:
                    self._audit(
                        "candidate.rediscovered",
                        existing,
                        actor=report.agent_id,
                        message=(
                            "decommissioned stable hardware identity was "
                            "observed again"
                        ),
                        details={
                            "currentState": "DETECTED",
                            "nextState": existing.state,
                        },
                    )

            if not report.scan_errors:
                for candidate in candidates.values():
                    if (
                        candidate.source != "node-scan"
                        or candidate.node_name != report.node_name
                        or candidate.candidate_id in observed_candidate_ids
                        or candidate.deleted_at is not None
                        or candidate.state == "STALE"
                    ):
                        continue
                    transition_candidate(
                        candidate,
                        "STALE",
                        reason=(
                            "candidate was absent from the latest clean "
                            "node reconciliation"
                        ),
                        actor=report.agent_id,
                        error_code="CANDIDATE_DISCONNECTED",
                        occurred_at=report.observed_at,
                    )
                    self._audit(
                        "candidate.disconnected",
                        candidate,
                        actor=report.agent_id,
                        message=(
                            "candidate was absent from the latest clean "
                            "node reconciliation"
                        ),
                        details={
                            "nextState": "STALE",
                            "errorCode": "CANDIDATE_DISCONNECTED",
                        },
                    )

            node_record = StoredDiscoveryNode(
                node_name=report.node_name,
                agent_id=report.agent_id,
                last_report_at=report.observed_at,
                candidate_count=len(report.candidates),
                scan_errors=report.scan_errors,
            )
            nodes = {
                item.node_name: item
                for item in registry.nodes
            }
            nodes[report.node_name] = node_record
            updated = CandidateRegistryDocument(
                nodes=list(nodes.values()),
                candidates=list(candidates.values()),
            )
            self._write_registry(
                updated,
                resource_version=resource_version,
            )
        return self.list_inventory()

    def create_manual(self, request: ManualCandidateCreate) -> CandidateView:
        candidate = request.candidate
        self._validate_manual_candidate(candidate)
        if not self.kube.node_exists(candidate.node_name):
            raise ControllerValidationError("manual candidate references an unknown node")
        hardware_id = candidate.hardware_id or _canonical_hash(
            {
                "transport": candidate.transport,
                "devicePath": candidate.device_path,
                "properties": candidate.properties,
            }
        )
        candidate_id, identity_hash = stable_candidate_identity(
            candidate.node_name,
            candidate.protocol,
            hardware_id,
        )
        now = _now()
        with self._lock:
            document, resource_version = self._read_registry()
            registry = CandidateRegistryDocument.model_validate(document)
            existing = next(
                (
                    item
                    for item in registry.candidates
                    if item.candidate_id == candidate_id
                ),
                None,
            )
            if existing is not None:
                if existing.deleted_at is not None:
                    if existing.state != "STALE":
                        transition_candidate(
                            existing,
                            "STALE",
                            reason=(
                                "decommissioned candidate was explicitly "
                                "declared again"
                            ),
                            actor="dashboard",
                            occurred_at=now,
                        )
                    transition_candidate(
                        existing,
                        "DETECTED",
                        reason=(
                            "operator explicitly re-declared the stable "
                            "hardware identity"
                        ),
                        actor="dashboard",
                        occurred_at=now,
                    )
                    existing.deleted_at = None
                    existing.decision = "pending"
                    existing.decision_note = ""
                    existing.auth_state = "not_checked"
                    existing.failure_reason = None
                    existing.retry_count = 0
                    existing.registration_step = None
                    existing.matched_binding_id = None
                    existing.match_confidence = "none"
                    existing.transport = candidate.transport
                    existing.display_name = candidate.display_name
                    existing.device_path = candidate.device_path
                    existing.properties = deepcopy(candidate.properties)
                    existing.hardware_id = hardware_id
                    existing.vendor = candidate.vendor
                    existing.model = candidate.model
                    existing.capabilities = list(candidate.capabilities)
                    existing.recommended_profile = candidate.recommended_profile
                    existing.note = candidate.note
                    existing.last_seen = now
                    existing.updated_at = now
                    existing.last_action_ref = CandidateActionRef(
                        action="create",
                        request_id=request.request_ref.request_id,
                        payload_hash=request.request_ref.payload_hash,
                    )
                    self._classify_candidate(
                        existing,
                        actor="dashboard",
                    )
                    self._write_registry(
                        registry,
                        resource_version=resource_version,
                    )
                    return self._candidate_view(existing, now=now)
                self._assert_replay(
                    existing.last_action_ref,
                    action="create",
                    request_id=request.request_ref.request_id,
                    payload_hash=request.request_ref.payload_hash,
                )
                return self._candidate_view(existing, now=now)
            self._require_capacity(len(registry.candidates))
            created = StoredCandidate(
                candidate_id=candidate_id,
                identity_hash=identity_hash,
                source="manual",
                node_name=candidate.node_name,
                protocol=candidate.protocol,
                transport=candidate.transport,
                display_name=candidate.display_name,
                device_path=candidate.device_path,
                hardware_id=hardware_id,
                vendor=candidate.vendor,
                model=candidate.model,
                capabilities=list(candidate.capabilities),
                recommended_profile=candidate.recommended_profile,
                properties=deepcopy(candidate.properties),
                note=candidate.note,
                first_seen=now,
                last_seen=now,
                updated_at=now,
                last_action_ref=CandidateActionRef(
                    action="create",
                    request_id=request.request_ref.request_id,
                    payload_hash=request.request_ref.payload_hash,
                ),
            )
            initial_transition(
                created,
                reason="operator declared a protocol endpoint candidate",
                actor="dashboard",
            )
            self._classify_candidate(created, actor="adapter-controller")
            registry.candidates.append(created)
            self._write_registry(
                registry,
                resource_version=resource_version,
            )
            self._audit(
                "candidate.declared",
                created,
                actor="dashboard",
                message="operator declared a discovery candidate",
            )
            return self._candidate_view(created, now=now)

    def update_decision(
        self,
        candidate_id: str,
        request: CandidateDecisionUpdate,
    ) -> CandidateView:
        now = _now()
        with self._lock:
            registry, resource_version, candidate = self._require_candidate(candidate_id)
            replay = self._assert_replay(
                candidate.last_action_ref,
                action="decision",
                request_id=request.request_ref.request_id,
                payload_hash=request.request_ref.payload_hash,
                allow_missing=True,
            )
            if not replay:
                candidate.decision = request.decision
                candidate.decision_note = request.note
                self._apply_legacy_decision_transition(
                    candidate,
                    request.decision,
                    request.note,
                )
                candidate.updated_at = now
                candidate.last_action_ref = CandidateActionRef(
                    action="decision",
                    request_id=request.request_ref.request_id,
                    payload_hash=request.request_ref.payload_hash,
                )
                self._write_registry(
                    registry,
                    resource_version=resource_version,
                )
            return self._candidate_view(candidate, now=now)

    def delete_candidate(
        self,
        candidate_id: str,
        request: CandidateDeleteRequest,
    ) -> CandidateView:
        now = _now()
        with self._lock:
            registry, resource_version, candidate = self._require_candidate(candidate_id)
            if candidate.state in {
                "APPROVED",
                "SERVICE_READY",
                "METADATA_REGISTERED",
                "EVENT_CONFIRMED",
            }:
                raise ControllerConflict(
                    "registered candidate cannot be deleted without an "
                    "explicit decommission workflow"
                )
            replay = self._assert_replay(
                candidate.last_action_ref,
                action="delete",
                request_id=request.request_ref.request_id,
                payload_hash=request.request_ref.payload_hash,
                allow_missing=True,
            )
            deleted_view = self._candidate_view(candidate, now=now)
            if replay:
                return deleted_view
            if candidate.source == "manual":
                candidate.deleted_at = now
                candidate.updated_at = now
                candidate.last_action_ref = CandidateActionRef(
                    action="delete",
                    request_id=request.request_ref.request_id,
                    payload_hash=request.request_ref.payload_hash,
                )
            else:
                candidate.decision = "ignored"
                candidate.decision_note = (
                    "자동 발견 후보는 재관측될 수 있어 삭제 대신 무시 처리했습니다."
                )
                candidate.updated_at = now
                candidate.last_action_ref = CandidateActionRef(
                    action="delete",
                    request_id=request.request_ref.request_id,
                    payload_hash=request.request_ref.payload_hash,
                )
                deleted_view = self._candidate_view(candidate, now=now)
            self._write_registry(
                registry,
                resource_version=resource_version,
            )
            return deleted_view

    def decommission_candidate(
        self,
        candidate_id: str,
        request: CandidateDecommissionRequest,
    ) -> CandidateView:
        now = _now()
        with self._lock:
            registry, resource_version, candidate = self._require_candidate(candidate_id)
            if candidate.state not in {
                "APPROVED",
                "SERVICE_READY",
                "METADATA_REGISTERED",
                "EVENT_CONFIRMED",
                "FAILED",
            }:
                raise ControllerConflict(
                    "only a registered or failed registration candidate can be "
                    "decommissioned"
                )
            replay = self._assert_replay(
                candidate.last_action_ref,
                action="decommission",
                request_id=request.request_ref.request_id,
                payload_hash=request.request_ref.payload_hash,
                allow_missing=True,
            )
            if replay:
                return self._candidate_view(candidate, now=now)
            candidate.deleted_at = now
            candidate.updated_at = now
            candidate.decision = "ignored"
            candidate.decision_note = request.reason
            candidate.last_action_ref = CandidateActionRef(
                action="decommission",
                request_id=request.request_ref.request_id,
                payload_hash=request.request_ref.payload_hash,
            )
            self._write_registry(
                registry,
                resource_version=resource_version,
            )
            self._audit(
                "candidate.decommissioned",
                candidate,
                actor=request.actor,
                message=request.reason,
                details={
                    "currentState": candidate.state,
                    "nextState": candidate.state,
                    "resourcesRemoved": True,
                },
            )
            return self._candidate_view(candidate, now=now)

    def _require_candidate(
        self,
        candidate_id: str,
    ) -> tuple[CandidateRegistryDocument, str | None, StoredCandidate]:
        document, resource_version = self._read_registry()
        registry = CandidateRegistryDocument.model_validate(document)
        candidate = next(
            (
                item
                for item in registry.candidates
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise ControllerNotFound(f"candidate {candidate_id!r} was not found")
        return registry, resource_version, candidate

    def _candidate_view(
        self,
        candidate: StoredCandidate,
        *,
        now: datetime,
    ) -> CandidateView:
        if candidate.source == "manual":
            presence = "declared"
        elif candidate.state == "STALE":
            presence = "stale"
        elif (now - candidate.last_seen).total_seconds() <= self.stale_after_seconds:
            presence = "present"
        else:
            presence = "stale"
        (
            adapter_id,
            binding_id,
            package_state,
            package_reason,
        ) = self._match_package(candidate)
        return CandidateView(
            candidate_id=candidate.candidate_id,
            source=candidate.source,
            node_name=candidate.node_name,
            protocol=candidate.protocol,
            transport=candidate.transport,
            display_name=candidate.display_name,
            device_path=candidate.device_path,
            hardware_id=candidate.hardware_id,
            vendor=candidate.vendor,
            model=candidate.model,
            firmware_version=candidate.firmware_version,
            capabilities=list(candidate.capabilities),
            recommended_profile=candidate.recommended_profile,
            match_confidence=candidate.match_confidence,
            properties=deepcopy(candidate.properties),
            evidence=deepcopy(candidate.evidence),
            note=candidate.note,
            decision=candidate.decision,
            decision_note=candidate.decision_note,
            state=candidate.state,
            auth_state=candidate.auth_state,
            failure_reason=candidate.failure_reason,
            retry_count=candidate.retry_count,
            registration_step=candidate.registration_step,
            transition_count=len(candidate.transitions),
            presence=presence,
            first_seen=candidate.first_seen,
            last_seen=candidate.last_seen,
            updated_at=candidate.updated_at,
            matched_adapter_id=adapter_id,
            matched_hardware_binding_id=binding_id,
            package_state=package_state,
            package_reason=package_reason,
            registration_ready=package_state == "registration-ready",
        )

    def _match_package(
        self,
        candidate: StoredCandidate,
    ) -> tuple[str | None, str | None, CandidatePackageState, str]:
        if self.device_catalog is not None:
            match = self.device_catalog.match(candidate)
            if match.confidence == "exact" and match.binding is not None:
                return (
                    match.binding.adapter.runtime_adapter_id,
                    match.binding.runtime_hardware_binding_id,
                    "registration-ready",
                    "stable identity, Profile, parser와 검증 이미지가 정확히 일치합니다.",
                )
            if match.confidence == "ambiguous":
                return (
                    None,
                    None,
                    "verification-required",
                    "여러 Catalog binding이 일치하여 자동 선택할 수 없습니다.",
                )
            if match.confidence == "partial":
                adapter_id = None
                if match.binding_ids:
                    try:
                        adapter_id = self.device_catalog.get(
                            match.binding_ids[0]
                        ).adapter.runtime_adapter_id
                    except ValueError:
                        adapter_id = None
                return (
                    adapter_id,
                    None,
                    "binding-required",
                    "프로토콜은 알려졌지만 stable identity와 Profile의 exact match가 필요합니다.",
                )
            return (
                None,
                None,
                "unsupported",
                "검증된 Device/Profile Catalog binding이 없습니다.",
            )
        templates = [
            item
            for item in self.catalog.templates
            if item.protocol_name.casefold() == candidate.protocol.casefold()
        ]
        if not templates:
            return (
                None,
                None,
                "unsupported",
                "이 프로토콜의 Device Service 패키지가 카탈로그에 없습니다.",
            )
        for template in templates:
            for binding in template.hardware_bindings:
                if (
                    binding.node_name == candidate.node_name
                    and candidate.device_path is not None
                    and binding.host_device_path == candidate.device_path
                ):
                    if template.verification_state == "unverified":
                        return (
                            template.adapter_id,
                            binding.binding_id,
                            "verification-required",
                            "연결은 일치하지만 Device Service 실기기 검증이 필요합니다.",
                        )
                    return (
                        template.adapter_id,
                        binding.binding_id,
                        "registration-ready",
                        "검증된 연결과 일치해 EdgeX 등록 흐름으로 진행할 수 있습니다.",
                    )
        verified = next(
            (
                item
                for item in templates
                if item.verification_state != "unverified"
            ),
            None,
        )
        if verified is not None:
            return (
                verified.adapter_id,
                None,
                "binding-required",
                "프로토콜 패키지는 검증됐지만 이 노드의 장치 경로 승인이 필요합니다.",
            )
        return (
            templates[0].adapter_id,
            None,
            "verification-required",
            "Device Service와 실장비 연결 검증 전에는 설치할 수 없습니다.",
        )

    def _validate_manual_candidate(self, candidate: ManualCandidateInput) -> None:
        if any(SECRET_KEY_PATTERN.search(key) for key in candidate.properties):
            raise ControllerValidationError(
                "candidate registry cannot store passwords, tokens, or secrets"
            )
        protocol = candidate.protocol
        properties = candidate.properties
        if protocol == "serial":
            if not candidate.device_path or not candidate.device_path.startswith(
                "/dev/serial/by-id/"
            ):
                raise ControllerValidationError(
                    "manual Serial candidate requires a stable /dev/serial/by-id path"
                )
            self._require_integer(properties, "BaudRate", minimum=1200, maximum=4_000_000)
        elif protocol == "i2c":
            if not candidate.device_path or re.fullmatch(
                r"/dev/i2c-[0-9]+", candidate.device_path
            ) is None:
                raise ControllerValidationError(
                    "manual I2C candidate requires an exact /dev/i2c-N path"
                )
        elif protocol == "mqtt":
            self._require_url(properties, "Broker", {"mqtt", "mqtts", "ws", "wss"})
            self._require_string(properties, "Topic")
        elif protocol == "modbus":
            mode = str(properties.get("Mode") or "").casefold()
            properties["Mode"] = mode
            if mode == "tcp":
                properties["Host"] = self._require_string(properties, "Host")
                properties["Port"] = self._require_integer(
                    properties,
                    "Port",
                    minimum=1,
                    maximum=65535,
                )
            elif mode == "rtu":
                if not candidate.device_path or not candidate.device_path.startswith(
                    "/dev/serial/by-id/"
                ):
                    raise ControllerValidationError(
                        "Modbus RTU requires a stable /dev/serial/by-id path"
                    )
                properties["BaudRate"] = self._require_integer(
                    properties,
                    "BaudRate",
                    minimum=1200,
                    maximum=4_000_000,
                )
            else:
                raise ControllerValidationError("Modbus Mode must be tcp or rtu")
            properties["UnitID"] = self._require_integer(
                properties,
                "UnitID",
                minimum=0,
                maximum=247,
            )
        elif protocol == "opcua":
            self._require_url(properties, "Endpoint", {"opc.tcp"})
        elif protocol == "onvif":
            self._require_url(properties, "Endpoint", {"http", "https"})
        elif protocol == "rtsp":
            self._require_url(properties, "Endpoint", {"rtsp", "rtsps"})
        elif protocol == "rest":
            self._require_url(properties, "Endpoint", {"http", "https"})

    @staticmethod
    def _require_string(properties: dict[str, Any], key: str) -> str:
        value = properties.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ControllerValidationError(f"{key} is required")
        return value.strip()

    @classmethod
    def _require_url(
        cls,
        properties: dict[str, Any],
        key: str,
        schemes: set[str],
    ) -> None:
        value = cls._require_string(properties, key)
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in schemes or not parsed.hostname:
            raise ControllerValidationError(
                f"{key} must use one of: {', '.join(sorted(schemes))}"
            )
        if parsed.username is not None or parsed.password is not None:
            raise ControllerValidationError(
                f"{key} must not contain embedded credentials"
            )

    @staticmethod
    def _require_integer(
        properties: dict[str, Any],
        key: str,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        value = properties.get(key)
        if isinstance(value, bool):
            raise ControllerValidationError(f"{key} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ControllerValidationError(f"{key} must be an integer") from exc
        if parsed < minimum or parsed > maximum:
            raise ControllerValidationError(
                f"{key} must be between {minimum} and {maximum}"
            )
        return parsed

    def _require_capacity(self, current_count: int) -> None:
        if current_count >= self.candidate_limit:
            raise ControllerConflict("device candidate registry is full")

    def get_candidate(self, candidate_id: str) -> CandidateView:
        with self._lock:
            _, _, candidate = self._require_candidate(candidate_id)
            if candidate.deleted_at is not None:
                raise ControllerNotFound(
                    f"candidate {candidate_id!r} was not found"
                )
            return self._candidate_view(candidate, now=_now())

    def get_stored_candidate(self, candidate_id: str) -> StoredCandidate:
        with self._lock:
            _, _, candidate = self._require_candidate(candidate_id)
            return candidate.model_copy(deep=True)

    def save_candidate(self, candidate: StoredCandidate) -> CandidateView:
        with self._lock:
            registry, resource_version, current = self._require_candidate(
                candidate.candidate_id
            )
            index = registry.candidates.index(current)
            registry.candidates[index] = candidate.model_copy(deep=True)
            self._write_registry(
                registry,
                resource_version=resource_version,
            )
            return self._candidate_view(candidate, now=_now())

    def transition(
        self,
        candidate_id: str,
        to_state: DiscoveryState,
        *,
        reason: str,
        actor: str,
        error_code: str | None = None,
    ) -> CandidateView:
        with self._lock:
            registry, resource_version, candidate = self._require_candidate(
                candidate_id
            )
            from_state = candidate.state
            transition_candidate(
                candidate,
                to_state,
                reason=reason,
                actor=actor,
                error_code=error_code,
            )
            if to_state == "APPROVED":
                candidate.decision = "accepted"
                candidate.decision_note = reason
            elif to_state == "REJECTED":
                candidate.decision = "ignored"
                candidate.decision_note = reason
            elif to_state in {"FAILED", "BLOCKED"}:
                candidate.failure_reason = reason
            self._write_registry(
                registry,
                resource_version=resource_version,
            )
            self._audit(
                f"candidate.state.{to_state.casefold()}",
                candidate,
                actor=actor,
                message=reason,
                details={
                    "currentState": from_state,
                    "nextState": to_state,
                    "registrationStep": candidate.registration_step,
                    **({"errorCode": error_code} if error_code else {}),
                },
            )
            return self._candidate_view(candidate, now=_now())

    def reconcile_presence(
        self,
        *,
        node_id: str | None = None,
        protocol: str | None = None,
    ) -> int:
        now = _now()
        changed = 0
        with self._lock:
            document, resource_version = self._read_registry()
            registry = CandidateRegistryDocument.model_validate(document)
            for candidate in registry.candidates:
                if candidate.source != "node-scan":
                    continue
                if node_id and candidate.node_name != node_id:
                    continue
                if protocol and candidate.protocol != protocol:
                    continue
                if candidate.state == "STALE":
                    continue
                if (
                    now - candidate.last_seen
                ).total_seconds() <= self.stale_after_seconds:
                    continue
                transition_candidate(
                    candidate,
                    "STALE",
                    reason="node-local discovery report exceeded the freshness window",
                    actor="adapter-controller",
                    error_code="CANDIDATE_STALE",
                    occurred_at=now,
                )
                changed += 1
            if changed:
                self._write_registry(
                    registry,
                    resource_version=resource_version,
                )
        return changed

    def get_plan(self, node_id: str) -> DiscoveryPlan:
        if not self.kube.node_exists(node_id):
            raise ControllerValidationError(
                "Discovery Plan references an unknown node"
            )
        if self.store is None:
            return DiscoveryPlan(node_id=node_id, updated_at=_now())
        plan = self.store.get_plan(node_id)
        if plan is None:
            return DiscoveryPlan(node_id=node_id, updated_at=_now())
        return plan

    def put_plan(self, plan: DiscoveryPlan) -> DiscoveryPlan:
        if not self.kube.node_exists(plan.node_id):
            raise ControllerValidationError(
                "Discovery Plan references an unknown node"
            )
        now = _now()
        current = self.get_plan(plan.node_id)
        updated = plan.model_copy(
            update={
                "version": current.version + 1,
                "updated_at": now,
            }
        )
        if self.store is None:
            raise ControllerValidationError(
                "Discovery Plan persistence is unavailable"
            )
        self.store.put_plan(updated)
        self._audit_event(
            event_type="discovery.plan.updated",
            actor="operator",
            message=f"Discovery Plan updated for {plan.node_id}",
            node_id=plan.node_id,
            details={"version": updated.version},
        )
        return updated

    def list_events(
        self,
        *,
        candidate_id: str | None = None,
        limit: int = 200,
    ) -> list[DiscoveryAuditEvent]:
        if self.store is None:
            return []
        return self.store.list_events(
            candidate_id=candidate_id,
            limit=limit,
        )

    def _classify_candidate(
        self,
        candidate: StoredCandidate,
        *,
        actor: str,
    ) -> None:
        if self.device_catalog is None:
            return
        match = self.device_catalog.match(candidate)
        candidate.match_confidence = match.confidence
        if match.binding is not None:
            candidate.matched_binding_id = match.binding.binding_id
            candidate.recommended_profile = match.binding.profile.name
        if candidate.state not in {"DETECTED", "IDENTIFIED", "BLOCKED"}:
            return
        if match.confidence == "exact":
            if candidate.state == "BLOCKED":
                if candidate.auth_state != "not_checked":
                    # A fresh observation may resolve Catalog matching, but it
                    # must never erase an external security denial/unavailable
                    # decision. Only an explicit operator retry can do that.
                    return
                transition_candidate(
                    candidate,
                    "PENDING_APPROVAL",
                    reason="Catalog exact match resolved the previous block",
                    actor=actor,
                )
                candidate.failure_reason = None
                return
            if candidate.state == "DETECTED":
                transition_candidate(
                    candidate,
                    "IDENTIFIED",
                    reason="stable identity exactly matched Device/Profile Catalog",
                    actor=actor,
                )
            if candidate.state == "IDENTIFIED":
                transition_candidate(
                    candidate,
                    "PENDING_APPROVAL",
                    reason="identified candidate requires operator approval",
                    actor=actor,
                )
            return
        error_code = (
            "CATALOG_AMBIGUOUS"
            if match.confidence == "ambiguous"
            else "PROFILE_MATCH_REQUIRED"
            if match.confidence == "partial"
            else "UNSUPPORTED_PROTOCOL"
        )
        if candidate.state != "BLOCKED":
            transition_candidate(
                candidate,
                "BLOCKED",
                reason=match.reason,
                actor=actor,
                error_code=error_code,
            )
        candidate.failure_reason = match.reason

    def _apply_legacy_decision_transition(
        self,
        candidate: StoredCandidate,
        decision: str,
        note: str,
    ) -> None:
        reason = note or f"legacy dashboard decision: {decision}"
        try:
            if decision == "accepted" and candidate.state == "PENDING_APPROVAL":
                transition_candidate(
                    candidate,
                    "APPROVED",
                    reason=reason,
                    actor="dashboard",
                )
            elif decision == "ignored" and candidate.state in {
                "PENDING_APPROVAL",
                "BLOCKED",
                "FAILED",
            }:
                transition_candidate(
                    candidate,
                    "REJECTED",
                    reason=reason,
                    actor="dashboard",
                )
            elif decision == "pending" and candidate.state in {
                "REJECTED",
                "BLOCKED",
            }:
                transition_candidate(
                    candidate,
                    "PENDING_APPROVAL",
                    reason=reason,
                    actor="dashboard",
                )
        except InvalidDiscoveryTransition as exc:
            raise ControllerConflict(str(exc)) from exc

    def _read_registry(self) -> tuple[dict[str, Any], str | None]:
        if self.store is not None:
            return self.store.load_registry(), None
        return self.kube.read_candidate_registry()

    def _write_registry(
        self,
        registry: CandidateRegistryDocument,
        *,
        resource_version: str | None,
    ) -> None:
        registry.version = 2
        if self.store is not None:
            self.store.save_registry(registry)
            return
        self.kube.write_candidate_registry(
            registry.model_dump(
                by_alias=True,
                mode="json",
                exclude_none=True,
            ),
            resource_version=resource_version,
        )

    def _seed_plans(self, path: Any) -> None:
        if self.store is None:
            return
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return
        for raw_plan in payload.get("plans") or []:
            try:
                plan = DiscoveryPlan.model_validate(raw_plan)
            except ValueError:
                continue
            current = self.store.get_plan(plan.node_id)
            if current is None or plan.version > current.version:
                self.store.put_plan(
                    plan.model_copy(update={"updated_at": _now()})
                )

    def _audit(
        self,
        event_type: str,
        candidate: StoredCandidate,
        *,
        actor: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit_event(
            event_type=event_type,
            candidate_id=candidate.candidate_id,
            node_id=candidate.node_name,
            protocol=candidate.protocol,
            actor=actor,
            message=message,
            details=details,
        )

    def _audit_event(
        self,
        *,
        event_type: str,
        actor: str,
        message: str,
        candidate_id: str | None = None,
        node_id: str | None = None,
        protocol: Any | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self.store is None:
            return
        occurred_at = _now()
        event_id = _canonical_hash(
            {
                "eventType": event_type,
                "candidateId": candidate_id,
                "occurredAt": occurred_at.isoformat(),
                "actor": actor,
                "message": message,
            }
        )
        self.store.append_event(
            DiscoveryAuditEvent(
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                candidate_id=candidate_id,
                node_id=node_id,
                protocol=protocol,
                actor=actor,
                message=message,
                details=details or {},
            )
        )
        audit_logger.info(
            json.dumps(
                {
                    "eventType": event_type,
                    "candidateId": candidate_id,
                    "nodeId": node_id,
                    "protocol": protocol,
                    "currentState": (
                        details.get("currentState")
                        if details
                        else None
                    ),
                    "nextState": (
                        details.get("nextState")
                        if details
                        else None
                    ),
                    "registrationStep": (
                        details.get("registrationStep")
                        if details
                        else None
                    ),
                    "errorCode": (
                        details.get("errorCode")
                        if details
                        else None
                    ),
                    "actor": actor,
                    "message": message,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _assert_replay(
        action_ref: CandidateActionRef | None,
        *,
        action: str,
        request_id: str,
        payload_hash: str,
        allow_missing: bool = False,
    ) -> bool:
        if action_ref is None:
            if allow_missing:
                return False
            raise ControllerConflict("candidate exists from a different request")
        if action_ref.request_id != request_id:
            if allow_missing:
                return False
            raise ControllerConflict("candidate exists from a different request")
        if action_ref.action != action or action_ref.payload_hash != payload_hash:
            raise ControllerConflict(
                "candidate request ID was reused with a different action or payload"
            )
        return True
