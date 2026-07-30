from pathlib import Path

import pytest

from app.catalog import RuntimeTemplateCatalog
from app.models import RuntimeApplyRequest, RuntimeObservation, RuntimePlanRequest
from app.planner import RuntimePlanner
from app.renderer import render_adapter_runtime, render_runtime_workload
from app.runtime_settings import (
    normalize_runtime_settings,
    render_runtime_environment,
    runtime_settings_hash,
)


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "runtime_templates.json"
)
BROKER = "mqtt://edge-mqtt-simulator.edgex-edge.svc.cluster.local:1883"


@pytest.fixture
def catalog() -> RuntimeTemplateCatalog:
    return RuntimeTemplateCatalog.load(CATALOG_PATH)


def mqtt_request(**overrides) -> RuntimePlanRequest:
    payload = {
        "adapterId": "mqtt",
        "targetNode": "etri-dev0001-jetorn",
        "hardwareBindingId": "jetson-mqtt-network-001",
        "mode": "auto",
        "settings": {
            "Broker": BROKER,
            "IncomingTopic": "incoming/data/#",
            "Qos": 0,
        },
    }
    payload.update(overrides)
    return RuntimePlanRequest.model_validate(payload)


def test_mqtt_runtime_settings_are_normalized_and_rendered(catalog):
    template = catalog.require("mqtt-device-service-v1")
    normalized = normalize_runtime_settings(template, mqtt_request().settings)

    assert normalized == {
        "Broker": BROKER,
        "IncomingTopic": "incoming/data/#",
        "Qos": 0,
    }
    environment = {
        item["name"]: item["value"]
        for item in render_runtime_environment(
            template,
            normalized,
            service_name="device-mqtt_fixture0001",
        )
    }
    assert environment == {
        "MQTTBROKERINFO_SCHEMA": "tcp",
        "MQTTBROKERINFO_HOST": (
            "edge-mqtt-simulator.edgex-edge.svc.cluster.local"
        ),
        "MQTTBROKERINFO_PORT": "1883",
        "MQTTBROKERINFO_CLIENTID": "device-mqtt_fixture0001",
        "MQTTBROKERINFO_INCOMINGTOPIC": "incoming/data/#",
        "MQTTBROKERINFO_QOS": "0",
        "MQTTBROKERINFO_AUTHMODE": "none",
    }


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (
            {
                "Broker": "mqtt://user:password@192.168.0.10:1883",
                "IncomingTopic": "incoming/data/#",
                "Qos": 0,
            },
            "credentials",
        ),
        (
            {
                "Broker": "mqtt://10.0.0.10:1883",
                "IncomingTopic": "incoming/data/#",
                "Qos": 0,
            },
            "allowlist",
        ),
        (
            {
                "Broker": BROKER,
                "IncomingTopic": "#",
                "Qos": 0,
            },
            "invalid format",
        ),
        (
            {
                "Broker": BROKER,
                "IncomingTopic": "incoming/data/#",
                "Qos": 3,
            },
            "allowed option",
        ),
        (
            {
                "Broker": BROKER,
                "IncomingTopic": "incoming/data/#",
                "Qos": 0,
                "Image": "attacker.example/device-mqtt:latest",
            },
            "not allowlisted",
        ),
    ],
)
def test_mqtt_runtime_settings_fail_closed(catalog, settings, message):
    template = catalog.require("mqtt-device-service-v1")

    with pytest.raises(ValueError, match=message):
        normalize_runtime_settings(template, settings)


def test_mqtt_runtime_reuse_requires_the_same_normalized_settings(catalog):
    planner = RuntimePlanner(catalog)
    request = mqtt_request()
    first = planner.plan(request, [])
    existing = RuntimeObservation(
        runtime_name=first.runtime_name,
        adapter_id="mqtt",
        template_id="mqtt-device-service-v1",
        service_name=first.service_name,
        target_node=request.target_node,
        hardware_binding_id=request.hardware_binding_id,
        management_mode="controller",
        management_owner="controller",
        purpose="development-fixture",
        verification_state="template-verified",
        phase="SERVICE_READY",
        settings_hash=first.settings_hash,
    )

    reused = planner.plan(request, [existing])
    changed = mqtt_request(
        settings={
            "Broker": BROKER,
            "IncomingTopic": "incoming/data/mqtt-temperature-sim-001/#",
            "Qos": 0,
        }
    )
    redeployed = planner.plan(changed, [existing])

    assert reused.action == "REUSE"
    assert reused.runtime_name == first.runtime_name
    assert redeployed.action == "DEPLOY"
    assert redeployed.runtime_name != first.runtime_name
    assert redeployed.settings_hash != first.settings_hash


def test_mqtt_workload_contains_only_validated_runtime_configuration(catalog):
    planner = RuntimePlanner(catalog)
    request = mqtt_request()
    template = catalog.require("mqtt-device-service-v1")
    plan = planner.plan(request, [])
    apply_request = RuntimeApplyRequest(
        request_id="a" * 64,
        payload_hash="b" * 64,
        plan_hash=plan.plan_hash,
    )
    runtime = render_adapter_runtime(
        plan,
        template,
        apply_request,
        namespace="edgex-edge",
        runtime_settings=request.settings,
    )
    runtime["metadata"]["uid"] = "mqtt-runtime-uid"

    resources = render_runtime_workload(
        runtime,
        template,
        namespace="edgex-edge",
    )
    indexed = {item["kind"]: item for item in resources}
    config = indexed["ConfigMap"]["data"]["configuration.yaml"]
    deployment = indexed["Deployment"]
    environment = {
        item["name"]: item["value"]
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }

    assert runtime["spec"]["runtimeSettings"] == request.settings
    assert runtime["spec"]["settingsHash"] == runtime_settings_hash(
        request.settings
    )
    assert "MQTTBrokerInfo:" in config
    assert (
        'Host: "edge-mqtt-simulator.edgex-edge.svc.cluster.local"'
        in config
    )
    assert 'IncomingTopic: "incoming/data/#"' in config
    assert "AuthMode: none" in config
    assert environment["MQTTBROKERINFO_CLIENTID"] == plan.service_name
    assert "PASSWORD" not in " ".join(environment)
    assert deployment["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/hostname": "etri-dev0001-jetorn"
    }
