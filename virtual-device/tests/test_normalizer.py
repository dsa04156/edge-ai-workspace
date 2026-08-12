from __future__ import annotations

from pathlib import Path

import pytest

from virtual_device.config import load_profile
from virtual_device.models import TelemetryEnvelope
from virtual_device.normalizer import Normalizer

from test_config import VALID_PROFILE, write_profile


@pytest.fixture
def normalizer(tmp_path: Path) -> Normalizer:
    return Normalizer(load_profile(write_profile(tmp_path, VALID_PROFILE)))


def test_profile_mapping_produces_only_declared_standard_fields(normalizer: Normalizer) -> None:
    sample = normalizer.normalize(
        {
            "sensor": "vibration",
            "device_id": "etri-pd0001-arduino",
            "source_ts": 1710000000,
            "x": "0.12",
            "y": 0.08,
            "z": 0.91,
            "raw_secret": "must-not-leak",
        },
        collected_at=1710000001,
    )

    assert set(sample.data) == {"acceleration_x", "acceleration_y", "acceleration_z"}
    assert sample.data["acceleration_x"].value == pytest.approx(0.12)
    assert sample.data["acceleration_x"].unit == "g"
    assert sample.quality.valid is True


def test_source_timestamp_is_preserved_separately_from_collected_at(normalizer: Normalizer) -> None:
    sample = normalizer.normalize(
        {"sensor": "vibration", "device_id": "pd", "ts": 1710000000, "x": 1, "y": 2, "z": 3},
        collected_at=1710000123,
    )

    assert sample.source_timestamp == 1710000000
    assert sample.collected_at == 1710000123


def test_envelope_uses_profile_identity_and_camel_case_wire_format(normalizer: Normalizer) -> None:
    sample = normalizer.normalize(
        {"sensor": "vibration", "device_id": "pd", "timestamp": 1710000000, "x": 1, "y": 2, "z": 3},
        collected_at=1710000001,
    )

    envelope = TelemetryEnvelope.from_sample(normalizer.profile, sample, sequence=123).to_dict()

    assert envelope["schemaVersion"] == "v1alpha1"
    assert envelope["virtualDeviceId"] == "etri-vd0001-vibration"
    assert envelope["physicalDeviceId"] == "etri-pd0001-arduino"
    assert envelope["nodeId"] == "etri-dev0001-jetorn"
    assert envelope["capability"] == "vibration"
    assert envelope["sourceTimestamp"] == 1710000000
    assert envelope["collectedAt"] == 1710000001
    assert envelope["sequence"] == 123
    assert "raw_secret" not in str(envelope)


def test_missing_required_mapping_field_marks_quality_invalid(normalizer: Normalizer) -> None:
    sample = normalizer.normalize(
        {"sensor": "vibration", "device_id": "pd", "ts": 1710000000, "x": 1, "z": 3},
        collected_at=1710000001,
    )

    assert sample.quality.valid is False
    assert "missing_required_property:y" in sample.quality.errors
    assert "acceleration_y" not in sample.data


def test_invalid_mapped_value_marks_quality_invalid_without_crashing(normalizer: Normalizer) -> None:
    sample = normalizer.normalize(
        {"sensor": "vibration", "device_id": "pd", "ts": 1710000000, "x": 1, "y": "bad", "z": 3},
        collected_at=1710000001,
    )

    assert sample.quality.valid is False
    assert "invalid_property:y:float" in sample.quality.errors
    assert "acceleration_y" not in sample.data
