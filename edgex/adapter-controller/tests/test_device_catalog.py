import json
from pathlib import Path

from app.device_catalog import DeviceBindingCatalog
from app.discovery_models import StoredCandidate
from datetime import datetime, timezone


BASE = Path(__file__).resolve().parents[1]


def candidate() -> StoredCandidate:
    now = datetime.now(timezone.utc)
    return StoredCandidate(
        candidate_id="candidate-" + "c" * 64,
        identity_hash="c" * 64,
        source="node-scan",
        node_name="etri-dev0001-jetorn",
        protocol="serial",
        transport="usb-serial",
        display_name="Arduino",
        hardware_id="75035303230351E0D171",
        properties={"VendorID": "2341", "ProductID": "0043"},
        first_seen=now,
        last_seen=now,
        updated_at=now,
    )


def modbus_candidate() -> StoredCandidate:
    now = datetime.now(timezone.utc)
    return StoredCandidate(
        candidate_id="candidate-" + "d" * 64,
        identity_hash="d" * 64,
        source="manual",
        node_name="etri-dev0001-jetorn",
        protocol="modbus",
        transport="modbus-tcp",
        display_name="Modbus TCP simulator",
        hardware_id="simulator-endpoint-001",
        properties={
            "Mode": "tcp",
            "Host": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
            "Port": 1502,
            "UnitID": 1,
        },
        first_seen=now,
        last_seen=now,
        updated_at=now,
    )


def sense_hat_candidate() -> StoredCandidate:
    now = datetime.now(timezone.utc)
    return StoredCandidate(
        candidate_id="candidate-" + "b" * 64,
        identity_hash="b" * 64,
        source="node-scan",
        node_name="etri-dev0003-raspi5",
        protocol="i2c",
        transport="i2c",
        display_name="raspberry-pi-sense-hat-v1",
        device_path="/dev/i2c-1",
        hardware_id=(
            "bus-1-raspberry-pi-sense-hat-v1-"
            "1c3d-5cbd-5fbc-6a68"
        ),
        model="raspberry-pi-sense-hat-v1",
        capabilities=[
            "temperature",
            "humidity",
            "pressure",
            "compass",
            "orientation",
            "gyroscope",
        ],
        recommended_profile="etri-sensehat-gyroscope",
        properties={
            "BusNumber": 1,
            "IdentityFingerprint": "1c3d-5cbd-5fbc-6a68",
            "IdentityCount": 4,
        },
        first_seen=now,
        last_seen=now,
        updated_at=now,
    )


def virtual_modbus_candidate() -> StoredCandidate:
    return modbus_candidate().model_copy(
        update={
            "candidate_id": "candidate-" + "e" * 64,
            "identity_hash": "e" * 64,
            "display_name": "Virtual temperature sensor 002",
            "hardware_id": "simulator-endpoint-002",
            "properties": {
                "Mode": "tcp",
                "Host": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
                "Port": 1502,
                "UnitID": 2,
            },
        }
    )


def third_virtual_modbus_candidate() -> StoredCandidate:
    return virtual_modbus_candidate().model_copy(
        update={
            "candidate_id": "candidate-" + "f" * 64,
            "identity_hash": "f" * 64,
            "display_name": "Virtual temperature sensor 003",
            "hardware_id": "simulator-endpoint-003",
            "properties": {
                "Mode": "tcp",
                "Host": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
                "Port": 1502,
                "UnitID": 3,
            },
        }
    )


def test_device_catalog_exact_match_and_allowlists():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )

    match = catalog.match(candidate())

    assert catalog.errors == []
    assert match.confidence == "exact"
    assert match.binding.profile.name == "arduino-multisensor-v1"
    assert catalog.profile_document(match.binding)["deviceResources"]


def test_device_catalog_exactly_matches_official_modbus_simulator_binding():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )

    match = catalog.match(modbus_candidate())

    assert catalog.errors == []
    assert match.confidence == "exact"
    assert match.binding.binding_id == "jetson-modbus-tcp-simulator-v1"
    assert match.binding.edge_x_protocol == "modbus-tcp"
    assert match.binding.connection_property_map == {
        "Address": "Host",
        "Port": "Port",
        "UnitID": "UnitID",
    }
    assert match.binding.auto_events[0].source_name == "temperature"
    profile = catalog.profile_document(match.binding)
    assert profile["deviceResources"][0]["attributes"] == {
        "primaryTable": "HOLDING_REGISTERS",
        "startingAddress": 0,
        "rawType": "Int16",
    }


def test_device_catalog_exactly_matches_composite_sense_hat_identity():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )

    match = catalog.match(sense_hat_candidate())

    assert catalog.errors == []
    assert match.confidence == "exact"
    assert match.binding.binding_id == "raspi5-sense-hat-v1"
    assert match.binding.registration_mode == "reuse-existing"
    assert match.binding.existing_device_name == (
        "imu-sensehat-gyroscope-01"
    )
    assert match.binding.runtime_hardware_binding_id == (
        "raspi5-sensehat-i2c-001"
    )
    assert catalog.profile_document(match.binding)["deviceResources"]


def test_device_catalog_exactly_matches_second_virtual_modbus_sensor():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )

    match = catalog.match(virtual_modbus_candidate())

    assert catalog.errors == []
    assert match.confidence == "exact"
    assert match.binding.binding_id == (
        "jetson-modbus-tcp-virtual-temperature-002-v1"
    )
    assert match.binding.runtime_hardware_binding_id == (
        "jetson-modbus-tcp-virtual-sensor-002"
    )
    assert match.binding.device_name_prefix == "virtual-temperature"


def test_device_catalog_exactly_matches_third_virtual_modbus_sensor():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )

    match = catalog.match(third_virtual_modbus_candidate())

    assert catalog.errors == []
    assert match.confidence == "exact"
    assert match.binding.binding_id == (
        "jetson-modbus-tcp-virtual-temperature-003-v1"
    )
    assert match.binding.runtime_hardware_binding_id == (
        "jetson-modbus-tcp-virtual-sensor-003"
    )
    assert match.binding.device_name_prefix == "virtual-temperature"


def test_manifest_profile_mismatch_blocks_known_usb_identity():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    unsupported = candidate().model_copy(
        update={"recommended_profile": "unsupported-board-v9"}
    )

    match = catalog.match(unsupported)

    assert match.confidence == "partial"
    assert match.binding is None


def test_failed_active_manifest_probe_blocks_known_usb_identity():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )
    timed_out = candidate().model_copy(
        update={"evidence": {"manifest": "SERIAL_MANIFEST_TIMEOUT"}}
    )

    match = catalog.match(timed_out)

    assert match.confidence == "partial"
    assert "did not succeed" in match.reason


def test_device_catalog_blocks_ambiguous_exact_match(tmp_path):
    source = json.loads(
        (BASE / "config" / "device_bindings.json").read_text()
    )
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    for profile in (BASE / "config" / "profiles").glob("*.json"):
        (profile_dir / profile.name).write_text(profile.read_text())
    duplicate = dict(source["bindings"][0])
    duplicate["bindingId"] = "duplicate-binding"
    source["bindings"].append(duplicate)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(source))

    match = DeviceBindingCatalog.load(path).match(candidate())

    assert match.confidence == "ambiguous"
    assert len(match.binding_ids) == 2


def test_invalid_binding_is_quarantined_without_killing_catalog(tmp_path):
    source = json.loads(
        (BASE / "config" / "device_bindings.json").read_text()
    )
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    for profile in (BASE / "config" / "profiles").glob("*.json"):
        (profile_dir / profile.name).write_text(profile.read_text())
    invalid = dict(source["bindings"][0])
    invalid["bindingId"] = "invalid-image"
    invalid["adapter"] = dict(invalid["adapter"])
    invalid["adapter"]["image"] = "registry/device:latest"
    source["bindings"].append(invalid)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(source))

    catalog = DeviceBindingCatalog.load(path)

    assert len(catalog.bindings) == len(source["bindings"]) - 1
    assert len(catalog.errors) == 1
    assert "invalid-image" in catalog.errors[0]
