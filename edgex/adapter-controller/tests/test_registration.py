from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.auth import AllowAllMockProvider, AuthDecision
from app.catalog import RuntimeTemplateCatalog
from app.device_catalog import DeviceBindingCatalog
from app.discovery import DeviceCandidateRegistry
from app.discovery_models import (
    CandidateApprovalRequest,
    CandidateDecommissionRequest,
    CandidateDecisionUpdate,
    CandidateMutationRef,
    CandidateRetryRequest,
    DiscoveryObservation,
    ManualCandidateCreate,
    ManualCandidateInput,
    NodeDiscoveryReport,
)
from app.discovery_store import SQLiteDiscoveryStore
from app.models import RuntimeObservation, RuntimePlan
from app.registration import RegistrationCoordinator
from app.service import AdapterControllerService

from fakes import FakeKubernetesGateway


BASE = Path(__file__).resolve().parents[1]
SERIAL_IMAGE = (
    "192.168.0.56:5000/edgex-device-serial@"
    "sha256:215dc73e86c7e9e69938b4e0b1f991947705083f61ca851758c1fb259c883eda"
)
MODBUS_IMAGE = (
    "docker.io/edgexfoundry/device-modbus:4.0.2@"
    "sha256:db8aeb83bae186c93929e33b82b47eb490289265babf7247a5b37405d73221f9"
)


class FakeRuntimeService:
    def __init__(
        self,
        phase: str = "SERVICE_READY",
        image: str = SERIAL_IMAGE,
    ) -> None:
        self.phase = phase
        self.image = image
        self.retired: list[str] = []

    def plan(self, request):
        return RuntimePlan(
            action="REUSE",
            allowed=True,
            adapter_id=request.adapter_id,
            template_id="serial-device-service-v1",
            runtime_name="device-serial-jetson",
            service_name="device-serial-jetson",
            target_node=request.target_node,
            hardware_binding_id=request.hardware_binding_id,
            management_mode="external",
            verification_state="hardware-verified",
            reasons=[],
            plan_hash="a" * 64,
        )

    def list_runtimes(self):
        return [
            RuntimeObservation(
                runtime_name="device-serial-jetson",
                adapter_id="serial-jetson",
                template_id="serial-device-service-v1",
                service_name="device-serial-jetson",
                target_node="etri-dev0001-jetorn",
                hardware_binding_id="jetson-arduino-serial-001",
                hardware_binding_ids=["jetson-arduino-serial-001"],
                management_mode="external",
                management_owner="argocd",
                verification_state="hardware-verified",
                phase=self.phase,
                consumers=0,
                image=self.image,
            )
        ]

    def retire_runtime(self, name, request):
        self.retired.append(name)


class FakeDeployRuntimeService(FakeRuntimeService):
    def plan(self, request):
        return RuntimePlan(
            action="DEPLOY",
            allowed=True,
            adapter_id=request.adapter_id,
            template_id="serial-device-service-v1",
            runtime_name="managed-serial-runtime",
            service_name="device-serial-jetson",
            target_node=request.target_node,
            hardware_binding_id=request.hardware_binding_id,
            management_mode="controller",
            verification_state="hardware-verified",
            reasons=[],
            plan_hash="b" * 64,
        )

    def apply_runtime(self, name, request):
        return RuntimeObservation(
            runtime_name=name,
            adapter_id="serial-jetson",
            template_id="serial-device-service-v1",
            service_name="device-serial-jetson",
            target_node="etri-dev0001-jetorn",
            hardware_binding_id="jetson-arduino-serial-001",
            hardware_binding_ids=["jetson-arduino-serial-001"],
            management_mode="controller",
            management_owner="controller",
            verification_state="hardware-verified",
            phase=self.phase,
            consumers=0,
            image=self.image,
        )


class FakeModbusRuntimeService:
    def __init__(self) -> None:
        self.retired: list[str] = []

    def plan(self, request):
        return RuntimePlan(
            action="DEPLOY",
            allowed=True,
            adapter_id="modbus",
            template_id="modbus-device-service-v1",
            runtime_name="adapter-modbus-1234567890",
            service_name="device-modbus_1234567890",
            target_node=request.target_node,
            hardware_binding_id=request.hardware_binding_id,
            management_mode="controller",
            verification_state="template-verified",
            reasons=[],
            plan_hash="e" * 64,
        )

    def apply_runtime(self, name, request):
        return RuntimeObservation(
            runtime_name=name,
            adapter_id="modbus",
            template_id="modbus-device-service-v1",
            service_name="device-modbus_1234567890",
            target_node="etri-dev0001-jetorn",
            hardware_binding_id="jetson-modbus-tcp-simulator-001",
            hardware_binding_ids=["jetson-modbus-tcp-simulator-001"],
            management_mode="controller",
            management_owner="controller",
            verification_state="template-verified",
            phase="SERVICE_READY",
            consumers=0,
            image=MODBUS_IMAGE,
        )

    def retire_runtime(self, name, request):
        self.retired.append(name)


class FakeDelayedModbusRuntimeService(FakeModbusRuntimeService):
    def __init__(self) -> None:
        super().__init__()
        self.plan_calls = 0
        self.apply_calls = 0
        self.list_calls = 0

    def plan(self, request):
        self.plan_calls += 1
        if self.plan_calls > 1:
            raise AssertionError("an already requested Runtime was replanned")
        return super().plan(request)

    def apply_runtime(self, name, request):
        self.apply_calls += 1
        runtime = super().apply_runtime(name, request)
        return runtime.model_copy(update={"phase": "DEPLOYING"})

    def list_runtimes(self):
        self.list_calls += 1
        runtime = super().apply_runtime(
            "adapter-modbus-1234567890",
            None,
        )
        phase = "DEPLOYING" if self.list_calls == 1 else "SERVICE_READY"
        return [runtime.model_copy(update={"phase": phase})]


class FakeEdgeX:
    def __init__(
        self,
        *,
        event_received: bool = True,
        profile_failure: bool = False,
        profile_created: bool = True,
        device_created: bool = True,
        operating_state_failure: bool = False,
    ) -> None:
        self.event_received = event_received
        self.profile_failure = profile_failure
        self.profile_created = profile_created
        self.device_created = device_created
        self.operating_state_failure = operating_state_failure
        self.profiles: list[str] = []
        self.devices: list[dict] = []
        self.operating_up_devices: list[str] = []
        self.deleted_devices: list[str] = []
        self.deleted_profiles: list[str] = []

    def ensure_profile(self, profile):
        if self.profile_failure:
            raise RuntimeError("profile rejected")
        self.profiles.append(profile["name"])
        return self.profile_created

    def ensure_device(self, device):
        self.devices.append(device)
        return self.device_created

    def first_event_received(self, device_name, *, not_before_ns=None):
        return self.event_received

    def ensure_device_operating_up(self, device_name):
        if self.operating_state_failure:
            raise RuntimeError("metadata state update unavailable")
        self.operating_up_devices.append(device_name)
        return True

    def delete_owned_device(self, name, *, candidate_id):
        self.deleted_devices.append(name)

    def delete_unused_profile(self, name):
        self.deleted_profiles.append(name)


class DenyAuth:
    def approve(self, candidate, *, actor, reason):
        return AuthDecision(
            approved=False,
            state="denied",
            reason="hardware certificate was rejected",
            error_code="AUTH_DENIED",
        )


class FlakyAuth:
    def __init__(self) -> None:
        self.calls = 0

    def approve(self, candidate, *, actor, reason):
        self.calls += 1
        if self.calls == 1:
            return AuthDecision(
                approved=False,
                state="unavailable",
                reason="approval service was temporarily unavailable",
                error_code="AUTH_UNAVAILABLE",
            )
        return AuthDecision(
            approved=True,
            state="approved",
            reason="approval service recovered",
        )


def report() -> NodeDiscoveryReport:
    return NodeDiscoveryReport(
        node_name="etri-dev0001-jetorn",
        agent_id="discovery/test",
        observed_at=datetime.now(timezone.utc),
        candidates=[
            DiscoveryObservation(
                hardware_key="arduino-by-id",
                hardware_id="75035303230351E0D171",
                protocol="serial",
                transport="usb-serial",
                display_name="Arduino",
                device_path=(
                    "/dev/serial/by-id/"
                    "usb-Arduino__www.arduino.cc__0043_"
                    "75035303230351E0D171-if00"
                ),
                vendor="Arduino",
                properties={"VendorID": "2341", "ProductID": "0043"},
                evidence={"stablePath": "udev-by-id"},
            )
        ],
    )


def approval() -> CandidateApprovalRequest:
    return CandidateApprovalRequest(
        actor="operator-1",
        reason="physical label and installation record verified",
        request_ref=CandidateMutationRef(
            request_id="1" * 64,
            payload_hash="2" * 64,
        ),
    )


def decommission() -> CandidateDecommissionRequest:
    return CandidateDecommissionRequest(
        actor="operator-1",
        reason="development fixture cleanup",
        request_ref=CandidateMutationRef(
            request_id="5" * 64,
            payload_hash="6" * 64,
        ),
    )


def components(tmp_path, *, auth=None, edge_x=None, runtime=None, timeout=60):
    kube = FakeKubernetesGateway(target_node_ready=True)
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    runtime_catalog = RuntimeTemplateCatalog.load(
        BASE / "config" / "runtime_templates.json"
    )
    device_catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    registry = DeviceCandidateRegistry(
        runtime_catalog,
        kube,
        store=store,
        device_catalog=device_catalog,
    )
    candidate = registry.ingest_report(report()).candidates[0]
    coordinator = RegistrationCoordinator(
        registry=registry,
        store=store,
        device_catalog=device_catalog,
        auth_provider=auth or AllowAllMockProvider(),
        edge_x=edge_x or FakeEdgeX(),
        kube=kube,
        runtime_service=runtime or FakeRuntimeService(),
        event_timeout_seconds=timeout,
    )
    return registry, store, coordinator, candidate


def test_approval_to_first_event_is_idempotent_end_to_end(tmp_path):
    registry, store, coordinator, candidate = components(tmp_path)

    approved = coordinator.approve(candidate.candidate_id, approval())
    replay = coordinator.approve(candidate.candidate_id, approval())
    assert approved.state == replay.state == "APPROVED"
    assert coordinator.edge_x.devices == []

    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)
    registration = coordinator.reconcile_candidate(candidate.candidate_id)

    assert registry.get_candidate(candidate.candidate_id).state == "EVENT_CONFIRMED"
    assert registration.status == "EVENT_CONFIRMED"
    assert len(coordinator.edge_x.profiles) == 1
    assert len(coordinator.edge_x.devices) == 1
    assert coordinator.edge_x.operating_up_devices == [
        registration.device_name
    ]
    assert coordinator.edge_x.devices[0]["tags"]["controllerCandidateId"] == (
        candidate.candidate_id
    )


def test_decommission_removes_only_saga_owned_resources_and_hides_candidate(
    tmp_path,
):
    edge_x = FakeEdgeX()
    runtime = FakeDeployRuntimeService()
    registry, _, coordinator, candidate = components(
        tmp_path,
        edge_x=edge_x,
        runtime=runtime,
    )
    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)
    completed = coordinator.reconcile_candidate(candidate.candidate_id)

    removed = coordinator.decommission(
        candidate.candidate_id,
        decommission(),
    )
    replay = coordinator.decommission(
        candidate.candidate_id,
        decommission(),
    )

    assert completed.status == "EVENT_CONFIRMED"
    assert removed.candidate_id == replay.candidate_id == candidate.candidate_id
    assert edge_x.deleted_devices == [completed.device_name]
    assert edge_x.deleted_profiles == [completed.profile_name]
    assert runtime.retired == [completed.runtime_name]
    assert all(
        item.candidate_id != candidate.candidate_id
        for item in registry.list_inventory().candidates
    )


def test_first_event_waits_for_operating_state_readback_then_retries(tmp_path):
    edge_x = FakeEdgeX(operating_state_failure=True)
    registry, _, coordinator, candidate = components(
        tmp_path,
        edge_x=edge_x,
    )

    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)
    waiting = coordinator.reconcile_candidate(candidate.candidate_id)

    assert waiting.status == "METADATA_REGISTERED"
    assert waiting.step == "SETTING_DEVICE_UP"
    assert waiting.last_error_code == "DEVICE_STATE_UPDATE_PENDING"
    assert registry.get_candidate(candidate.candidate_id).state == (
        "METADATA_REGISTERED"
    )

    edge_x.operating_state_failure = False
    completed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert completed.status == "EVENT_CONFIRMED"
    assert edge_x.operating_up_devices == [completed.device_name]


def test_device_name_keeps_a_hash_suffix_when_hardware_slugs_share_a_prefix(
    tmp_path,
):
    device_catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    binding = device_catalog.get("jetson-arduino-multisensor-v1")
    common = "same-very-long-hardware-identity-prefix-" * 3

    first = RegistrationCoordinator._device_name(
        SimpleNamespace(
            hardware_id=f"{common}a",
            identity_hash="1" * 64,
        ),
        binding,
    )
    second = RegistrationCoordinator._device_name(
        SimpleNamespace(
            hardware_id=f"{common}b",
            identity_hash="2" * 64,
        ),
        binding,
    )

    assert first != second
    assert first.endswith("-" + "1" * 10)
    assert second.endswith("-" + "2" * 10)
    assert len(first) <= 63
    assert len(second) <= 63


def test_modbus_device_uses_runtime_service_protocol_mapping_and_auto_event(
    tmp_path,
):
    device_catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    binding = device_catalog.get("jetson-modbus-tcp-simulator-v1")
    candidate = SimpleNamespace(
        protocol="modbus",
        model="edgeai-modbus-tcp-simulator-v1",
        node_name="etri-dev0001-jetorn",
        candidate_id="candidate-" + "a" * 64,
        hardware_id="modbus-simulator-001",
        properties={
            "Mode": "tcp",
            "Host": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
            "Port": 1502,
            "UnitID": 1,
        },
    )
    registration = SimpleNamespace(
        device_name="modbus-sim-001",
        service_name="adapter-modbus-1234567890",
    )

    document = RegistrationCoordinator._device_document(
        candidate,
        binding,
        registration,
    )

    assert document["serviceName"] == "adapter-modbus-1234567890"
    assert document["protocols"] == {
        "modbus-tcp": {
            "Address": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
            "Port": 1502,
            "UnitID": 1,
            "Timeout": 5,
            "IdleTimeout": 5,
        }
    }
    assert document["autoEvents"] == [
        {
            "sourceName": "temperature",
            "interval": "1s",
            "onChange": False,
        }
    ]


def test_manual_modbus_candidate_runs_approval_to_first_event_saga(tmp_path):
    kube = FakeKubernetesGateway(target_node_ready=True)
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    runtime_catalog = RuntimeTemplateCatalog.load(
        BASE / "config" / "runtime_templates.json"
    )
    device_catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    registry = DeviceCandidateRegistry(
        runtime_catalog,
        kube,
        store=store,
        device_catalog=device_catalog,
    )
    candidate = registry.create_manual(
        ManualCandidateCreate(
            candidate=ManualCandidateInput(
                node_name="etri-dev0001-jetorn",
                protocol="modbus",
                transport="modbus-tcp",
                display_name="EdgeX Modbus TCP simulator",
                properties={
                    "Mode": "tcp",
                    "Host": (
                        "edge-modbus-simulator.edgex-edge.svc.cluster.local"
                    ),
                    "Port": 1502,
                    "UnitID": 1,
                },
            ),
            request_ref=CandidateMutationRef(
                request_id="4" * 64,
                payload_hash="5" * 64,
            ),
        )
    )
    edge_x = FakeEdgeX(event_received=True)
    coordinator = RegistrationCoordinator(
        registry=registry,
        store=store,
        device_catalog=device_catalog,
        auth_provider=AllowAllMockProvider(),
        edge_x=edge_x,
        kube=kube,
        runtime_service=FakeModbusRuntimeService(),
        event_timeout_seconds=10,
    )

    assert candidate.state == "PENDING_APPROVAL"
    controller = AdapterControllerService(
        runtime_catalog,
        kube,
        None,
        None,
        namespace="edgex-edge",
        candidate_registry=registry,
        registration_coordinator=coordinator,
        device_catalog=device_catalog,
    )
    completed = controller.update_candidate_decision(
        candidate.candidate_id,
        CandidateDecisionUpdate(
            decision="accepted",
            note="development simulator endpoint verified",
            request_ref=CandidateMutationRef(
                request_id="6" * 64,
                payload_hash="7" * 64,
            ),
        ),
    )
    registration = coordinator.get_registration(candidate.candidate_id)

    assert completed.state == "EVENT_CONFIRMED"
    assert registration.status == "EVENT_CONFIRMED"
    assert registry.get_candidate(candidate.candidate_id).state == (
        "EVENT_CONFIRMED"
    )
    assert edge_x.profiles == ["edgeai-modbus-temperature-v1"]
    assert edge_x.devices[0]["serviceName"] == "device-modbus_1234567890"
    assert edge_x.devices[0]["protocols"]["modbus-tcp"]["Port"] == 1502
    assert edge_x.devices[0]["autoEvents"][0]["sourceName"] == "temperature"


def test_created_runtime_is_observed_until_ready_without_replanning(tmp_path):
    kube = FakeKubernetesGateway(target_node_ready=True)
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    runtime_catalog = RuntimeTemplateCatalog.load(
        BASE / "config" / "runtime_templates.json"
    )
    device_catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    registry = DeviceCandidateRegistry(
        runtime_catalog,
        kube,
        store=store,
        device_catalog=device_catalog,
    )
    candidate = registry.create_manual(
        ManualCandidateCreate(
            candidate=ManualCandidateInput(
                node_name="etri-dev0001-jetorn",
                protocol="modbus",
                transport="modbus-tcp",
                display_name="EdgeX Modbus TCP simulator",
                properties={
                    "Mode": "tcp",
                    "Host": (
                        "edge-modbus-simulator.edgex-edge.svc.cluster.local"
                    ),
                    "Port": 1502,
                    "UnitID": 1,
                },
            ),
            request_ref=CandidateMutationRef(
                request_id="8" * 64,
                payload_hash="9" * 64,
            ),
        )
    )
    runtime = FakeDelayedModbusRuntimeService()
    coordinator = RegistrationCoordinator(
        registry=registry,
        store=store,
        device_catalog=device_catalog,
        auth_provider=AllowAllMockProvider(),
        edge_x=FakeEdgeX(event_received=True),
        kube=kube,
        runtime_service=runtime,
        event_timeout_seconds=10,
    )
    controller = AdapterControllerService(
        runtime_catalog,
        kube,
        None,
        None,
        namespace="edgex-edge",
        candidate_registry=registry,
        registration_coordinator=coordinator,
        device_catalog=device_catalog,
    )
    started = controller.update_candidate_decision(
        candidate.candidate_id,
        CandidateDecisionUpdate(
            decision="accepted",
            note="development simulator endpoint verified",
            request_ref=CandidateMutationRef(
                request_id="a" * 64,
                payload_hash="b" * 64,
            ),
        ),
    )

    first = coordinator.get_registration(candidate.candidate_id)
    waiting = coordinator.reconcile_candidate(candidate.candidate_id)
    ready = coordinator.reconcile_candidate(candidate.candidate_id)

    assert started.state == "APPROVED"
    assert first.step == "RUNTIME_REQUESTED"
    assert waiting.step == "WAITING_FOR_RUNTIME"
    assert ready.status == "SERVICE_READY"
    assert runtime.plan_calls == 1
    assert runtime.apply_calls == 1
    assert runtime.list_calls == 2


def test_auth_denial_blocks_before_edgex_registration(tmp_path):
    registry, _, coordinator, candidate = components(
        tmp_path,
        auth=DenyAuth(),
    )

    blocked = coordinator.approve(candidate.candidate_id, approval())

    assert blocked.state == "BLOCKED"
    assert blocked.auth_state == "denied"
    assert coordinator.edge_x.devices == []
    assert registry.get_candidate(candidate.candidate_id).failure_reason

    observed_again = registry.ingest_report(report()).candidates[0]
    assert observed_again.state == "BLOCKED"
    assert observed_again.auth_state == "denied"


def test_auth_unavailable_requires_a_new_explicit_approval_request(tmp_path):
    auth = FlakyAuth()
    registry, _, coordinator, candidate = components(
        tmp_path,
        auth=auth,
    )

    blocked = coordinator.approve(candidate.candidate_id, approval())
    retried = coordinator.approve(
        candidate.candidate_id,
        CandidateApprovalRequest(
            actor="operator-1",
            reason="external approval service recovered",
            request_ref=CandidateMutationRef(
                request_id="7" * 64,
                payload_hash="8" * 64,
            ),
        ),
    )

    assert blocked.state == "BLOCKED"
    assert blocked.auth_state == "unavailable"
    assert retried.state == "APPROVED"
    assert retried.auth_state == "approved"
    assert auth.calls == 2
    assert registry.get_candidate(candidate.candidate_id).state == "APPROVED"


def test_first_event_timeout_rolls_back_only_saga_created_metadata(tmp_path):
    edge_x = FakeEdgeX(event_received=False)
    registry, _, coordinator, candidate = components(
        tmp_path,
        edge_x=edge_x,
        timeout=0,
    )
    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)

    failed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert failed.status == "FAILED"
    assert failed.last_error_code == "FIRST_EVENT_TIMEOUT"
    assert edge_x.deleted_devices
    assert edge_x.deleted_profiles == ["arduino-multisensor-v1"]
    assert registry.get_candidate(candidate.candidate_id).state == "FAILED"


def test_device_service_startup_failure_stops_before_metadata(tmp_path):
    registry, _, coordinator, candidate = components(
        tmp_path,
        runtime=FakeRuntimeService(phase="FAILED"),
    )
    coordinator.approve(candidate.candidate_id, approval())

    failed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert failed.status == "FAILED"
    assert failed.last_error_code == "RUNTIME_START_FAILED"
    assert coordinator.edge_x.profiles == []
    assert registry.get_candidate(candidate.candidate_id).state == "FAILED"


def test_runtime_image_must_match_allowlisted_digest(tmp_path):
    runtime = FakeRuntimeService(
        image=(
            "192.168.0.56:5000/edgex-device-serial@"
            f"sha256:{'f' * 64}"
        )
    )
    registry, _, coordinator, candidate = components(
        tmp_path,
        runtime=runtime,
    )
    coordinator.approve(candidate.candidate_id, approval())

    failed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert failed.status == "FAILED"
    assert failed.last_error_code == "RUNTIME_IMAGE_NOT_VERIFIED"
    assert coordinator.edge_x.profiles == []
    assert runtime.retired == []
    assert registry.get_candidate(candidate.candidate_id).state == "FAILED"


def test_runtime_image_failure_rolls_back_only_new_controller_runtime(tmp_path):
    runtime = FakeDeployRuntimeService(
        image=(
            "192.168.0.56:5000/edgex-device-serial@"
            f"sha256:{'f' * 64}"
        )
    )
    registry, _, coordinator, candidate = components(
        tmp_path,
        runtime=runtime,
    )
    coordinator.approve(candidate.candidate_id, approval())

    failed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert failed.status == "FAILED"
    assert failed.last_error_code == "RUNTIME_IMAGE_NOT_VERIFIED"
    assert runtime.retired == ["managed-serial-runtime"]
    assert failed.created_runtime is False
    assert registry.get_candidate(candidate.candidate_id).state == "FAILED"


def test_profile_failure_is_persisted_without_creating_device(tmp_path):
    edge_x = FakeEdgeX(profile_failure=True)
    registry, _, coordinator, candidate = components(
        tmp_path,
        edge_x=edge_x,
    )
    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)

    failed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert failed.status == "FAILED"
    assert failed.last_error_code == "METADATA_REGISTRATION_FAILED"
    assert edge_x.devices == []
    assert registry.get_candidate(candidate.candidate_id).state == "FAILED"


def test_retry_after_event_timeout_can_complete(tmp_path):
    edge_x = FakeEdgeX(event_received=False)
    registry, _, coordinator, candidate = components(
        tmp_path,
        edge_x=edge_x,
        timeout=0,
    )
    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)
    edge_x.event_received = True
    retry = CandidateRetryRequest(
        actor="operator-1",
        reason="Device Service issue was repaired",
        request_ref=CandidateMutationRef(
            request_id="3" * 64,
            payload_hash="4" * 64,
        ),
    )

    retried = coordinator.retry(
        candidate.candidate_id,
        retry,
    )
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)
    completed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert retried.state == "APPROVED"
    assert completed.status == "EVENT_CONFIRMED"
    assert completed.attempt == 2
    assert registry.get_candidate(candidate.candidate_id).retry_count == 1


def test_timeout_never_rolls_back_preexisting_profile_device_or_runtime(
    tmp_path,
):
    edge_x = FakeEdgeX(
        event_received=False,
        profile_created=False,
        device_created=False,
    )
    runtime = FakeRuntimeService()
    registry, _, coordinator, candidate = components(
        tmp_path,
        edge_x=edge_x,
        runtime=runtime,
        timeout=0,
    )
    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)
    coordinator.reconcile_candidate(candidate.candidate_id)

    failed = coordinator.reconcile_candidate(candidate.candidate_id)

    assert failed.status == "FAILED"
    assert edge_x.deleted_devices == []
    assert edge_x.deleted_profiles == []
    assert runtime.retired == []


def test_controller_restart_resumes_from_persisted_saga_step(tmp_path):
    registry, store, coordinator, candidate = components(tmp_path)
    coordinator.approve(candidate.candidate_id, approval())
    coordinator.reconcile_candidate(candidate.candidate_id)
    assert registry.get_candidate(candidate.candidate_id).state == "SERVICE_READY"
    store.close()

    kube = FakeKubernetesGateway(target_node_ready=True)
    reopened = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    runtime_catalog = RuntimeTemplateCatalog.load(
        BASE / "config" / "runtime_templates.json"
    )
    device_catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    restored_registry = DeviceCandidateRegistry(
        runtime_catalog,
        kube,
        store=reopened,
        device_catalog=device_catalog,
    )
    restored = RegistrationCoordinator(
        registry=restored_registry,
        store=reopened,
        device_catalog=device_catalog,
        auth_provider=AllowAllMockProvider(),
        edge_x=FakeEdgeX(),
        kube=kube,
        runtime_service=FakeRuntimeService(),
    )

    restored.reconcile_candidate(candidate.candidate_id)
    final = restored.reconcile_candidate(candidate.candidate_id)

    assert final.status == "EVENT_CONFIRMED"
    assert (
        restored_registry.get_candidate(candidate.candidate_id).state
        == "EVENT_CONFIRMED"
    )
