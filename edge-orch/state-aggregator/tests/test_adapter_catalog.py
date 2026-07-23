from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapter_catalog import AdapterCatalog
from app.config import Settings
from app.device_management_models import DeviceOnboardingRequest, DevicePatchRequest


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "config" / "adapter_catalog.json"
)


@pytest.fixture
def catalog() -> AdapterCatalog:
    return AdapterCatalog.load(CATALOG_PATH)


def serial_protocol(**overrides):
    values = {
        "Port": "/dev/arduino-001",
        "BaudRate": 115200,
        "DeviceID": "arduino-001",
        "ResourceName": "temperature_raw",
    }
    values.update(overrides)
    return values


def test_catalog_exposes_only_live_validated_adapters_as_installed(catalog):
    statuses = {item.adapter_id: item.declared_status for item in catalog.adapters}

    assert statuses == {
        "serial-jetson": "installed",
        "sensehat-raspi": "installed",
        "modbus": "unsupported",
        "opcua": "unsupported",
        "mqtt": "unsupported",
        "rtsp": "unsupported",
    }


def test_catalog_uses_current_device_service_and_node_identity(catalog):
    serial = catalog.require("serial-jetson")
    sensehat = catalog.require("sensehat-raspi")

    assert serial.service_name == "device-serial-jetson"
    assert serial.protocol_name == "serial"
    assert serial.node_name == "etri-dev0001-jetorn"
    assert sensehat.service_name == "device-sensehat-raspi"
    assert sensehat.protocol_name == "i2c"
    assert sensehat.node_name == "etri-dev0003-raspi5"


def test_catalog_separates_installed_runtime_from_deployment_verification(catalog):
    serial = catalog.require("serial-jetson")
    sensehat = catalog.require("sensehat-raspi")

    assert serial.runtime.mode == "external"
    assert serial.runtime.management_owner == "argocd"
    assert serial.runtime.verification_state == "hardware-verified"
    assert serial.runtime.template_id == "serial-device-service-v1"
    assert serial.runtime.deployment_enabled is False
    assert [item.binding_id for item in serial.runtime.hardware_bindings] == [
        "jetson-arduino-serial-001"
    ]
    assert serial.runtime.hardware_bindings[0].node_name == "etri-dev0001-jetorn"
    assert serial.runtime.hardware_bindings[0].device_path == "/dev/arduino-001"
    assert serial.runtime.hardware_bindings[0].protocol_properties == {
        "Port": "/dev/arduino-001",
        "BaudRate": 115200,
        "DeviceID": "arduino-001",
    }
    assert serial.runtime.reuse_policy.binding_fields == [
        "Port",
        "BaudRate",
        "DeviceID",
    ]
    assert serial.runtime.reuse_policy.route_fields == ["ResourceName"]

    assert sensehat.runtime.mode == "external"
    assert sensehat.runtime.management_owner == "argocd"
    assert sensehat.runtime.verification_state == "hardware-verified"
    assert sensehat.runtime.template_id == "sensehat-device-service-v1"
    assert sensehat.runtime.deployment_enabled is False
    assert sensehat.runtime.hardware_bindings[0].binding_id == (
        "raspi5-sensehat-i2c-001"
    )
    assert sensehat.runtime.reuse_policy.route_fields == ["ResourceGroup"]


def test_unverified_protocols_are_visible_but_never_deployable(catalog):
    for adapter_id in ("modbus", "opcua", "mqtt", "rtsp"):
        adapter = catalog.require(adapter_id)
        assert adapter.runtime.mode == "unavailable"
        assert adapter.runtime.verification_state == "unverified"
        assert adapter.runtime.deployment_enabled is False
        assert adapter.runtime.hardware_bindings == []


def test_catalog_rejects_duplicate_hardware_binding_identity():
    from app.device_management_models import AdapterCatalogDocument

    payload = {
        "version": 2,
        "adapters": [
            {
                "adapterId": "first",
                "displayName": "first",
                "protocolName": "serial",
                "declaredStatus": "unsupported",
                "runtime": {
                    "mode": "unavailable",
                    "verificationState": "unverified",
                    "hardwareBindings": [
                        {
                            "bindingId": "shared-binding",
                            "displayName": "shared",
                            "nodeName": "edge-01",
                            "devicePath": "/dev/example",
                        }
                    ],
                },
            },
            {
                "adapterId": "second",
                "displayName": "second",
                "protocolName": "i2c",
                "declaredStatus": "unsupported",
                "runtime": {
                    "mode": "unavailable",
                    "verificationState": "unverified",
                    "hardwareBindings": [
                        {
                            "bindingId": "shared-binding",
                            "displayName": "shared",
                            "nodeName": "edge-02",
                            "devicePath": "/dev/example-2",
                        }
                    ],
                },
            },
        ],
    }

    with pytest.raises(ValueError, match="hardware binding"):
        AdapterCatalog(AdapterCatalogDocument.model_validate(payload))


def test_serial_protocol_accepts_driver_supported_endpoint(catalog):
    assert catalog.validate_protocol("serial-jetson", serial_protocol()) == []


def test_serial_protocol_rejects_unknown_field(catalog):
    errors = catalog.validate_protocol(
        "serial-jetson", serial_protocol(Password="must-not-pass")
    )

    assert [item.code for item in errors] == ["unknown_protocol_field"]
    assert errors[0].field == "Password"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"Port": "/dev/ttyUSB0"}, "hardware_binding_mismatch"),
        ({"BaudRate": 9600}, "hardware_binding_mismatch"),
        ({"DeviceID": "arduino-002"}, "hardware_binding_mismatch"),
        ({"ResourceName": "pressure_raw"}, "invalid_option"),
        ({"DeviceID": ""}, "empty_value"),
    ],
)
def test_serial_protocol_enforces_driver_constraints(catalog, overrides, code):
    errors = catalog.validate_protocol("serial-jetson", serial_protocol(**overrides))

    assert code in [item.code for item in errors]


def test_serial_protocol_accepts_an_additional_approved_physical_binding(catalog):
    serial = catalog.require("serial-jetson")
    second = serial.runtime.hardware_bindings[0].model_copy(
        update={
            "binding_id": "jetson-arduino-serial-002",
            "display_name": "Jetson Arduino USB Serial 2",
            "device_path": "/dev/arduino-002",
            "protocol_properties": {
                "Port": "/dev/arduino-002",
                "BaudRate": 57600,
                "DeviceID": "arduino-002",
            },
        }
    )
    serial.runtime.hardware_bindings.append(second)
    properties = serial_protocol(
        Port="/dev/arduino-002",
        BaudRate=57600,
        DeviceID="arduino-002",
    )

    assert catalog.validate_protocol("serial-jetson", properties) == []
    assert catalog.validate_hardware_binding(
        "serial-jetson",
        "jetson-arduino-serial-002",
        properties,
    ) == []
    mismatch = catalog.validate_hardware_binding(
        "serial-jetson",
        "jetson-arduino-serial-001",
        properties,
    )
    assert [item.code for item in mismatch] == ["hardware_binding_mismatch"]


def test_sensehat_profile_template_is_derived_from_resource_group(catalog):
    template = catalog.profile_template(
        "sensehat-raspi",
        {
            "Bus": "/dev/i2c-1",
            "DeviceID": "sensehat-001",
            "ResourceGroup": "orientation",
        },
    )

    assert [item.name for item in template.device_resources] == ["pitch", "roll", "yaw"]
    assert {item.properties.value_type for item in template.device_resources} == {"Float64"}
    assert template.device_commands[0].name == "orientation"
    assert [
        operation.device_resource
        for operation in template.device_commands[0].resource_operations
    ] == ["pitch", "roll", "yaw"]


def test_unsupported_adapter_cannot_validate_or_build_profile(catalog):
    errors = catalog.validate_protocol("mqtt", {})

    assert [item.code for item in errors] == ["unsupported_adapter"]
    with pytest.raises(ValueError, match="unsupported"):
        catalog.profile_template("mqtt", {})


def test_catalog_redacts_fields_marked_secret(catalog):
    assert catalog.redact_protocol(
        "mqtt", {"Broker": "mqtt://broker", "Password": "plain-text"}
    ) == {"Broker": "mqtt://broker", "Password": "***"}


def test_onboarding_request_accepts_camel_case_and_forbids_extra_fields():
    request = DeviceOnboardingRequest.model_validate(
        {
            "adapterId": "serial-jetson",
            "device": {
                "name": "virtual-temperature-002",
                "description": "second source",
                "labels": ["arduino"],
                "tags": {"physicalDeviceId": "arduino-001"},
                "protocolProperties": serial_protocol(),
                "adminState": "UNLOCKED",
            },
            "profile": {"mode": "existing", "name": "etri-arduino-temperature"},
        }
    )

    assert request.adapter_id == "serial-jetson"
    assert request.device.protocol_properties["BaudRate"] == 115200
    assert request.model_dump(by_alias=True)["profile"]["mode"] == "existing"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        DeviceOnboardingRequest.model_validate(
            {
                "adapterId": "serial-jetson",
                "device": {
                    "name": "virtual-temperature-002",
                    "protocolProperties": serial_protocol(),
                    "unsafeServiceName": "different-service",
                },
                "profile": {"mode": "existing", "name": "etri-arduino-temperature"},
            }
        )


@pytest.mark.parametrize(
    ("unsafe_field", "value"),
    [
        ("image", "registry.invalid/attacker:latest"),
        ("command", ["/bin/sh"]),
        ("hostPath", "/dev/ttyUSB0"),
        ("namespace", "kube-system"),
        ("clusterIP", "10.0.0.7"),
        ("podIP", "10.244.0.7"),
    ],
)
def test_onboarding_request_cannot_inject_runtime_fields(unsafe_field, value):
    payload = {
        "adapterId": "serial-jetson",
        "device": {
            "name": "virtual-temperature-002",
            "protocolProperties": serial_protocol(),
        },
        "profile": {"mode": "existing", "name": "etri-arduino-temperature"},
        unsafe_field: value,
    }

    with pytest.raises(ValidationError, match="extra_forbidden"):
        DeviceOnboardingRequest.model_validate(payload)


def test_create_profile_requires_descriptive_fields_and_patch_is_allowlisted():
    with pytest.raises(ValidationError, match="manufacturer"):
        DeviceOnboardingRequest.model_validate(
            {
                "adapterId": "serial-jetson",
                "device": {
                    "name": "virtual-temperature-002",
                    "protocolProperties": serial_protocol(),
                },
                "profile": {"mode": "create", "name": "temperature-v2"},
            }
        )

    patch = DevicePatchRequest.model_validate(
        {
            "description": "updated",
            "labels": ["line-a"],
            "tags": {"line": "a"},
            "protocolProperties": serial_protocol(),
            "adminState": "LOCKED",
        }
    )
    assert patch.admin_state == "LOCKED"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        DevicePatchRequest.model_validate({"serviceName": "other-service"})


def test_settings_keep_management_disabled_without_secrets(monkeypatch):
    monkeypatch.delenv("DEVICE_MANAGEMENT_ENABLED", raising=False)
    monkeypatch.delenv("DEVICE_MANAGEMENT_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("DEVICE_MANAGEMENT_HMAC_KEY", raising=False)

    settings = Settings()

    assert settings.device_management_enabled is False
    assert settings.device_management_admin_token is None
    assert settings.device_management_hmac_key is None
    assert settings.device_management_operation_limit == 256
    assert settings.adapter_catalog_path.name == "adapter_catalog.json"
