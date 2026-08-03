from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts import (
    Measurement,
    ProductionContext,
    ProductionQualityTelemetry,
    PumpMotorTelemetry,
    contract_schemas,
)


def pump_payload() -> dict:
    return {
        "schemaVersion": "okdong.pump-motor.telemetry/v1",
        "eventId": "event-001",
        "sourceType": "sensor",
        "deviceId": "sensor-001",
        "assetId": "pump-001",
        "nodeId": "edge-001",
        "observedAt": "2026-08-03T10:00:00+09:00",
        "signals": {
            "accelerationX": {"value": 1.5, "unit": "m/s2"},
            "accelerationY": {"value": 2.5, "unit": "m/s2"},
            "accelerationZ": {"value": 3.5, "unit": "m/s2"},
            "temperature": {"value": 42.0, "unit": "Cel"},
            "additional": {
                "motorCurrent": {"value": 4.2, "unit": "A"},
            },
        },
    }


def test_pump_contract_accepts_typed_signals_and_preserves_camel_case() -> None:
    telemetry = PumpMotorTelemetry.model_validate(pump_payload())

    assert telemetry.asset_id == "pump-001"
    assert telemetry.observed_at.utcoffset() is not None
    assert telemetry.signals.additional["motorCurrent"].unit == "A"
    serialized = telemetry.model_dump(mode="json", by_alias=True)
    assert serialized["schemaVersion"] == "okdong.pump-motor.telemetry/v1"
    assert serialized["signals"]["accelerationX"]["value"] == 1.5


def test_production_quality_contract_keeps_unconfirmed_plc_fields_as_map() -> None:
    telemetry = ProductionQualityTelemetry(
        event_id="quality-001",
        source_type="mes",
        line_id="line-01",
        observed_at=datetime.now(timezone.utc),
        production=ProductionContext(production_id="work-001", lot_id="lot-01"),
        process_values={"futureOkdongTag": Measurement(value=12.5, unit="unknown")},
        quality_label="unknown",
    )

    assert telemetry.production.production_id == "work-001"
    assert list(telemetry.process_values) == ["futureOkdongTag"]


@pytest.mark.parametrize(
    "change",
    [
        {"observedAt": "2026-08-03T10:00:00"},
        {"unexpected": "not allowed"},
        {
            "signals": {
                "accelerationX": {"value": "NaN", "unit": "raw"},
                "accelerationY": {"value": 2, "unit": "raw"},
                "accelerationZ": {"value": 3, "unit": "raw"},
                "temperature": {"value": 4, "unit": "raw"},
            }
        },
    ],
)
def test_pump_contract_rejects_ambiguous_or_invalid_payload(change: dict) -> None:
    payload = pump_payload()
    payload.update(change)

    with pytest.raises(ValidationError):
        PumpMotorTelemetry.model_validate(payload)


def test_contract_catalog_exposes_only_versioned_supported_contracts() -> None:
    schemas = contract_schemas()

    assert set(schemas) == {"pump-motor", "production-quality"}
    pump_schema = schemas["pump-motor"]
    quality_schema = schemas["production-quality"]
    assert "schemaVersion" in pump_schema["properties"]
    assert "processValues" in quality_schema["properties"]
