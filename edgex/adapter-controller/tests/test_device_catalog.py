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


def test_device_catalog_exact_match_and_allowlists():
    catalog = DeviceBindingCatalog.load(
        BASE / "config" / "device_bindings.json"
    )

    match = catalog.match(candidate())

    assert catalog.errors == []
    assert match.confidence == "exact"
    assert match.binding.profile.name == "arduino-multisensor-v1"
    assert catalog.profile_document(match.binding)["deviceResources"]


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
    profile = (
        BASE
        / "config"
        / "profiles"
        / "arduino-multisensor-v1.json"
    )
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
    profile = (
        BASE
        / "config"
        / "profiles"
        / "arduino-multisensor-v1.json"
    )
    (profile_dir / profile.name).write_text(profile.read_text())
    invalid = dict(source["bindings"][0])
    invalid["bindingId"] = "invalid-image"
    invalid["adapter"] = dict(invalid["adapter"])
    invalid["adapter"]["image"] = "registry/device:latest"
    source["bindings"].append(invalid)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(source))

    catalog = DeviceBindingCatalog.load(path)

    assert len(catalog.bindings) == 1
    assert len(catalog.errors) == 1
    assert "invalid-image" in catalog.errors[0]
