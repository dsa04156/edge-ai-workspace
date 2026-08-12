import copy
import json

import pytest
from pydantic import ValidationError

from app.virtual_device_bindings import (
    BindingConfigError,
    MAX_EVENT_QUERY_PAGE_SIZE,
    VirtualDeviceBindingConfig,
    canonical_binding_bytes,
    config_revision,
    load_virtual_device_bindings,
)


def binding_document():
    return {
        "apiVersion": "virtual-device-binding/v1",
        "eventQuery": {
            "pageSize": 100,
            "maxPages": 10,
            "maxEventsPerDevice": 1000,
            "maxPriorProbeEventsPerDevice": 200,
        },
        "instances": [
            {
                "id": "vibration-01",
                "physicalDeviceRef": {
                    "name": "physical-vibration-01",
                    "expectedProfileName": "vibration-profile",
                },
                "capabilities": [
                    {
                        "id": "vibration",
                        "freshnessSeconds": 90,
                        "inputs": [
                            {
                                "inputId": "vibration.acceleration-x",
                                "capabilityField": "acceleration_x",
                                "required": True,
                                "bindings": [
                                    {
                                        "sourceName": "telemetry",
                                        "resourceName": "acceleration_x",
                                    }
                                ],
                                "acceptedValueTypes": ["Float32", "Float64"],
                                "acceptedUnits": ["g"],
                            }
                        ],
                    }
                ],
                "aiServiceRef": {
                    "serviceId": "pump-anomaly-v1",
                    "inputContract": "pump-anomaly-input/v1",
                    "bindingMode": "declarative_read_only",
                    "inputFieldMap": [
                        {
                            "inputId": "vibration.acceleration-x",
                            "aiField": "accel_x",
                        }
                    ],
                },
            }
        ],
    }


def test_valid_binding_document_is_normalized_with_public_aliases():
    validated = VirtualDeviceBindingConfig.model_validate(binding_document())

    assert validated.instances[0].capabilities[0].inputs[0].input_id == "vibration.acceleration-x"
    assert json.loads(canonical_binding_bytes(validated))["apiVersion"] == "virtual-device-binding/v1"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.update(unexpected=True),
        lambda document: document["instances"][0]["aiServiceRef"].update(endpoint="http://bad"),
        lambda document: document["instances"][0]["capabilities"][0]["inputs"][0].update(
            acceptedUnits=[]
        ),
        lambda document: document["instances"][0]["aiServiceRef"].update(
            bindingMode="read_write"
        ),
    ],
)
def test_invalid_or_unknown_binding_fields_are_rejected(mutate):
    document = binding_document()
    mutate(document)

    with pytest.raises(ValidationError):
        VirtualDeviceBindingConfig.model_validate(document)


def test_empty_document_is_test_only(tmp_path):
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps({"apiVersion": "virtual-device-binding/v1", "instances": []}))

    with pytest.raises(BindingConfigError):
        load_virtual_device_bindings(path)

    assert load_virtual_device_bindings(path, allow_empty_for_tests=True).instances == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document["instances"].append(copy.deepcopy(document["instances"][0])),
        lambda document: document["instances"][0]["capabilities"].append(
            copy.deepcopy(document["instances"][0]["capabilities"][0])
        ),
        lambda document: document["instances"][0]["capabilities"][0]["inputs"].append(
            copy.deepcopy(document["instances"][0]["capabilities"][0]["inputs"][0])
        ),
        lambda document: document["instances"][0]["aiServiceRef"]["inputFieldMap"].append(
            {"inputId": "unknown", "aiField": "other"}
        ),
        lambda document: document["instances"][0]["aiServiceRef"].update(inputFieldMap=[]),
    ],
)
def test_duplicate_ids_and_required_coverage_are_rejected(mutate):
    document = binding_document()
    mutate(document)

    with pytest.raises(ValidationError):
        VirtualDeviceBindingConfig.model_validate(document)


def test_alias_rename_and_ai_rename_are_independent_semantic_changes():
    original = VirtualDeviceBindingConfig.model_validate(binding_document())
    alias_rename = binding_document()
    alias_rename["instances"][0]["capabilities"][0]["inputs"][0]["bindings"][0][
        "resourceName"
    ] = "acceleration_x_v2"
    ai_rename = binding_document()
    ai_rename["instances"][0]["aiServiceRef"]["inputFieldMap"][0]["aiField"] = "accel_x_v2"

    alias_validated = VirtualDeviceBindingConfig.model_validate(alias_rename)
    ai_validated = VirtualDeviceBindingConfig.model_validate(ai_rename)

    assert alias_validated.instances[0].capabilities[0].inputs[0].input_id == original.instances[0].capabilities[0].inputs[0].input_id
    assert ai_validated.instances[0].capabilities[0].inputs[0].capability_field == original.instances[0].capabilities[0].inputs[0].capability_field
    assert config_revision(alias_validated) != config_revision(original)
    assert config_revision(ai_validated) != config_revision(original)


def test_event_query_hard_maxima_are_enforced():
    document = binding_document()
    document["eventQuery"]["pageSize"] = MAX_EVENT_QUERY_PAGE_SIZE + 1

    with pytest.raises(ValidationError):
        VirtualDeviceBindingConfig.model_validate(document)


def test_revision_uses_normalized_validated_content_not_json_formatting(tmp_path):
    document = binding_document()
    compact_path = tmp_path / "compact.json"
    pretty_path = tmp_path / "pretty.json"
    compact_path.write_text(json.dumps(document, separators=(",", ":")))
    pretty_path.write_text(json.dumps(document, indent=4, sort_keys=True))

    compact = load_virtual_device_bindings(compact_path)
    pretty = load_virtual_device_bindings(pretty_path)

    assert canonical_binding_bytes(compact) == canonical_binding_bytes(pretty)
    assert config_revision(compact) == config_revision(pretty)


def test_binding_identities_reject_whitespace_only_values():
    document = binding_document()
    document["instances"][0]["id"] = "   "

    with pytest.raises(ValidationError):
        VirtualDeviceBindingConfig.model_validate(document)
