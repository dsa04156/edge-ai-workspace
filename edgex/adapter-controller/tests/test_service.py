import pytest

from app.api import ControllerConflict, ControllerNotFound, ControllerValidationError
from app.catalog import RuntimeTemplateCatalog
from app.models import (
    RuntimeActionRequest,
    RuntimeApplyRequest,
    RuntimeCatalogDocument,
    RuntimeCreateRequest,
    RuntimePlanRequest,
)
from app.reconciler import RuntimeReconciler
from app.service import AdapterControllerService

from fakes import FakeEdgeXServiceProbe, FakeKubernetesGateway


DIGEST_IMAGE = "registry.example/device-service@sha256:" + ("a" * 64)


def catalog(*, deployment_enabled=True) -> RuntimeTemplateCatalog:
    return RuntimeTemplateCatalog(
        RuntimeCatalogDocument.model_validate(
            {
                "version": 1,
                "namespace": "edgex-edge",
                "templates": [
                    {
                        "templateId": "managed-serial-v1",
                        "adapterId": "managed-serial",
                        "displayName": "Managed Serial",
                        "protocolName": "serial",
                        "verificationState": "template-verified",
                        "deploymentEnabled": deployment_enabled,
                        "image": DIGEST_IMAGE,
                        "servicePort": 59940,
                        "hardwareBindings": [
                            {
                                "bindingId": "managed-serial-binding",
                                "displayName": "Managed binding",
                                "nodeName": "edge-node-02",
                                "hostDevicePath": "/dev/serial/by-id/managed-02",
                                "containerDevicePath": "/dev/serial-02",
                                "deviceType": "CharDevice",
                                "requiresPrivileged": True,
                            }
                        ],
                    }
                ],
            }
        )
    )


def service(*, deployment_ready=True, edgex_ready=True, consumers=0):
    kube = FakeKubernetesGateway(deployment_ready=deployment_ready)
    probe = FakeEdgeXServiceProbe(ready=edgex_ready, consumers=consumers)
    controller = AdapterControllerService(
        catalog(),
        kube,
        probe,
        RuntimeReconciler(kube, probe, namespace="edgex-edge"),
        namespace="edgex-edge",
    )
    return controller, kube, probe


def plan_request():
    return RuntimePlanRequest(
        adapter_id="managed-serial",
        target_node="edge-node-02",
        hardware_binding_id="managed-serial-binding",
        mode="auto",
    )


def create_request(plan_hash):
    return RuntimeCreateRequest(
        plan=plan_request(),
        request_ref=RuntimeApplyRequest(
            request_id="b" * 64,
            payload_hash="c" * 64,
            plan_hash=plan_hash,
        ),
    )


def action_request(*, request_id="d" * 64, payload_hash="e" * 64):
    return RuntimeActionRequest(
        request_id=request_id,
        payload_hash=payload_hash,
    )


def create_managed_runtime(controller):
    plan = controller.plan(plan_request())
    return controller.apply_runtime(
        plan.runtime_name,
        create_request(plan.plan_hash),
    )


def test_service_plans_and_creates_idempotent_controller_runtime():
    controller, kube, probe = service()
    plan = controller.plan(plan_request())

    assert plan.action == "DEPLOY"
    created = controller.apply_runtime(
        plan.runtime_name,
        create_request(plan.plan_hash),
    )
    replay = controller.apply_runtime(
        plan.runtime_name,
        create_request(plan.plan_hash),
    )

    assert created.phase == "SERVICE_READY"
    assert created.management_mode == "controller"
    assert created.mutable is True
    assert replay.runtime_name == created.runtime_name
    assert kube.runtime_apply_calls == [created.runtime_name]
    assert probe.calls[-1] == created.service_name


def test_apply_rejects_stale_plan_name_hash_and_conflicting_replay():
    controller, kube, _ = service()
    plan = controller.plan(plan_request())

    with pytest.raises(ControllerValidationError, match="name"):
        controller.apply_runtime("different-name", create_request(plan.plan_hash))
    with pytest.raises(ControllerConflict, match="plan"):
        controller.apply_runtime(
            plan.runtime_name,
            create_request("f" * 64),
        )

    create_managed_runtime(controller)
    conflicting = create_request(plan.plan_hash)
    conflicting.request_ref.payload_hash = "9" * 64
    with pytest.raises(ControllerConflict, match="different"):
        controller.apply_runtime(plan.runtime_name, conflicting)
    assert len(kube.runtime_apply_calls) == 1


def test_restart_is_idempotent_and_external_runtime_is_read_only():
    controller, kube, _ = service()
    created = create_managed_runtime(controller)

    restarted = controller.restart_runtime(created.runtime_name, action_request())
    replay = controller.restart_runtime(created.runtime_name, action_request())

    assert restarted.runtime_name == created.runtime_name
    assert replay.runtime_name == created.runtime_name
    assert len(kube.runtime_patches) == 1
    assert kube.runtime_patches[0][1]["restartNonce"] == "d" * 64

    with pytest.raises(ControllerNotFound):
        controller.restart_runtime("device-serial-jetson", action_request())


def test_retire_checks_edgex_consumers_and_action_payload():
    controller, kube, probe = service(consumers=2)
    created = create_managed_runtime(controller)

    with pytest.raises(ControllerConflict, match="consumers"):
        controller.retire_runtime(created.runtime_name, action_request())

    probe.consumers = 0
    retired = controller.retire_runtime(created.runtime_name, action_request())
    assert retired.phase == "RETIRED"
    assert probe.consumer_calls[-1] == created.service_name
    assert [kind for kind, _ in kube.deleted] == [
        "Deployment",
        "Service",
        "ConfigMap",
        "NetworkPolicy",
    ]


def test_list_external_runtime_uses_both_workload_and_edgex_readback(tmp_path):
    from pathlib import Path

    repository_catalog = RuntimeTemplateCatalog.load(
        Path(__file__).resolve().parents[1] / "config" / "runtime_templates.json"
    )
    kube = FakeKubernetesGateway(deployment_ready=True)
    probe = FakeEdgeXServiceProbe(ready=True, consumers=6)
    controller = AdapterControllerService(
        repository_catalog,
        kube,
        probe,
        RuntimeReconciler(kube, probe, namespace="edgex-edge"),
        namespace="edgex-edge",
    )

    runtimes = controller.list_runtimes()
    indexed = {item.runtime_name: item for item in runtimes}

    assert indexed["device-serial-jetson"].phase == "SERVICE_READY"
    assert indexed["device-serial-jetson"].management_owner == "argocd"
    assert indexed["device-serial-jetson"].mutable is False
    assert indexed["device-serial-jetson"].consumers == 6
    assert indexed["device-sensehat-raspi"].phase == "SERVICE_READY"


def test_plan_blocks_when_catalog_node_is_not_ready():
    kube = FakeKubernetesGateway(
        deployment_ready=True,
        target_node_ready=False,
    )
    probe = FakeEdgeXServiceProbe(ready=True)
    controller = AdapterControllerService(
        catalog(),
        kube,
        probe,
        RuntimeReconciler(kube, probe, namespace="edgex-edge"),
        namespace="edgex-edge",
    )

    plan = controller.plan(plan_request())

    assert plan.action == "BLOCKED"
    assert [reason.code for reason in plan.reasons] == ["node_not_ready"]
