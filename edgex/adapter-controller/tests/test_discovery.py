import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.api import ControllerConflict, ControllerValidationError
from app.catalog import RuntimeTemplateCatalog
from app.device_catalog import DeviceBindingCatalog
from app.discovery import DeviceCandidateRegistry, stable_candidate_identity
from app.discovery_models import (
    CandidateDecisionUpdate,
    CandidateDeleteRequest,
    CandidateMutationRef,
    DiscoveryObservation,
    ManualCandidateCreate,
    ManualCandidateInput,
    NodeDiscoveryReport,
)

from fakes import FakeKubernetesGateway


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "runtime_templates.json"
)
DEVICE_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "device_bindings.json"
)


def mutation_ref(seed: str = "a") -> CandidateMutationRef:
    return CandidateMutationRef(
        request_id=seed * 64,
        payload_hash=("f" if seed != "f" else "e") * 64,
    )


def serial_report(observed_at: datetime | None = None) -> NodeDiscoveryReport:
    return NodeDiscoveryReport(
        node_name="etri-dev0001-jetorn",
        agent_id="node-discovery/etri-dev0001-jetorn",
        observed_at=observed_at or datetime.now(timezone.utc),
        candidates=[
            DiscoveryObservation(
                hardware_key="usb-Arduino-75035303230351E0D171",
                protocol="serial",
                transport="usb-serial",
                display_name="Arduino USB Serial",
                device_path=(
                    "/dev/serial/by-id/"
                    "usb-Arduino__www.arduino.cc__0043_"
                    "75035303230351E0D171-if00"
                ),
                properties={
                    "VendorID": "2341",
                    "ProductID": "0043",
                },
                evidence={"stablePath": "udev-by-id"},
            )
        ],
    )


@pytest.fixture
def registry():
    kube = FakeKubernetesGateway()
    catalog = RuntimeTemplateCatalog.load(CATALOG_PATH)
    return DeviceCandidateRegistry(
        catalog,
        kube,
        stale_after_seconds=90,
        candidate_limit=10,
    ), kube


def test_node_report_creates_stable_registration_ready_candidate(registry):
    service, kube = registry

    first = service.ingest_report(serial_report())
    second = service.ingest_report(serial_report())

    assert len(first.candidates) == 1
    assert len(second.candidates) == 1
    candidate = second.candidates[0]
    assert candidate.candidate_id == first.candidates[0].candidate_id
    assert candidate.presence == "present"
    assert candidate.registration_ready is True
    assert candidate.matched_adapter_id == "serial-jetson"
    assert (
        candidate.matched_hardware_binding_id
        == "jetson-arduino-serial-001"
    )
    assert kube.candidate_registry_version == 2


def test_candidate_id_uses_node_protocol_and_stable_hardware_identity():
    candidate_id, identity_hash = stable_candidate_identity(
        "etri-dev0001-jetorn",
        "serial",
        "75035303230351E0D171",
    )
    expected = hashlib.sha256(
        (
            "etri-dev0001-jetorn|serial|"
            "75035303230351E0D171"
        ).encode()
    ).hexdigest()

    assert identity_hash == expected
    assert candidate_id == f"candidate-{expected}"


def test_discovery_report_does_not_persist_sensitive_raw_metadata(registry):
    service, _ = registry
    incoming = serial_report()
    incoming.candidates[0].properties["Password"] = "must-not-persist"
    incoming.candidates[0].evidence["accessToken"] = "must-not-persist"

    candidate = service.ingest_report(incoming).candidates[0]

    assert "Password" not in candidate.properties
    assert "accessToken" not in candidate.evidence


def test_discovered_candidate_becomes_stale_without_becoming_inventory(registry):
    service, _ = registry
    report = serial_report(datetime.now(timezone.utc) - timedelta(seconds=120))
    service.ingest_report(report)

    inventory = service.list_inventory()

    assert inventory.candidates[0].presence == "stale"
    assert inventory.nodes[0].presence == "stale"
    assert inventory.candidates[0].decision == "pending"


def test_clean_disconnect_and_reconnect_keep_the_same_candidate_id(registry):
    service, _ = registry
    first = service.ingest_report(serial_report()).candidates[0]
    disconnected = service.ingest_report(
        NodeDiscoveryReport(
            node_name="etri-dev0001-jetorn",
            agent_id="node-discovery/etri-dev0001-jetorn",
            observed_at=datetime.now(timezone.utc),
            candidates=[],
            scan_errors=[],
        )
    ).candidates[0]
    reconnected = service.ingest_report(serial_report()).candidates[0]

    assert disconnected.candidate_id == first.candidate_id
    assert disconnected.state == "STALE"
    assert disconnected.presence == "stale"
    assert reconnected.candidate_id == first.candidate_id
    assert reconnected.state != "STALE"


def test_different_hardware_on_the_same_port_creates_a_new_candidate(registry):
    service, _ = registry
    first_report = serial_report()
    first_report.candidates[0].hardware_id = "physical-device-a"
    first = service.ingest_report(first_report).candidates[0]

    replacement_report = serial_report()
    replacement_report.candidates[0].hardware_key = "replacement-device"
    replacement_report.candidates[0].hardware_id = "physical-device-b"
    candidates = service.ingest_report(replacement_report).candidates

    assert len(candidates) == 2
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    assert first.candidate_id in by_id
    assert by_id[first.candidate_id].state == "STALE"
    replacement = next(
        candidate
        for candidate in candidates
        if candidate.candidate_id != first.candidate_id
    )
    assert replacement.hardware_id == "physical-device-b"
    assert replacement.presence == "present"


def test_candidate_decision_is_idempotent_and_conflicts_on_reused_request(registry):
    service, _ = registry
    candidate = service.ingest_report(serial_report()).candidates[0]
    request = CandidateDecisionUpdate(
        decision="accepted",
        note="현장 장비 확인 완료",
        request_ref=mutation_ref("b"),
    )

    accepted = service.update_decision(candidate.candidate_id, request)
    replay = service.update_decision(candidate.candidate_id, request)

    assert accepted.decision == "accepted"
    assert replay.decision == "accepted"
    conflicting = request.model_copy(
        update={
            "decision": "ignored",
            "request_ref": CandidateMutationRef(
                request_id=request.request_ref.request_id,
                payload_hash="9" * 64,
            ),
        }
    )
    with pytest.raises(ControllerConflict, match="reused"):
        service.update_decision(candidate.candidate_id, conflicting)


def test_manual_mqtt_candidate_rejects_secrets_and_can_be_deleted(registry):
    service, _ = registry
    secret_candidate = ManualCandidateCreate(
        candidate=ManualCandidateInput(
            node_name="etri-dev0001-jetorn",
            protocol="mqtt",
            transport="mqtts",
            display_name="Line MQTT sensor",
            properties={
                "Broker": "mqtts://broker.example:8883",
                "Topic": "factory/line-1/temperature",
                "Password": "do-not-store",
            },
        ),
        request_ref=mutation_ref("c"),
    )
    with pytest.raises(ControllerValidationError, match="secrets"):
        service.create_manual(secret_candidate)

    request = secret_candidate.model_copy(
        update={
            "candidate": secret_candidate.candidate.model_copy(
                update={
                    "properties": {
                        "Broker": "mqtts://broker.example:8883",
                        "Topic": "factory/line-1/temperature",
                    }
                }
            )
        }
    )
    created = service.create_manual(request)
    deleted = service.delete_candidate(
        created.candidate_id,
        CandidateDeleteRequest(request_ref=mutation_ref("d")),
    )

    assert created.source == "manual"
    assert created.presence == "declared"
    assert created.package_state == "verification-required"
    assert deleted.candidate_id == created.candidate_id
    assert service.list_inventory().candidates == []


def test_manual_modbus_simulator_candidate_is_normalized_and_exactly_matched():
    kube = FakeKubernetesGateway()
    service = DeviceCandidateRegistry(
        RuntimeTemplateCatalog.load(CATALOG_PATH),
        kube,
        candidate_limit=10,
        device_catalog=DeviceBindingCatalog.load(DEVICE_CATALOG_PATH),
    )

    created = service.create_manual(
        ManualCandidateCreate(
            candidate=ManualCandidateInput(
                node_name="etri-dev0001-jetorn",
                protocol="modbus",
                transport="modbus-tcp",
                display_name="EdgeX Modbus TCP simulator",
                properties={
                    "Mode": "TCP",
                    "Host": (
                        "edge-modbus-simulator.edgex-edge.svc.cluster.local"
                    ),
                    "Port": "1502",
                    "UnitID": "1",
                },
            ),
            request_ref=mutation_ref("8"),
        )
    )

    assert created.state == "PENDING_APPROVAL"
    assert created.registration_ready is True
    assert created.matched_adapter_id == "modbus"
    assert created.matched_hardware_binding_id == (
        "jetson-modbus-tcp-simulator-001"
    )
    assert created.properties == {
        "Mode": "tcp",
        "Host": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
        "Port": 1502,
        "UnitID": 1,
    }


def test_manual_candidate_identity_ignores_display_metadata_and_rejects_url_credentials(
    registry,
):
    service, _ = registry
    base = ManualCandidateInput(
        node_name="etri-dev0001-jetorn",
        protocol="mqtt",
        transport="mqtts",
        display_name="Line MQTT sensor",
        properties={
            "Broker": "mqtts://broker.example:8883",
            "Topic": "factory/line-1/temperature",
        },
        note="first review",
    )
    created = service.create_manual(
        ManualCandidateCreate(
            candidate=base,
            request_ref=mutation_ref("1"),
        )
    )

    with pytest.raises(ControllerConflict, match="different request"):
        service.create_manual(
            ManualCandidateCreate(
                candidate=base.model_copy(
                    update={
                        "display_name": "Renamed sensor",
                        "note": "same endpoint",
                    }
                ),
                request_ref=mutation_ref("2"),
            )
        )

    assert len(service.list_inventory().candidates) == 1
    assert service.list_inventory().candidates[0].candidate_id == created.candidate_id

    with pytest.raises(ControllerValidationError, match="embedded credentials"):
        service.create_manual(
            ManualCandidateCreate(
                candidate=base.model_copy(
                    update={
                        "properties": {
                            "Broker": "mqtts://user:password@broker.example:8883",
                            "Topic": "factory/line-1/temperature",
                        }
                    }
                ),
                request_ref=mutation_ref("3"),
            )
        )


def test_delete_of_scanned_candidate_preserves_ignore_tombstone(registry):
    service, _ = registry
    candidate = service.ingest_report(serial_report()).candidates[0]

    deleted = service.delete_candidate(
        candidate.candidate_id,
        CandidateDeleteRequest(request_ref=mutation_ref("e")),
    )
    refreshed = service.ingest_report(serial_report()).candidates[0]

    assert deleted.decision == "ignored"
    assert refreshed.decision == "ignored"
    assert "삭제 대신 무시" in refreshed.decision_note


def test_registered_candidate_cannot_be_deleted_without_decommission(registry):
    service, _ = registry
    candidate = service.ingest_report(serial_report()).candidates[0]
    service.transition(
        candidate.candidate_id,
        "IDENTIFIED",
        reason="test identity",
        actor="test",
    )
    service.transition(
        candidate.candidate_id,
        "PENDING_APPROVAL",
        reason="test approval gate",
        actor="test",
    )
    service.transition(
        candidate.candidate_id,
        "APPROVED",
        reason="test operator approval",
        actor="test",
    )

    with pytest.raises(ControllerConflict, match="decommission"):
        service.delete_candidate(
            candidate.candidate_id,
            CandidateDeleteRequest(request_ref=mutation_ref("d")),
        )
