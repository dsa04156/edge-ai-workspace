from pathlib import Path

from app.catalog import RuntimeTemplateCatalog
from app.models import RuntimeObservation, RuntimePlanRequest
from app.planner import RuntimePlanner


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "runtime_templates.json"
)


def planner() -> RuntimePlanner:
    return RuntimePlanner(RuntimeTemplateCatalog.load(CATALOG_PATH))


def request(**overrides) -> RuntimePlanRequest:
    payload = {
        "adapterId": "serial-jetson",
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-arduino-serial-001",
        "mode": "auto",
    }
    payload.update(overrides)
    return RuntimePlanRequest.model_validate(payload)


def external_serial(*, phase="SERVICE_READY") -> RuntimeObservation:
    return RuntimeObservation(
        runtime_name="device-serial-jetson",
        adapter_id="serial-jetson",
        template_id="serial-device-service-v1",
        service_name="device-serial-jetson",
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-arduino-serial-001",
        management_mode="external",
        management_owner="argocd",
        verification_state="hardware-verified",
        phase=phase,
        consumers=6,
        mutable=False,
    )


def test_auto_reuses_ready_runtime_on_exact_node_and_binding():
    plan = planner().plan(request(), [external_serial()])

    assert plan.action == "REUSE"
    assert plan.allowed is True
    assert plan.runtime_name == "device-serial-jetson"
    assert plan.service_name == "device-serial-jetson"
    assert plan.management_mode == "external"
    assert plan.reasons == []
    assert len(plan.plan_hash) == 64


def test_auto_reuses_one_protocol_runtime_for_a_second_approved_binding():
    runtime_planner = planner()
    template = runtime_planner.catalog.require("serial-device-service-v1")
    second = template.hardware_bindings[0].model_copy(
        update={
            "binding_id": "jetson-arduino-serial-002",
            "display_name": "Jetson Arduino USB Serial 2",
            "host_device_path": "/dev/serial/by-id/example-002",
            "container_device_path": "/dev/arduino-002",
        }
    )
    template.hardware_bindings.append(second)
    runtime = external_serial().model_copy(
        update={
            "hardware_binding_ids": [
                "jetson-arduino-serial-001",
                "jetson-arduino-serial-002",
            ],
        }
    )

    plan = runtime_planner.plan(
        request(hardwareBindingId="jetson-arduino-serial-002"),
        [runtime],
    )

    assert plan.action == "REUSE"
    assert plan.runtime_name == "device-serial-jetson"
    assert plan.hardware_binding_id == "jetson-arduino-serial-002"


def test_explicit_deploy_cannot_replace_existing_binding():
    plan = planner().plan(request(mode="deploy"), [external_serial()])

    assert plan.action == "BLOCKED"
    assert plan.allowed is False
    assert [item.code for item in plan.reasons] == ["hardware_binding_in_use"]


def test_unready_existing_runtime_blocks_duplicate_deploy():
    plan = planner().plan(request(), [external_serial(phase="DEPLOYING")])

    assert plan.action == "BLOCKED"
    assert [item.code for item in plan.reasons] == ["runtime_not_ready"]


def test_explicit_reuse_blocks_when_no_runtime_exists():
    plan = planner().plan(request(mode="reuse"), [])

    assert plan.action == "BLOCKED"
    assert [item.code for item in plan.reasons] == ["runtime_not_found"]


def test_auto_blocks_when_matching_template_is_not_yet_deployable():
    plan = planner().plan(request(), [])

    assert plan.action == "BLOCKED"
    assert [item.code for item in plan.reasons] == ["template_not_deployable"]
    assert plan.verification_state == "hardware-verified"


def test_unverified_protocol_never_plans_deployment():
    modbus = RuntimePlanRequest(
        adapter_id="modbus",
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="modbus-line-a",
        mode="auto",
    )

    plan = planner().plan(modbus, [])

    assert plan.action == "BLOCKED"
    assert [item.code for item in plan.reasons] == ["template_unverified"]
    assert plan.verification_state == "unverified"


def test_wrong_node_binding_pair_is_blocked():
    plan = planner().plan(
        request(targetNode="etri-dev0003-raspi5"),
        [],
    )

    assert plan.action == "BLOCKED"
    assert [item.code for item in plan.reasons] == ["node_not_allowed"]


def test_not_ready_target_node_blocks_reuse_or_deploy_plan():
    plan = planner().plan(
        request(),
        [external_serial()],
        target_node_ready=False,
    )

    assert plan.action == "BLOCKED"
    assert [item.code for item in plan.reasons] == ["node_not_ready"]
