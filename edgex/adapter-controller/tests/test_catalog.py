import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.catalog import RuntimeTemplateCatalog
from app.models import RuntimeCatalogDocument, RuntimePlanRequest


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "runtime_templates.json"
)


@pytest.fixture
def catalog() -> RuntimeTemplateCatalog:
    return RuntimeTemplateCatalog.load(CATALOG_PATH)


def test_catalog_records_external_hardware_verified_runtimes(catalog):
    serial = catalog.require("serial-device-service-v1")
    sensehat = catalog.require("sensehat-device-service-v1")

    assert serial.adapter_id == "serial-jetson"
    assert serial.verification_state == "hardware-verified"
    assert serial.deployment_enabled is False
    assert "@sha256:" in serial.image
    assert serial.hardware_bindings[0].binding_id == "jetson-arduino-serial-001"
    assert serial.external_runtimes[0].service_name == "device-serial-jetson"
    assert serial.external_runtimes[0].management_owner == "argocd"

    assert sensehat.adapter_id == "sensehat-raspi"
    assert sensehat.verification_state == "hardware-verified"
    assert sensehat.deployment_enabled is False
    assert sensehat.hardware_bindings[0].node_name == "etri-dev0003-raspi5"
    assert sensehat.external_runtimes[0].service_name == "device-sensehat-raspi"


def test_catalog_marks_unverified_protocol_templates_non_deployable(catalog):
    for template_id in (
        "modbus-device-service-v1",
        "opcua-device-service-v1",
        "mqtt-device-service-v1",
        "rtsp-device-service-v1",
    ):
        template = catalog.require(template_id)
        assert template.verification_state == "unverified"
        assert template.deployment_enabled is False
        assert template.image is None
        assert template.hardware_bindings == []


def test_catalog_rejects_mutable_or_unpinned_deployable_image(tmp_path):
    document = {
        "version": 1,
        "namespace": "edgex-edge",
        "templates": [
            {
                "templateId": "unsafe-template",
                "adapterId": "unsafe",
                "displayName": "unsafe",
                "protocolName": "serial",
                "verificationState": "template-verified",
                "deploymentEnabled": True,
                "image": "registry.invalid/unsafe:latest",
                "servicePort": 59990,
                "hardwareBindings": [
                    {
                        "bindingId": "unsafe-binding",
                        "displayName": "unsafe",
                        "nodeName": "edge-01",
                        "hostDevicePath": "/dev/unsafe",
                        "containerDevicePath": "/dev/unsafe",
                        "deviceType": "CharDevice",
                    }
                ],
            }
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document))

    with pytest.raises((ValidationError, ValueError), match="digest"):
        RuntimeTemplateCatalog.load(path)


def test_catalog_rejects_duplicate_binding_identity():
    payload = {
        "version": 1,
        "namespace": "edgex-edge",
        "templates": [
            {
                "templateId": "first-template",
                "adapterId": "first",
                "displayName": "first",
                "protocolName": "serial",
                "verificationState": "unverified",
                "deploymentEnabled": False,
                "servicePort": 59980,
                "hardwareBindings": [
                    {
                        "bindingId": "shared-binding",
                        "displayName": "shared",
                        "nodeName": "edge-01",
                    }
                ],
            },
            {
                "templateId": "second-template",
                "adapterId": "second",
                "displayName": "second",
                "protocolName": "i2c",
                "verificationState": "unverified",
                "deploymentEnabled": False,
                "servicePort": 59981,
                "hardwareBindings": [
                    {
                        "bindingId": "shared-binding",
                        "displayName": "shared",
                        "nodeName": "edge-02",
                    }
                ],
            },
        ],
    }

    with pytest.raises(ValueError, match="binding"):
        RuntimeTemplateCatalog(RuntimeCatalogDocument.model_validate(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image", "registry.invalid/attacker:latest"),
        ("command", ["/bin/sh"]),
        ("hostPath", "/dev/ttyUSB0"),
        ("namespace", "kube-system"),
        ("clusterIP", "10.0.0.9"),
        ("podIP", "10.244.0.9"),
    ],
)
def test_plan_request_forbids_runtime_manifest_injection(field, value):
    payload = {
        "adapterId": "serial-jetson",
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-arduino-serial-001",
        "mode": "auto",
        field: value,
    }

    with pytest.raises(ValidationError, match="extra_forbidden"):
        RuntimePlanRequest.model_validate(payload)
