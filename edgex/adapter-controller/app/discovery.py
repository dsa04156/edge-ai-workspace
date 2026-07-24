from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from .api import ControllerConflict, ControllerNotFound, ControllerValidationError
from .catalog import RuntimeTemplateCatalog
from .discovery_models import (
    CandidateActionRef,
    CandidateDecisionUpdate,
    CandidateDeleteRequest,
    CandidatePackageState,
    CandidateRegistryDocument,
    CandidateView,
    DiscoveryInventory,
    DiscoveryNodeView,
    ManualCandidateCreate,
    ManualCandidateInput,
    NodeDiscoveryReport,
    StoredCandidate,
    StoredDiscoveryNode,
)


SECRET_KEY_PATTERN = re.compile(
    r"(?:password|passwd|token|secret|credential|private.?key)",
    re.IGNORECASE,
)


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
    return f"candidate-{identity_hash[:24]}"


class DeviceCandidateRegistry:
    def __init__(
        self,
        catalog: RuntimeTemplateCatalog,
        kube: Any,
        *,
        stale_after_seconds: int = 90,
        candidate_limit: int = 2000,
    ) -> None:
        if stale_after_seconds < 10:
            raise ValueError("discovery stale threshold must be at least 10 seconds")
        if candidate_limit < 1:
            raise ValueError("candidate limit must be positive")
        self.catalog = catalog
        self.kube = kube
        self.stale_after_seconds = stale_after_seconds
        self.candidate_limit = candidate_limit
        self._lock = RLock()

    def list_inventory(self) -> DiscoveryInventory:
        with self._lock:
            document, _ = self.kube.read_candidate_registry()
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
            document, resource_version = self.kube.read_candidate_registry()
            registry = CandidateRegistryDocument.model_validate(document)
            candidates = {item.candidate_id: item for item in registry.candidates}
            for observed in report.candidates:
                identity_hash = _canonical_hash(
                    {
                        "source": "node-scan",
                        "nodeName": report.node_name,
                        "protocol": observed.protocol,
                        "hardwareKey": observed.hardware_key,
                    }
                )
                candidate_id = _candidate_id(identity_hash)
                existing = candidates.get(candidate_id)
                if existing is None:
                    self._require_capacity(len(candidates))
                    candidates[candidate_id] = StoredCandidate(
                        candidate_id=candidate_id,
                        identity_hash=identity_hash,
                        source="node-scan",
                        node_name=report.node_name,
                        protocol=observed.protocol,
                        transport=observed.transport,
                        display_name=observed.display_name,
                        device_path=observed.device_path,
                        properties=deepcopy(observed.properties),
                        evidence=deepcopy(observed.evidence),
                        discovered_by=report.agent_id,
                        first_seen=report.observed_at,
                        last_seen=report.observed_at,
                        updated_at=now,
                    )
                    continue
                existing.transport = observed.transport
                existing.display_name = observed.display_name
                existing.device_path = observed.device_path
                existing.properties = deepcopy(observed.properties)
                existing.evidence = deepcopy(observed.evidence)
                existing.discovered_by = report.agent_id
                if report.observed_at > existing.last_seen:
                    existing.last_seen = report.observed_at
                existing.updated_at = now

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
            self.kube.write_candidate_registry(
                updated.model_dump(by_alias=True, mode="json", exclude_none=True),
                resource_version=resource_version,
            )
        return self.list_inventory()

    def create_manual(self, request: ManualCandidateCreate) -> CandidateView:
        candidate = request.candidate
        self._validate_manual_candidate(candidate)
        if not self.kube.node_exists(candidate.node_name):
            raise ControllerValidationError("manual candidate references an unknown node")
        identity_hash = _canonical_hash(
            {
                "source": "manual",
                "nodeName": candidate.node_name,
                "protocol": candidate.protocol,
                "transport": candidate.transport,
                "devicePath": candidate.device_path,
                "properties": candidate.properties,
            }
        )
        candidate_id = _candidate_id(identity_hash)
        now = _now()
        with self._lock:
            document, resource_version = self.kube.read_candidate_registry()
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
                    existing.deleted_at = None
                    existing.decision = "pending"
                    existing.decision_note = ""
                    existing.transport = candidate.transport
                    existing.display_name = candidate.display_name
                    existing.device_path = candidate.device_path
                    existing.properties = deepcopy(candidate.properties)
                    existing.note = candidate.note
                    existing.last_seen = now
                    existing.updated_at = now
                    existing.last_action_ref = CandidateActionRef(
                        action="create",
                        request_id=request.request_ref.request_id,
                        payload_hash=request.request_ref.payload_hash,
                    )
                    self.kube.write_candidate_registry(
                        registry.model_dump(
                            by_alias=True,
                            mode="json",
                            exclude_none=True,
                        ),
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
            registry.candidates.append(created)
            self.kube.write_candidate_registry(
                registry.model_dump(by_alias=True, mode="json", exclude_none=True),
                resource_version=resource_version,
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
                candidate.updated_at = now
                candidate.last_action_ref = CandidateActionRef(
                    action="decision",
                    request_id=request.request_ref.request_id,
                    payload_hash=request.request_ref.payload_hash,
                )
                self.kube.write_candidate_registry(
                    registry.model_dump(by_alias=True, mode="json", exclude_none=True),
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
            self.kube.write_candidate_registry(
                registry.model_dump(by_alias=True, mode="json", exclude_none=True),
                resource_version=resource_version,
            )
            return deleted_view

    def _require_candidate(
        self,
        candidate_id: str,
    ) -> tuple[CandidateRegistryDocument, str | None, StoredCandidate]:
        document, resource_version = self.kube.read_candidate_registry()
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
            properties=deepcopy(candidate.properties),
            evidence=deepcopy(candidate.evidence),
            note=candidate.note,
            decision=candidate.decision,
            decision_note=candidate.decision_note,
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
            if mode == "tcp":
                self._require_string(properties, "Host")
                self._require_integer(properties, "Port", minimum=1, maximum=65535)
            elif mode == "rtu":
                if not candidate.device_path or not candidate.device_path.startswith(
                    "/dev/serial/by-id/"
                ):
                    raise ControllerValidationError(
                        "Modbus RTU requires a stable /dev/serial/by-id path"
                    )
                self._require_integer(
                    properties,
                    "BaudRate",
                    minimum=1200,
                    maximum=4_000_000,
                )
            else:
                raise ControllerValidationError("Modbus Mode must be tcp or rtu")
            self._require_integer(properties, "UnitID", minimum=0, maximum=247)
        elif protocol == "opcua":
            self._require_url(properties, "Endpoint", {"opc.tcp"})
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
