from pathlib import Path

from app.catalog import RuntimeTemplateCatalog
from app.models import (
    RuntimeApplyRequest,
    RuntimeNetworkEgress,
    RuntimePlan,
    RuntimeTemplate,
)
from app.renderer import render_adapter_runtime, render_runtime_workload


DIGEST_IMAGE = "registry.example/device-serial@sha256:" + ("a" * 64)


def deployable_template() -> RuntimeTemplate:
    return RuntimeTemplate.model_validate(
        {
            "templateId": "serial-managed-v2",
            "adapterId": "serial-managed",
            "displayName": "Managed Serial",
            "protocolName": "serial",
            "verificationState": "template-verified",
            "deploymentEnabled": True,
            "image": DIGEST_IMAGE,
            "servicePort": 59930,
            "hardwareBindings": [
                {
                    "bindingId": "edge-serial-02",
                    "displayName": "Edge Serial 02",
                    "nodeName": "edge-node-02",
                    "hostDevicePath": "/dev/serial/by-id/device-02",
                    "containerDevicePath": "/dev/serial-02",
                    "deviceType": "CharDevice",
                    "requiresPrivileged": True,
                }
            ],
        }
    )


def deploy_plan() -> RuntimePlan:
    return RuntimePlan(
        action="DEPLOY",
        allowed=True,
        adapter_id="serial-managed",
        template_id="serial-managed-v2",
        runtime_name="adapter-serial-managed-abc123",
        service_name="adapter-serial-managed-abc123",
        target_node="edge-node-02",
        hardware_binding_id="edge-serial-02",
        management_mode="controller",
        verification_state="template-verified",
        plan_hash="b" * 64,
    )


def apply_request() -> RuntimeApplyRequest:
    return RuntimeApplyRequest(
        request_id="c" * 64,
        payload_hash="d" * 64,
        plan_hash="b" * 64,
    )


def runtime_cr() -> dict:
    resource = render_adapter_runtime(
        deploy_plan(),
        deployable_template(),
        apply_request(),
        namespace="edgex-edge",
    )
    resource["metadata"]["uid"] = "runtime-uid-01"
    return resource


def test_adapter_runtime_cr_contains_identity_not_runtime_manifest_fields():
    resource = render_adapter_runtime(
        deploy_plan(),
        deployable_template(),
        apply_request(),
        namespace="edgex-edge",
    )

    assert resource["apiVersion"] == "edgeai.etri.re.kr/v1alpha1"
    assert resource["kind"] == "AdapterRuntime"
    assert resource["metadata"]["namespace"] == "edgex-edge"
    assert resource["metadata"]["finalizers"] == [
        "edgeai.etri.re.kr/runtime-cleanup"
    ]
    assert resource["spec"] == {
        "templateId": "serial-managed-v2",
        "adapterId": "serial-managed",
        "targetNode": "edge-node-02",
        "hardwareBindingId": "edge-serial-02",
        "edgeX": {
            "serviceName": "adapter-serial-managed-abc123",
            "messageBusHost": "edgex-messagebus.edgex-system.svc.cluster.local",
            "messageBusPort": 1883,
        },
        "desiredState": "Running",
        "restartNonce": "",
        "requestRef": {
            "requestId": "c" * 64,
            "payloadHash": "d" * 64,
            "planHash": "b" * 64,
        },
    }
    text = str(resource["spec"])
    for forbidden in (
        "registry.example",
        "hostDevicePath",
        "containerDevicePath",
        "clusterIP",
        "podIP",
        "command",
    ):
        assert forbidden not in text


def test_renderer_uses_only_template_pinned_runtime_details():
    resources = render_runtime_workload(
        runtime_cr(),
        deployable_template(),
        namespace="edgex-edge",
    )
    indexed = {(item["kind"], item["metadata"]["name"]): item for item in resources}
    name = "adapter-serial-managed-abc123"

    assert set(indexed) == {
        ("ConfigMap", name),
        ("Deployment", name),
        ("Service", name),
        ("NetworkPolicy", name),
    }
    for resource in resources:
        assert resource["metadata"]["namespace"] == "edgex-edge"
        assert resource["metadata"]["labels"][
            "app.kubernetes.io/managed-by"
        ] == "edge-adapter-controller"
        assert resource["metadata"]["ownerReferences"][0]["uid"] == "runtime-uid-01"

    deployment = indexed[("Deployment", name)]
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "edge-node-02"}
    assert pod.get("hostNetwork", False) is False
    assert container["image"] == DIGEST_IMAGE
    assert container["env"][0] == {
        "name": "EDGEX_SERVICE_NAME",
        "value": name,
    }
    assert {
        item["name"]: item["value"]
        for item in container["env"]
        if "value" in item
    }["MESSAGEBUS_HOST"] == "edgex-messagebus.edgex-system.svc.cluster.local"
    assert container["securityContext"]["privileged"] is True
    device_volume = next(
        item for item in pod["volumes"] if item["name"] == "hardware-device"
    )
    assert device_volume["hostPath"] == {
        "path": "/dev/serial/by-id/device-02",
        "type": "CharDevice",
    }

    service = indexed[("Service", name)]
    assert "clusterIP" not in service["spec"]
    assert service["spec"]["ports"][0]["port"] == 59930
    assert "podIP" not in str(resources)


def test_restart_nonce_only_changes_controller_owned_pod_template_annotation():
    resource = runtime_cr()
    first = render_runtime_workload(
        resource,
        deployable_template(),
        namespace="edgex-edge",
    )
    resource["spec"]["restartNonce"] = "restart-01"
    restarted = render_runtime_workload(
        resource,
        deployable_template(),
        namespace="edgex-edge",
    )

    first_deployment = next(item for item in first if item["kind"] == "Deployment")
    restarted_deployment = next(
        item for item in restarted if item["kind"] == "Deployment"
    )
    assert "edgeai.etri.re.kr/restart-nonce" not in (
        first_deployment["spec"]["template"]["metadata"].get("annotations") or {}
    )
    assert restarted_deployment["spec"]["template"]["metadata"]["annotations"][
        "edgeai.etri.re.kr/restart-nonce"
    ] == "restart-01"


def test_renderer_adds_only_catalog_approved_protocol_egress():
    template = deployable_template().model_copy(
        update={
            "network_egress": [
                RuntimeNetworkEgress(
                    namespace="edgex-edge",
                    pod_selector={
                        "app.kubernetes.io/name": "edge-modbus-simulator"
                    },
                    ports=[1502],
                )
            ]
        }
    )

    resources = render_runtime_workload(
        runtime_cr(),
        template,
        namespace="edgex-edge",
    )
    policy = next(item for item in resources if item["kind"] == "NetworkPolicy")

    assert policy["spec"]["egress"][-1] == {
        "to": [
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": "edgex-edge"
                    }
                },
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "edge-modbus-simulator"
                    }
                },
            }
        ],
        "ports": [{"protocol": "TCP", "port": 1502}],
    }


def test_official_edgex_runtime_uses_sdk_instance_service_identity():
    template = RuntimeTemplateCatalog.load(
        (
            Path(__file__).resolve().parents[1]
            / "config"
            / "runtime_templates.json"
        )
    ).require("modbus-device-service-v1")
    name = "adapter-modbus-6a19a499ed"
    plan = RuntimePlan(
        action="DEPLOY",
        allowed=True,
        adapter_id="modbus",
        template_id="modbus-device-service-v1",
        runtime_name=name,
        service_name="device-modbus_6a19a499ed",
        target_node="etri-dev0001-jetorn",
        hardware_binding_id="jetson-modbus-tcp-simulator-001",
        management_mode="controller",
        verification_state="template-verified",
        plan_hash="e" * 64,
    )
    resource = render_adapter_runtime(
        plan,
        template,
        RuntimeApplyRequest(
            request_id="f" * 64,
            payload_hash="1" * 64,
            plan_hash="e" * 64,
        ),
        namespace="edgex-edge",
    )
    resource["metadata"]["uid"] = "modbus-runtime-uid"

    resources = render_runtime_workload(
        resource,
        template,
        namespace="edgex-edge",
    )
    deployment = next(
        item for item in resources if item["kind"] == "Deployment"
    )
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {
        item["name"]: item["value"]
        for item in container["env"]
        if "value" in item
    }

    assert "-i=6a19a499ed" in container["args"]
    assert env["EDGEX_SERVICE_NAME"] == "device-modbus_6a19a499ed"
    assert env["SERVICE_HOST"] == (
        "adapter-modbus-6a19a499ed.edgex-edge.svc.cluster.local"
    )
